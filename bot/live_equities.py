#!/usr/bin/env python3
"""Robinhood equities RSI(2) buy-the-dip — PAPER signal bot + simulated fills.

STRICTLY PAPER. execution='NONE'. No Robinhood credentials on this VPS, no IBKR,
no orders of any kind. This file EMITS actionable signals + maintains a simulated
paper book; the LAPTOP reads the signals and places the real Robinhood orders via
its own MCP.

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
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
# SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback.
import os as _so, sys as _ss  # noqa: E402
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb  # noqa: E402
_sb()

from data.s3_archive import archive_scan_results  # noqa: E402

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

# ---- strategy parameters (paper capital is a SIMULATION input, not real money) ----
PAPER_CAPITAL = float(os.getenv('RH_PAPER_CAPITAL', '700'))
RISK_PCT = float(os.getenv('RH_RISK_PCT', '0.01'))        # 1%/trade
MAX_POS_PCT = float(os.getenv('RH_MAX_POS_PCT', '0.05'))  # 5% capital/name cap
DAY_LOSS_CAP = float(os.getenv('RH_DAY_LOSS_CAP', '150')) # $/day realized-loss cap
RSI2_THR = 5.0
STOP_ATR = 2.0
MAX_HOLD = 5
MAX_POSITIONS = 20
MIN_BARS = 260                       # >= 1y so SMA200 is fully warmed
DATA_START = '2022-01-01'            # fixed anchor -> stable index positions

# ---- universe (deterministic liquidity rule, NOT return cherry-picking) ----
# ETFs: the 10 validated names (XLE/XLB/XLU/XLRE excluded — KILL in the sweep).
ETFS = ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'XLF', 'XLK', 'XLV', 'XLP', 'XLI']
# Stocks: top-50 S&P100 by 20d avg dollar volume (recomputed 2026-08-16; GOOG
# dual-class dropped, GOOGL kept). Refresh monthly per the plan's liquidity rule.
STOCKS = ['MU', 'NVDA', 'MSFT', 'AAPL', 'AMD', 'TSLA', 'AMZN', 'INTC', 'GOOGL',
          'META', 'AVGO', 'PLTR', 'ORCL', 'AMAT', 'LRCX', 'LLY', 'NOW', 'NFLX',
          'CSCO', 'GEV', 'CAT', 'V', 'WMT', 'JPM', 'CRM', 'XOM', 'TXN', 'GS',
          'JNJ', 'QCOM', 'IBM', 'UNH', 'BAC', 'COST', 'MA', 'T', 'CVX', 'UBER',
          'KO', 'BA', 'ABBV', 'ISRG', 'C', 'ADBE', 'TMO', 'DHR', 'HD', 'MCD',
          'PG', 'BKNG']
UNIVERSE = ETFS + STOCKS
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


def position_size(capital, close, atr):
    """$ per name = min(1%/stop_pct, 5% cap). Returns (size_usd, stop_dist_pct)."""
    stop_dist = STOP_ATR * atr
    stop_pct = stop_dist / close if close > 0 else 1.0
    size_risk = (RISK_PCT * capital) / stop_pct if stop_pct > 0 else 0.0
    size_cap = MAX_POS_PCT * capital
    return min(size_risk, size_cap), stop_pct


def load_book(table, dry_run):
    """Current paper positions: {sym: item} for status in (PENDING, OPEN)."""
    if dry_run:
        return {}
    book = {}
    try:
        resp = table.scan(FilterExpression='begins_with(pk, :p)',
                          ExpressionAttributeValues={':p': 'RHPOS#'})
        for it in resp.get('Items', []):
            if it.get('sk') == 'current' and it.get('status') in ('PENDING', 'OPEN'):
                book[it['pk'].split('#', 1)[1]] = it
    except Exception as e:
        print(f'  [book] scan failed (fail-open, empty book): {e!r}')
    return book


def put_item(table, pk, sk, fields, dry_run):
    if dry_run:
        print(f'  [dry] {pk} / {sk} : ' + ', '.join(f'{k}={v}' for k, v in fields.items()))
        return
    try:
        table.put_item(Item={'pk': pk, 'sk': sk, **fields})
    except Exception as e:
        print(f'  [put] {pk}/{sk} failed: {e!r}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=0, help='cap symbols for a smoke test')
    args = ap.parse_args()

    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()

    # once-per-day dedupe (fail-open on read error, like equity_signals)
    if not args.dry_run:
        try:
            if table.get_item(Key={'pk': 'RUN#live_equities', 'sk': today}).get('Item'):
                print(f'[{today}] live_equities already ran today — skip')
                return
        except Exception as e:
            print(f'[{today}] dedupe read failed (fail-open): {e!r}')

    syms = UNIVERSE[:args.limit] if args.limit else UNIVERSE
    print(f'fetching {len(syms)} symbols (start={DATA_START})…')
    bars = fetch(syms)
    print(f'  got {len(bars)}/{len(syms)} symbols')

    book = load_book(table, args.dry_run)
    open_count = sum(1 for p in book.values() if p.get('status') == 'OPEN')
    committed = len(book)  # PENDING + OPEN

    day_loss_used = 0.0
    cap_breached = False
    enters, exits = [], []
    payload = {'lane': 'robinhood-equities', 'date': today, 'paper_capital': PAPER_CAPITAL,
               'signals': []}

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

        # --- 1. fill PENDING at today's open ---
        if pos and pos.get('status') == 'PENDING':
            entry_price = o
            atr_sig = _f(pos.get('atr')) or atr or 0.0
            stop = entry_price - STOP_ATR * atr_sig
            pos = {'symbol': sym, 'status': 'OPEN',
                   'entry_date': str(today_dt.date()),
                   'entry_price': _s(entry_price), 'stop_price': _s(stop),
                   'size_usd': pos.get('size_usd', ''), 'size_shares': _s(
                       float(pos.get('size_usd') or 0) / entry_price if entry_price > 0 else 0),
                   'atr': _s(atr_sig), 'ts': int(time.time())}

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
            if r2 < RSI2_THR and c > ma200:
                if committed < MAX_POSITIONS and day_loss_used < DAY_LOSS_CAP:
                    size_usd, stop_pct = position_size(PAPER_CAPITAL, c, atr or 0.0)
                    if size_usd > 0:
                        stop_price = c - STOP_ATR * (atr or 0.0)
                        # informational regime flag (NOT a gate — validated & rejected)
                        regime = 'RISK_ON' if c > ma200 else 'RISK_OFF'
                        reason = (f'RSI(2) {r2:.2f} < {RSI2_THR} AND close {c:.2f} > '
                                  f'SMA200 {ma200:.2f}')
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
                        else f'{committed} >= {MAX_POSITIONS} positions'))
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
          f'{"BREACHED" if cap_breached else "ok"}, committed={committed}/{MAX_POSITIONS}')
    for e in enters:
        print(f'  ENTER {e["sym"]:6s} size=${e["size_usd"]} stop={e["stop_price"]}')
    for x in exits:
        print(f'  EXIT  {x["symbol"]:6s} {x["exit_reason"]:6s} pnl=${x["pnl_usd"]}')


if __name__ == '__main__':
    main()
