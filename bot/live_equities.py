#!/usr/bin/env python3
"""Robinhood equities RSI(2) buy-the-dip — paper signal bot + simulated fills,
with a GATED LIVE execution mode (off by default).

DEFAULT = PAPER (execution='NONE'): this file EMITS actionable signals + maintains
a simulated paper book. A gated LIVE mode (EXECUTION_MODE='LIVE' + RH_LIVE_ENABLED)
places real orders on the Robinhood 'Agentic' account via hardening/rh_client.py —
see docs/ROBINHOOD_EXECUTION.md for the exact go-live switch and verification steps.
LIVE is OFF by default; the running paper-forward bot is unchanged.

STRATEGY (per research/ROBINHOOD_LANE_PLAN.md + REGIME_GATE_VALIDATION.md):
  Universe : 10 ETFs + top-50 S&P100 by 20d avg $volume (liquidity rule).
  Entry    : Wilder RSI(2) < 5  AND  close > SMA200  (per-name trend filter only).
             The index-level SPY>SMA200 regime gate was VALIDATED and REJECTED
             (see REGIME_GATE_VALIDATION.md): it made 2022 worse (0.81->0.21),
             left OOS PF unchanged (1.47->1.47), and cost ~21% return. Not deployed.
  Exit     : (1) 2xATR(14) intraday GTC stop, gap-aware; (2) 5-day time stop;
             (3) revert exit close>SMA5 OR RSI(2)>70.  No trailing stop.
  Risk     : 1%/trade sized by stop distance, capped at 5% capital/name;
             $150/day realized-loss cap (paper = tracked, enforced on new entries).
             Satellite sizing + explicit bear-year warning on every signal.

FILL MODEL (mirrors the backtest): signal at bar-t close -> paper entry at bar-t+1
OPEN; stop checked intraday from the entry bar forward (gap-through -> open, else
low<=stop -> stop). One open position per symbol (no pyramiding).

JOURNAL — the LAPTOP's read-path (DynamoDB table `trading-data`, us-east-1):
  RHSIG#<sym>        sk=<date>     today's actionable signal (action=ENTER/EXIT).
                                   ENTER fields: action, side, entry='next_open',
                                   stop_price, size_usd, size_shares, rsi2, sma200,
                                   sma5, atr14, regime, bear_warning, reason, ts.
                                   EXIT fields: action, exit_reason, exit_price,
                                   pnl_usd, pnl_pct, hold_days.
  RHPOS#<sym>        sk=current    current paper position (status=PENDING/OPEN/
                                   CLOSED) + entry/stop/size/planned-exit.
  RHTRADE#<sym>      sk=<entry_date>  immutable round-trip history (forward-test).
  RHLEDGER#<date>    sk=summary    daily realized P&L + $150 loss-cap status.
  RUN#live_equities  sk=<date>     once-per-day run marker.
  S3: research/scan-results/rh-equities/<Y>/<m>/<d>/<ts>.json  (full-day snapshot).

Schedule: daily after US close via Hermes cron (paper_rh_equities.sh). Dedupe on
RUN#live_equities/<date>. Numeric fields are stringified (matches equity_signals).

Usage:
  python bot/live_equities.py --dry-run          # compute+print, no AWS writes
  python bot/live_equities.py --limit 12         # smoke-test on a subset of names
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf
import boto3
import json
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
# SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback.
import os as _so, sys as _ss  # noqa: E402
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb  # noqa: E402
_sb()

from data.s3_archive import archive_scan_results  # noqa: E402
from bot.earnings_guard import load_upcoming_earnings  # noqa: E402

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

# ---- strategy parameters (paper capital is a SIMULATION input, not real money) ----
PAPER_CAPITAL = float(os.getenv('RH_PAPER_CAPITAL', '700'))
RISK_PCT = float(os.getenv('RH_RISK_PCT', '0.01'))        # 1%/trade
MAX_POS_PCT = float(os.getenv('RH_MAX_POS_PCT', '0.05'))  # 5% capital/name cap
DAY_LOSS_CAP = float(os.getenv('RH_DAY_LOSS_CAP', '150')) # $/day realized-loss cap

# ---- EXECUTION MODE (go-live switch) ----
# PAPER (default) = simulated fills at next open (current behaviour, unchanged).
# LIVE            = real Robinhood orders via hardening/rh_client.py, gated behind
#                   BOTH RH_EXECUTION_MODE='LIVE' AND RH_LIVE_ENABLED='true' (two
#                   independent switches, both default OFF) + account_mode check
#                   (agentic_allowed) + 1% risk + $150/day cap + stop chokepoint
#                   (place_equity_entry REJECTS stop_price<=0 and reverses any
#                   fill it cannot protect). See docs/ROBINHOOD_EXECUTION.md.
EXECUTION_MODE = os.getenv('RH_EXECUTION_MODE', 'PAPER').strip().upper()   # PAPER | LIVE
RH_LIVE_ENABLED = os.getenv('RH_LIVE_ENABLED', 'false').strip().lower() == 'true'
RH_LIVE_ACCOUNT = os.getenv('RH_LIVE_ACCOUNT', '515821577')  # 'Agentic' agentic_allowed acct

RSI2_THR = 5.0
STOP_ATR = 2.0
MAX_HOLD = 5
MAX_POSITIONS = int(os.getenv('RH_MAX_POSITIONS', '20'))  # LIVE concurrent-position ceiling
PAPER_MAX_POSITIONS = int(os.getenv('RH_PAPER_MAX_POSITIONS', '20'))  # PAPER ceiling (breadth testing)
MIN_BARS = 260                       # >= 1y so SMA200 is fully warmed
DATA_START = '2022-01-01'            # fixed anchor -> stable index positions
EARNINGS_GUARD_DAYS = int(os.getenv('EARNINGS_GUARD_DAYS', '5'))  # no entry into a name reporting within N days

# ---- universe (deterministic liquidity rule, NOT return cherry-picking) ----
# ETFs: the 10 validated names (XLE/XLB/XLU/XLRE excluded — KILL in the sweep).
ETFS = ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'XLF', 'XLK', 'XLV', 'XLP', 'XLI']
# Stocks: liquid S&P-1500 names, 20d avg $volume >= $500M/day (screened 2026-08-24).
STOCKS = [
    'AAL', 'AAPL', 'ABBV', 'ABNB', 'ABT', 'ACN', 'ADBE', 'ADI',
    'ADP', 'AMAT', 'AMD', 'AMGN', 'AMZN', 'ANET', 'APH', 'APP',
    'AVGO', 'AXON', 'AXP', 'AZO', 'BA', 'BAC', 'BKNG', 'BLK',
    'BMY', 'BRK-B', 'BSX', 'BX', 'C', 'CAT', 'CB', 'CDE',
    'CDNS', 'CEG', 'CI', 'CIEN', 'CMCSA', 'CME', 'CMG', 'CMI',
    'COF', 'COHR', 'COIN', 'COP', 'COST', 'CRM', 'CRWD', 'CSCO',
    'CSX', 'CTSH', 'CVNA', 'CVS', 'CVX', 'DASH', 'DDOG', 'DE',
    'DELL', 'DHR', 'DIS', 'DUK', 'EQIX', 'ETN', 'F', 'FCX',
    'FERG', 'FIX', 'FSLR', 'FTNT', 'GE', 'GEV', 'GILD', 'GLW',
    'GOOG', 'GOOGL', 'GS', 'HCA', 'HD', 'HL', 'HLT', 'HON',
    'HONA', 'HOOD', 'HPE', 'HUM', 'HWM', 'IBM', 'ICE', 'INTC',
    'INTU', 'ISRG', 'JCI', 'JNJ', 'JPM', 'KKR', 'KLAC', 'KO',
    'LIN', 'LITE', 'LLY', 'LMT', 'LOW', 'LRCX', 'MA', 'MAR',
    'MCD', 'MCHP', 'MCK', 'MDLZ', 'MDT', 'META', 'MMM', 'MNST',
    'MO', 'MPC', 'MPWR', 'MRK', 'MRNA', 'MRVL', 'MS', 'MSFT',
    'MU', 'NEE', 'NEM', 'NFLX', 'NKE', 'NOW', 'NVDA', 'NXPI',
    'ON', 'ORCL', 'ORLY', 'PANW', 'PATH', 'PEP', 'PFE', 'PG',
    'PGR', 'PH', 'PLD', 'PLTR', 'PM', 'PSX', 'PWR', 'PYPL',
    'QCOM', 'RCL', 'RDDT', 'REGN', 'ROST', 'RTX', 'SBUX', 'SCHW',
    'SHW', 'SMCI', 'SNDK', 'SNPS', 'SPGI', 'STX', 'SYK', 'T',
    'TDG', 'TER', 'TGT', 'TJX', 'TMO', 'TMUS', 'TRV', 'TSLA',
    'TT', 'TTWO', 'TWLO', 'TXN', 'UBER', 'UNH', 'UNP', 'UPS',
    'V', 'VLO', 'VRT', 'VRTX', 'VST', 'VZ', 'WBD', 'WDAY',
    'WDC', 'WELL', 'WFC', 'WMT', 'XOM', 'ZTS'
]
# Liquid sub-$35 small-ticket universe for the LIVE whole-share lane ($700).
# Screened 2026-08-24 (research/expand_universe_screen.py): close $3-$35 AND
# 20d avg $volume >= $50M, from the S&P 1500. Speculative crypto-miner/meme/
# distressed names (MARA/CLSK/RIOT/GME/PTON/SEDG/HIMS/CELH/RUN) excluded.
# RSI2 edge was validated on S&P100; this is forward-testing breadth.
SMALL_CAP_STOCKS = [
    'AAL', 'ACHC', 'ACI', 'ADT', 'AEO', 'AES', 'AGNC', 'ALHC',
    'AM', 'AMH', 'AMTM', 'AROC', 'ARR', 'AVTR', 'BANC', 'BAX',
    'BBWI', 'BEN', 'BF-B', 'BNL', 'BOX', 'BRX', 'BTU', 'CAG',
    'CCL', 'CDE', 'CHWY', 'CLF', 'CMCSA', 'CNH', 'COLB', 'CPB',
    'CPRI', 'CPRT', 'CRBG', 'CRGY', 'CSGP', 'CUZ', 'CZR', 'DBX',
    'DOC', 'DOCS', 'DOW', 'DV', 'EBC', 'ELAN', 'F', 'FA',
    'FHN', 'FIVN', 'FLG', 'FNB', 'GAP', 'GEN', 'GEO', 'GNTX',
    'GPK', 'GT', 'GTES', 'HAL', 'HBAN', 'HL', 'HOG', 'HPQ',
    'HR', 'HRL', 'HST', 'INVH', 'IVZ', 'JBLU', 'KD', 'KDP',
    'KEY', 'KHC', 'KIM', 'KMI', 'KMT', 'KRG', 'KSS', 'KVUE',
    'LBRT', 'LCID', 'LKQ', 'LUMN', 'LYFT', 'M', 'MAC', 'MAT',
    'MBGL', 'MGY', 'MIR', 'MOS', 'NCLH', 'NIO', 'NLY', 'NOG',
    'NOV', 'NVST', 'NWL', 'NWSA', 'OLN', 'ONB', 'OPCH', 'OPLN',
    'OUT', 'PATH', 'PBR', 'PCG', 'PEGA', 'PFE', 'PINS', 'PK',
    'PPL', 'PR', 'PSKY', 'PTEN', 'RELY', 'REZI', 'RF', 'RITM',
    'RIVN', 'RSI', 'RYN', 'SARO', 'SBRA', 'SHC', 'SIRI', 'SLM',
    'SMCI', 'SNAP', 'SOFI', 'STWD', 'T', 'TDC', 'TTD', 'UAA',
    'VALE', 'VFC', 'VICI', 'VLY', 'VNT', 'VSH', 'VTRS', 'VVV',
    'WAY', 'WBD', 'WEN', 'WMG', 'WRBY', 'WSC', 'WT', 'WU',
    'WY', 'XRAY'
]

def _load_smallcap_universe():
    """Load the expanded sub-$35 whole-share universe (full ~6,000-stock screen,
    ~363 names, blocklist-filtered) from smallcap_universe_full.json. Fallback to
    the hardcoded SMALL_CAP_STOCKS (154) if the file is missing/unreadable."""
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'research', 'smallcap_universe_full.json')
        with open(p, encoding='utf-8') as f:
            syms = [s for s in json.load(f).get('symbols', [])
                    if s.upper() not in SMALLCAP_BLOCKLIST]
        if syms:
            return syms
    except Exception as e:
        print(f'  [universe] smallcap load failed ({e!r}) — fallback to SMALL_CAP_STOCKS')
    return SMALL_CAP_STOCKS


SMALLCAP_BLOCKLIST = {'MARA', 'RIOT', 'CLSK', 'WULF', 'CIFR', 'BITF', 'HUT', 'IREN',
                      'GME', 'PTON', 'SEDG', 'HIMS', 'CELH', 'RUN'}


def _load_broad_universe():
    """Load the ~1,459-name tradeable universe (S&P 1500, price>$2, adv>=$10M)
    from the generated artifact `research/universe_1500.json`. Falls back to the
    hardcoded STOCKS list if the file is missing/unreadable — the bot must never
    break on a universe-load failure. Broad universe is PAPER-only; the LIVE lane
    stays on SMALL_CAP_STOCKS (sub-$35 whole-share)."""
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'research', 'universe_1500.json')
        with open(p, encoding='utf-8') as f:
            syms = json.load(f).get('symbols', [])
        if syms:
            return syms
    except Exception as e:
        print(f'  [universe] broad universe load failed ({e!r}) — falling back to STOCKS')
    return STOCKS


UNIVERSE = ETFS + _load_broad_universe()
BEAR_WARNING = ('true')  # this edge is negative in single bear years (2008 PF 0.36, 2022 PF 0.81)


def _s(v):
    """Stringify a float for DynamoDB; NaN -> ''."""
    try:
        f = float(v)
        return '' if f != f else str(round(f, 4))
    except (TypeError, ValueError):
        return str(v)


def _f(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return (100 - 100 / (1 + rs))


def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def indicators(df):
    d = df.copy()
    c = d['close']
    d['rsi2'] = rsi(c, 2).fillna(50.0)
    d['sma200'] = c.rolling(200).mean()
    d['sma5'] = c.rolling(5).mean()
    d['atr14'] = wilder_atr(d['high'], d['low'], c, 14)
    return d


def fetch(syms, start=DATA_START):
    """yfinance daily OHLCV (split+dividend adjusted) -> {sym: df}."""
    out = {}
    for sym in syms:
        try:
            df = yf.download(sym, start=start, interval='1d',
                             auto_adjust=True, progress=False)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            df.columns = [c.lower() for c in df.columns]
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df = df[~df.index.duplicated(keep='last')].sort_index()
            df = df[df['close'].notna() & (df['close'] > 0)]
            if len(df) >= MIN_BARS:
                out[sym] = df
        except Exception as e:
            print(f'  [{sym}] fetch error: {e!r}')
        time.sleep(0.15)  # pacing
    return out


def fetch_batch(syms, start=DATA_START):
    """Batch yfinance daily OHLCV — ONE download for all symbols -> {sym: df}.

    Drop-in replacement for fetch(): identical output shape (lowercased OHLCV
    columns, tz-naive DatetimeIndex, deduped, >= MIN_BARS rows). Falls back to
    the sequential fetch() if the batch call fails, so a yfinance change or a
    rate-limit can never break the bot. This is the scale lever: 1,500 names =
    1 network round-trip instead of 1,500.
    """
    if not syms:
        return {}
    out = {}
    try:
        raw = yf.download(' '.join(syms), start=start, interval='1d',
                          auto_adjust=True, progress=False, group_by='ticker',
                          threads=True)
    except Exception as e:
        print(f'  [fetch_batch] batch download failed ({e!r}) — falling back to sequential')
        return fetch(syms, start)
    if raw is None or raw.empty:
        return out
    tickers = raw.columns.get_level_values(0).unique()
    for sym in syms:
        try:
            if sym not in tickers:
                continue
            sub = raw[sym]
            if isinstance(sub, pd.Series):  # single-field degenerate case
                continue
            df = sub[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            df.columns = [c.lower() for c in df.columns]
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df = df[~df.index.duplicated(keep='last')].sort_index()
            df = df[df['close'].notna() & (df['close'] > 0)]
            if len(df) >= MIN_BARS:
                out[sym] = df
        except Exception as e:
            print(f'  [{sym}] fetch_batch error: {e!r}')
    return out


def position_size(capital, close, atr):
    """$ per name = min(1%/stop_pct, 5% cap). Returns (size_usd, stop_dist_pct)."""
    stop_dist = STOP_ATR * atr
    stop_pct = stop_dist / close if close > 0 else 1.0
    size_risk = (RISK_PCT * capital) / stop_pct if stop_pct > 0 else 0.0
    size_cap = MAX_POS_PCT * capital
    return min(size_risk, size_cap), stop_pct


def _get_rh_client():
    """Lazily build the Robinhood client (LIVE mode only). Imported here so the
    paper path never touches SSM/rh_client (and the dashboard can import this file)."""
    from hardening.rh_client import RHClient
    return RHClient(account_number=RH_LIVE_ACCOUNT)


def live_gate_ok(client, day_loss_used):
    """(ok, reason): gate LIVE entries. FAIL-CLOSED — every check must pass.

    Mirrors the never-lose-money discipline: explicit flag + hard-enable toggle,
    account-mode check (agentic_allowed only), 1% risk cap, $150/day loss cap.
    The stop-loss chokepoint (stop_price>0, never naked) is enforced by
    RHClient.place_equity_entry itself, not here.
    """
    if EXECUTION_MODE != 'LIVE':
        return False, f'execution mode is {EXECUTION_MODE}, not LIVE'
    if not RH_LIVE_ENABLED:
        return False, 'RH_LIVE_ENABLED is false'
    if RISK_PCT > 0.01:
        return False, f'RISK_PCT {RISK_PCT} exceeds 1% cap'
    if day_loss_used >= DAY_LOSS_CAP:
        return False, f'day loss ${day_loss_used:.2f} >= ${DAY_LOSS_CAP:.0f} cap'
    try:
        acct = client.get_account()
    except Exception as e:  # noqa: BLE001 - fail-closed
        return False, f'account check failed: {e!r}'
    if not acct.get('agentic_allowed'):
        return False, f"account {acct.get('account_number')} is not agentic_allowed"
    return True, 'ok'


def _live_exit_position(client, sym, shares):
    """Cancel resting stops + market-close a LIVE position; confirm the fill.

    Raises on ANY failure so the caller leaves the position OPEN for retry
    (fail-closed — never mark a broker position closed on an unconfirmed exit).
    NOTE: basic path; fill-confirmation + a Robinhood reconciler are follow-on
    work required before go-live (see docs/ROBINHOOD_EXECUTION.md).
    """
    from hardening.rh_client import RHOrderError
    for o in client.list_orders(symbol=sym):
        if (o.get('type') in ('stop_market', 'stop_limit')
                and (o.get('state') or '') in ('confirmed', 'queued', 'new',
                                                'partially_filled')):
            try:
                client.cancel_order(o['id'])
            except Exception as e:  # noqa: BLE001 - best-effort stop cancel
                print(f'[live] cancel stop {o.get("id")} failed (non-fatal): {e!r}')
    fill = client.place_equity_order(sym, 'sell', 'market', quantity=str(shares))
    oid = fill.get('id')
    state = (fill.get('state') or '').lower()
    for _ in range(20):  # up to ~10s
        if state == 'filled':
            return fill
        if state in ('cancelled', 'rejected'):
            raise RHOrderError(f'LIVE exit {sym} {state}')
        time.sleep(0.5)
        orders = client.list_orders(order_id=oid) if oid else []
        state = ((orders[0].get('state') if orders else state) or '').lower()
    raise RHOrderError(f'LIVE exit {sym} not confirmed filled (state={state})')


def load_book(table, dry_run):
    """Current paper positions: {sym: item} for status in (PENDING, OPEN)."""
    if dry_run:
        return {}
    book = {}
    try:
        lek = None
        while True:
            kw = dict(FilterExpression='begins_with(pk, :p)',
                      ExpressionAttributeValues={':p': 'RHPOS#'})
            if lek:
                kw['ExclusiveStartKey'] = lek
            resp = table.scan(**kw)
            for it in resp.get('Items', []):
                if it.get('sk') == 'current' and it.get('status') in ('PENDING', 'OPEN'):
                    book[it['pk'].split('#', 1)[1]] = it
            lek = resp.get('LastEvaluatedKey')
            if not lek:
                break
    except Exception as e:
        print(f'  [book] scan failed (fail-open, empty book): {e!r}')
    return book


_pending_writes = []  # batched DynamoDB writes, flushed once at end of run


def put_item(table, pk, sk, fields, dry_run):
    if dry_run:
        print(f'  [dry] {pk} / {sk} : ' + ', '.join(f'{k}={v}' for k, v in fields.items()))
        return
    _pending_writes.append({'pk': pk, 'sk': sk, **fields})


def flush_writes(table):
    """Flush accumulated writes via batch_writer (25 items/call → ~60 calls for
    1,500 names instead of 1,500). Fail-safe: on any error fall back to individual
    put_item so no position/signal write is ever lost. This is the cost lever for
    the vast-universe architecture."""
    if not _pending_writes:
        return
    n = len(_pending_writes)
    try:
        with table.batch_writer() as bw:
            for item in _pending_writes:
                bw.put_item(Item=item)
        print(f'  [batch] wrote {n} DynamoDB items (batch_writer)')
    except Exception as e:
        print(f'  [batch] flush failed ({e!r}) — falling back to individual writes')
        for item in _pending_writes:
            try:
                table.put_item(Item=item)
            except Exception as e2:
                print(f'  [put] {item["pk"]}/{item["sk"]} failed: {e2!r}')
    finally:
        _pending_writes.clear()


def main():
    global EXECUTION_MODE
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=0, help='cap symbols for a smoke test')
    ap.add_argument('--force', action='store_true',
                    help='bypass the daily-close finalization guard (dry-run TEST only)')
    args = ap.parse_args()

    # SAFETY: --force may ONLY bypass finalization for a --dry-run (no orders). It
    # must never let a LIVE run trade on a partial (unfinalized) bar.
    if args.force and not args.dry_run:
        print('[force] requires --dry-run — refusing (never bypass finalization for live orders)')
        return

    # SAFETY: --dry-run must NEVER place a real order. Force PAPER so no broker
    # call path (entry or exit) is reachable, even with RH_EXECUTION_MODE=LIVE in
    # the env. (Dry-run still exercises the full signal pipeline + gate logic.)
    if args.dry_run and EXECUTION_MODE == 'LIVE':
        print('[dry-run] LIVE env detected — forcing PAPER (dry-run never places orders)')
        EXECUTION_MODE = 'PAPER'

    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()

    # Data-freshness guard: daily signals need the FINALIZED close (>= 17:00 ET).
    try:
        import datetime as _dt
        from zoneinfo import ZoneInfo
        if _dt.datetime.now(ZoneInfo('America/New_York')).hour < 17 and not args.force:
            print(f'[{today}] live_equities SKIP — before daily-close finalization (stale-data guard)')
            return
    except Exception:
        pass

    # once-per-day dedupe (fail-open on read error, like equity_signals)
    if not args.dry_run:
        try:
            if table.get_item(Key={'pk': 'RUN#live_equities', 'sk': today}).get('Item'):
                print(f'[{today}] live_equities already ran today — skip')
                return
        except Exception as e:
            print(f'[{today}] dedupe read failed (fail-open): {e!r}')

    # LIVE whole-share lane uses the liquid sub-$35 sub-universe (the S&P100
    # universe is >$35, so $700 whole-share can't buy it). PAPER keeps full universe.
    _syms = _load_smallcap_universe() if EXECUTION_MODE == 'LIVE' else UNIVERSE
    syms = _syms[:args.limit] if args.limit else _syms
    pos_cap = MAX_POSITIONS if EXECUTION_MODE == 'LIVE' else PAPER_MAX_POSITIONS
    earnings_blacklist = load_upcoming_earnings(table, days_ahead=EARNINGS_GUARD_DAYS)
    if earnings_blacklist:
        print(f'  earnings guard: will not ENTER {len(earnings_blacklist)} symbols '
              f'reporting within {EARNINGS_GUARD_DAYS}d')
    print(f'fetching {len(syms)} symbols (start={DATA_START})…')
    bars = fetch_batch(syms)
    print(f'  got {len(bars)}/{len(syms)} symbols')

    book = load_book(table, args.dry_run)
    open_count = sum(1 for p in book.values() if p.get('status') == 'OPEN')
    committed = len(book)  # PENDING + OPEN

    day_loss_used = 0.0
    cap_breached = False
    enters, exits = [], []
    payload = {'lane': 'robinhood-equities', 'date': today, 'paper_capital': PAPER_CAPITAL,
               'signals': []}

    # LIVE client (lazy, only when EXECUTION_MODE == 'LIVE'). Fail-closed: a failed
    # init disables LIVE entries for the whole run (paper/other lanes unaffected).
    client = None
    live_client_error = None
    if EXECUTION_MODE == 'LIVE':
        try:
            client = _get_rh_client()
            print(f"[live] Robinhood client ready (account={client.account_number or 'auto'})")
        except Exception as e:  # noqa: BLE001
            live_client_error = f'RHClient init failed: {e!r}'
            print(f'[live] {live_client_error} — no LIVE entries this run')

    for sym in syms:
        df = bars.get(sym)
        if df is None:
            continue
        d = indicators(df)
        last = d.iloc[-1]
        o, h, l, c = (float(last[k]) for k in ('open', 'high', 'low', 'close'))
        r2 = _f(last['rsi2']); ma200 = _f(last['sma200'])
        ma5 = _f(last['sma5']); atr = _f(last['atr14'])
        today_dt = d.index[-1]

        pos = book.get(sym)
        exited = False
        exit_info = None

        # --- 1. fill PENDING at today's open (only if it signaled on a PRIOR bar) ---
        if pos and pos.get('status') == 'PENDING':
            entry_date_s = str(pos.get('entry_date', ''))
            last_bar_s = str(today_dt.date())
            if entry_date_s and entry_date_s < last_bar_s:
                entry_price = o
                atr_sig = _f(pos.get('atr')) or atr or 0.0
                stop = entry_price - STOP_ATR * atr_sig
                pos = {'status': 'OPEN',
                       'entry_date': last_bar_s,
                       'entry_price': _s(entry_price), 'stop_price': _s(stop),
                       'size_usd': pos.get('size_usd', ''), 'size_shares': _s(
                           float(pos.get('size_usd') or 0) / entry_price if entry_price > 0 else 0),
                       'atr': _s(atr_sig), 'ts': int(time.time())}
                # Persist the simulated next-open fill so the position advances to
                # OPEN and the round-trip journal (RHTRADE#) can later record the
                # exit + realized P&L. Was in-memory only -> the position stayed
                # PENDING forever, re-filled at every subsequent open, and RHTRADE#
                # never got written (the "signals but never fills" defect).
                put_item(table, f'RHPOS#{sym}', 'current', pos, args.dry_run)
            # else: signaled on the current bar (or a same-day re-run) -> keep
            # PENDING and fill on the next run (next trading open).

        # --- 2. manage OPEN: stop -> time -> revert (backtest priority order) ---
        if pos and pos.get('status') == 'OPEN':
            stop = _f(pos.get('stop_price')) or 0.0
            entry_price = _f(pos.get('entry_price')) or 0.0
            hold = 0
            try:
                entry_ts = pd.Timestamp(pos['entry_date'])
                hold = len(d) - 1 - d.index.get_loc(entry_ts)
            except Exception:
                hold = MAX_HOLD
            reason = None
            exit_price = None
            if stop > 0 and o < stop:                 # gap through stop
                reason, exit_price = 'stop', o
            elif stop > 0 and l <= stop:              # intraday stop
                reason, exit_price = 'stop', stop
            elif hold >= MAX_HOLD:                    # time stop
                reason, exit_price = 'time', c
            elif (ma5 is not None and c > ma5) or (r2 is not None and r2 > 70.0):
                reason, exit_price = 'revert', c
            if reason is not None:
                size_usd = float(pos.get('size_usd') or 0)
                shares = float(pos.get('size_shares') or 0)
                if shares <= 0 and entry_price > 0:
                    shares = size_usd / entry_price
                # LIVE: place a real exit (cancel stop + market close). Fail-closed:
                # on ANY failure leave the position OPEN for retry — never mark a
                # broker position closed on an unconfirmed exit. (Broker-side stop
                # fills are reconciled by the follow-on Robinhood reconciler.)
                if EXECUTION_MODE == 'LIVE' and client is not None and not live_client_error:
                    try:
                        fill = _live_exit_position(client, sym, shares)
                        exit_price = _f(fill.get('average_price')) or exit_price or c
                    except Exception as e:  # noqa: BLE001
                        print(f'[live] exit {sym} failed — position left OPEN for retry: {e!r}')
                        continue
                pnl = (exit_price - entry_price) * shares
                pnl_pct = (exit_price / entry_price - 1.0) if entry_price > 0 else 0.0
                if pnl < 0:
                    day_loss_used += -pnl
                exit_info = {'symbol': sym, 'exit_reason': reason,
                             'exit_price': _s(exit_price), 'entry_price': _s(entry_price),
                             'pnl_usd': _s(pnl), 'pnl_pct': _s(pnl_pct),
                             'hold_days': int(hold)}
                put_item(table, f'RHTRADE#{sym}', pos['entry_date'], {
                    'entry_date': pos['entry_date'], 'entry_price': _s(entry_price),
                    'exit_date': str(today_dt.date()), 'exit_price': _s(exit_price),
                    'exit_reason': reason, 'hold_days': int(hold),
                    'size_usd': pos.get('size_usd', ''), 'pnl_usd': _s(pnl),
                    'pnl_pct': _s(pnl_pct), 'ts': int(time.time())}, args.dry_run)
                put_item(table, f'RHPOS#{sym}', 'current', {
                    'status': 'CLOSED', 'entry_date': pos['entry_date'],
                    'entry_price': _s(entry_price), 'exit_date': str(today_dt.date()),
                    'exit_price': _s(exit_price), 'exit_reason': reason,
                    'pnl_usd': _s(pnl), 'pnl_pct': _s(pnl_pct), 'ts': int(time.time())},
                    args.dry_run)
                exits.append(exit_info)
                exited = True
                pos = None

        # --- 3. new entry (flat, no exit this bar, cap/limit not breached) ---
        if pos is None and not exited and r2 is not None and ma200 is not None:
            if sym.upper() in earnings_blacklist:
                put_item(table, f'RHSIG#{sym}', today, {
                    'action': 'NONE', 'signal': 'NONE', 'strategy': 'RSI2',
                    'rsi2': _s(r2), 'close': _s(c),
                    'reason': f'earnings guard: reports within {EARNINGS_GUARD_DAYS}d '
                              f'(no naked-gap entries)',
                    'mode': 'PAPER', 'execution': 'NONE', 'ts': int(time.time())},
                    args.dry_run)
                continue
            if r2 < RSI2_THR and c > ma200:
                if committed < pos_cap and day_loss_used < DAY_LOSS_CAP:
                    size_usd, stop_pct = position_size(PAPER_CAPITAL, c, atr or 0.0)
                    if size_usd > 0:
                        stop_price = c - STOP_ATR * (atr or 0.0)
                        # informational regime flag (NOT a gate — validated & rejected)
                        regime = 'RISK_ON' if c > ma200 else 'RISK_OFF'
                        reason = (f'RSI(2) {r2:.2f} < {RSI2_THR} AND close {c:.2f} > '
                                  f'SMA200 {ma200:.2f}')

                        # --- LIVE execution (gated; see docs/ROBINHOOD_EXECUTION.md) ---
                        if EXECUTION_MODE == 'LIVE':
                            reason_l = None
                            if live_client_error:
                                reason_l = f'LIVE disabled: {live_client_error}'
                            elif client is None:
                                reason_l = 'LIVE client unavailable'
                            else:
                                ok, greason = live_gate_ok(client, day_loss_used)
                                if not ok:
                                    reason_l = f'LIVE gate: {greason}'
                                else:
                                    shares = int(size_usd / c) if c > 0 else 0
                                    if shares < 1:
                                        reason_l = (f'LIVE skip: ${size_usd:.2f} < 1 whole '
                                                    f'share of {sym} (@${c:.2f})')
                                    else:
                                        try:
                                            fill = client.place_equity_entry(
                                                sym, 'buy', stop_price,
                                                quantity=str(shares),
                                                client_order_ref=f'rh_{today}_{sym}')
                                            ep = (_f((fill.get('entry') or {}).get('average_price'))
                                                  or c)
                                            sig = {'action': 'ENTER', 'side': 'LONG',
                                                   'strategy': 'RSI2', 'signal': 'LONG',
                                                   'entry': 'broker_fill',
                                                   'stop_price': _s(stop_price),
                                                   'size_usd': _s(size_usd),
                                                   'size_shares': _s(shares),
                                                   'rsi2': _s(r2), 'sma200': _s(ma200),
                                                   'sma5': _s(ma5 or 0), 'atr14': _s(atr or 0),
                                                   'stop_pct': _s(stop_pct),
                                                   'regime': regime, 'bear_warning': BEAR_WARNING,
                                                   'reason': reason, 'close': _s(c),
                                                   'mode': 'LIVE', 'execution': 'RH',
                                                   'venue': 'Robinhood Agentic — LIVE',
                                                   'order_id': (fill.get('entry') or {}).get('id', ''),
                                                   'stop_order_id': (fill.get('stop') or {}).get('id', ''),
                                                   'ts': int(time.time())}
                                            put_item(table, f'RHSIG#{sym}', today, sig, args.dry_run)
                                            put_item(table, f'RHPOS#{sym}', 'current', {
                                                'status': 'OPEN', 'entry_date': str(today_dt.date()),
                                                'entry_price': _s(ep), 'stop_price': _s(stop_price),
                                                'size_usd': _s(size_usd), 'size_shares': _s(shares),
                                                'atr': _s(atr or 0), 'ts': int(time.time())},
                                                args.dry_run)
                                            enters.append({'sym': sym, 'size_usd': _s(size_usd),
                                                           'stop_price': _s(stop_price)})
                                            committed += 1
                                        except Exception as e:  # fail-closed: never naked
                                            reason_l = f'LIVE place failed (fail-closed): {e!r}'
                            if reason_l is not None:
                                put_item(table, f'RHSIG#{sym}', today, {
                                    'action': 'NONE', 'signal': 'NONE', 'strategy': 'RSI2',
                                    'rsi2': _s(r2), 'close': _s(c), 'reason': reason_l,
                                    'mode': 'LIVE', 'execution': 'RH', 'ts': int(time.time())},
                                    args.dry_run)
                        else:
                            # --- PAPER (default): signal + simulated next-open fill ---
                            sig = {'action': 'ENTER', 'side': 'LONG', 'strategy': 'RSI2',
                                   'signal': 'LONG', 'entry': 'next_open',
                                   'stop_price': _s(stop_price), 'size_usd': _s(size_usd),
                                   'size_shares': _s(size_usd / c if c > 0 else 0),
                                   'rsi2': _s(r2), 'sma200': _s(ma200), 'sma5': _s(ma5 or 0),
                                   'atr14': _s(atr or 0), 'stop_pct': _s(stop_pct),
                                   'regime': regime, 'bear_warning': BEAR_WARNING,
                                   'reason': reason, 'close': _s(c),
                                   'mode': 'PAPER', 'execution': 'NONE',
                                   'venue': 'Robinhood (laptop) — paper', 'ts': int(time.time())}
                            put_item(table, f'RHSIG#{sym}', today, sig, args.dry_run)
                            put_item(table, f'RHPOS#{sym}', 'current', {
                                'status': 'PENDING', 'entry_date': str(today_dt.date()),
                                'size_usd': _s(size_usd), 'atr': _s(atr or 0),
                                'stop_ref': _s(stop_price), 'ts': int(time.time())},
                                args.dry_run)
                            enters.append({'sym': sym, 'size_usd': _s(size_usd),
                                           'stop_price': _s(stop_price)})
                            committed += 1
                else:
                    reason = ('cap/limit: ' + (
                        f'day loss {day_loss_used:.0f} >= {DAY_LOSS_CAP:.0f}' if day_loss_used >= DAY_LOSS_CAP
                        else f'{committed} >= {pos_cap} positions'))
                    put_item(table, f'RHSIG#{sym}', today, {
                        'action': 'NONE', 'signal': 'NONE', 'strategy': 'RSI2',
                        'rsi2': _s(r2), 'close': _s(c), 'reason': reason,
                        'mode': 'PAPER', 'execution': 'NONE', 'ts': int(time.time())},
                        args.dry_run)

    if day_loss_used >= DAY_LOSS_CAP:
        cap_breached = True

    # --- daily ledger (realized P&L = today's wins + losses) ---
    realized = sum(float(e['pnl_usd'] or 0) for e in exits)
    ledger = {'realized_pnl_usd': _s(realized),
              'day_loss_used_usd': _s(day_loss_used), 'cap_usd': _s(DAY_LOSS_CAP),
              'cap_breached': 'true' if cap_breached else 'false',
              'n_enter': len(enters), 'n_exit': len(exits), 'ts': int(time.time())}
    put_item(table, f'RHLEDGER#{today}', 'summary', ledger, args.dry_run)
    put_item(table, 'RUN#live_equities', today, {'ts': int(time.time())}, args.dry_run)
    flush_writes(table)

    # --- S3 snapshot (forward-test history) ---
    payload['signals'] = enters + exits
    payload['ledger'] = ledger
    if not args.dry_run:
        try:
            archive_scan_results('rh-equities', payload)
        except Exception as e:
            print(f'  snapshot archive failed: {e!r}')

    print(f'\nlive_equities done [{today}]: {len(enters)} ENTER, {len(exits)} EXIT, '
          f'day_loss_used=${day_loss_used:.2f} (cap ${DAY_LOSS_CAP:.0f}) '
          f'{"BREACHED" if cap_breached else "ok"}, committed={committed}/{pos_cap}')
    for e in enters:
        print(f'  ENTER {e["sym"]:6s} size=${e["size_usd"]} stop={e["stop_price"]}')
    for x in exits:
        print(f'  EXIT  {x["symbol"]:6s} {x["exit_reason"]:6s} pnl=${x["pnl_usd"]}')


if __name__ == '__main__':
    main()
