"""Live trading bot — TWO long-only strategies, MES + MNQ (paper forward-test).

Strategies (each tracked INDEPENDENTLY, tagged in DynamoDB pk):

  1) DONCHIAN — Donchian/ATR breakout (exact port of bot/futures_scan.py
     `sig_donchian` long-only — the validated trend edge: full-period PF
     2.23/1.80, walk-forward OOS PF 2.08/2.14 on ES/NQ):
       Entry : close > prior 20-day high   (h.rolling(20).max().shift(1))
       Stop  : CHANDELIER trail — 3*ATR below the highest close since entry
               (initial = entry - 3*ATR), ratcheted up only (tighten-only).
       Exits : 5-day time stop -> close <= stop -> close < prior 20-day low.

  2) RSI2 — RSI(2) buy-the-dip (Connors ORIGINAL + 200d-SMA trend filter;
     refined 2026-08-16 — see research/rsi2_sma200_compare.py):
       Entry : RSI(2) < 10  AND  close > 200-day SMA   (Connors' trend gate:
               only buy dips in an uptrend, not falling knives. Backtest
               showed comparable OOS PF + lower relative maxDD + no COVID
               knife-catch vs the no-filter rule.)
       Exit  : RSI(2) > 70, or 5-day time stop, or 2*ATR hard stop (FIXED —
               trailing NOT applied: backtest showed trailing cuts
               mean-reversion winners; never-lose-money: no unprotected
               position, ever).

Data: yfinance ES=F / NQ=F daily (same % action as MES/MNQ).
Execution: IBKR paper (DUR193467) MES + MNQ, front-month, dynamic roll.
Logging: DynamoDB pk tagged per strategy —
  SIGNAL#<sym>_<STRAT> / TRADE#<sym>_<STRAT> / POSITION#<sym>_<STRAT>
  (e.g. SIGNAL#MES_DONCHIAN, SIGNAL#MES_RSI2). A 'strategy' attribute is also
  written on each item. Paper only — LIVE env var stays false.
Run daily via cron 19:00 ET.
"""
import os
import sys
import time
import datetime as dt

import yfinance as yf
import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv
from ib_insync import IB, Future

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.s3_archive import archive_daily_bar

from risk import RiskEngine, RiskConfig, realized_pnl, realized_vol_daily
from hardening.risk_ledger import RiskLedger, RiskStateUnavailable
from hardening.reconciler import reconcile
from hardening.exec_manager import ExecutionManager, TradeIntent
from control import (get_control, control_state, control_allows_entry, wants_flatten,
                     clear_flatten, ack_flatten, flatten_ibkr, already_ran_today,
                     mark_ran_today, data_finalized, ControlUnavailable, account_mode_ok)

load_dotenv()
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

# ===== config =====
IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
RISK_BUDGET = float(os.getenv('RISK_BUDGET', '50000'))
LIVE = os.getenv('LIVE', 'false').lower() == 'true'   # flip to true for real money

LOOKBACK = 20
STOP_ATR = 2.0
BREAKEVEN_ATR = 1.0   # RSI2 breakeven-lock: raise stop to entry once +1*ATR in profit
TAKE_PROFIT_PCT = 0.005  # RSI2PT A/B variant: broker-side limit exit at +0.5%
MAX_HOLD = 5
RSI2_LO = 10.0    # RSI(2) buy-the-dip entry
RSI2_HI = 70.0    # RSI(2) exit
RSI2_TREND_SMA = 200   # Connors trend filter: entry requires close > 200d SMA

# ---- 2-day short-term reversal (validated short-horizon edge, 2026-08-19;
#      research/short_horizon_edges_study.py + short_horizon_deepdive.py) ----
REV2_LOOKBACK = 2        # N-day reversal lookback
REV2_THRESH_ATR = 1.0    # entry: N-day return < -1xATR (as % of price)
REV2_MAX_HOLD = 3        # time stop (validated: avg hold 3.4d)

# ---- trailing-stop params (validated: Donchian chandelier ONLY) ----
CHAND_ATR = 3.0              # Donchian chandelier: 3*ATR below highest close

# data ticker -> execution contract. MES/MNQ are 1/10 size; % returns identical.
CONTRACTS = [
    {'data': 'ES=F', 'symbol': 'MES', 'point_value': 5.0},
    {'data': 'NQ=F', 'symbol': 'MNQ', 'point_value': 2.0},
]


# ===== indicators =====
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def compute(df):
    """Last bar's indicator values. don_hi/don_lo are PRIOR 20-day extremes
    (shift(1) — today excluded), matching futures_scan.py exactly."""
    h, l, c = df['High'], df['Low'], df['Close']
    don_hi = h.rolling(LOOKBACK).max().shift(1)
    don_lo = l.rolling(LOOKBACK).min().shift(1)
    atr = wilder_atr(h, l, c, 14)
    r2 = rsi(c, 2)
    sma200 = c.rolling(RSI2_TREND_SMA).mean()
    rev2 = c.pct_change(REV2_LOOKBACK)
    return pd.DataFrame({'close': c, 'don_hi': don_hi, 'don_lo': don_lo,
                         'atr': atr, 'rsi2': r2, 'sma200': sma200,
                         'rev2': rev2}).iloc[-1]


# ===== strategy interface: entry -> (bool, reason); exit -> (bool, reason);
#      stop(detail) -> protective stop price (hard stop, never-lose-money). =====
def donchian_entry(detail):
    if not np.isnan(detail['don_hi']) and detail['close'] > detail['don_hi']:
        return True, f"close {detail['close']:.1f} > 20d-high {detail['don_hi']:.1f}"
    return False, f"close {detail['close']:.1f} <= 20d-high {detail['don_hi']:.1f}"


def donchian_exit(detail, stop, held, entry_px=None):
    """Close-based exits, in backtest order: time stop -> ATR stop -> breakout."""
    if held >= MAX_HOLD:
        return True, f"time stop ({held}d >= {MAX_HOLD}d)"
    if stop is not None and detail['close'] <= stop:
        return True, f"close {detail['close']:.1f} <= stop {stop:.1f}"
    if not np.isnan(detail['don_lo']) and detail['close'] < detail['don_lo']:
        return True, f"close {detail['close']:.1f} < 20d-low {detail['don_lo']:.1f}"
    return False, "hold"


def donchian_stop(detail):
    # Chandelier initial width: 3*ATR below entry, then ratcheted up by
    # donchian_trail. (Validated variant — see research/trailing_stop_backtest.py.)
    return detail['close'] - CHAND_ATR * detail['atr']


def rsi2_entry(detail):
    if detail['rsi2'] < RSI2_LO:
        # Connors' ORIGINAL trend filter: only buy the dip when price is ABOVE
        # the 200-day SMA (dips in an uptrend mean-revert; dips below the SMA
        # are falling knives in a downtrend). Fail-closed on missing history.
        sma = detail['sma200']
        if not np.isfinite(sma):
            return False, (f"RSI(2) {detail['rsi2']:.1f} < {RSI2_LO} but no "
                           f"200d SMA yet (insufficient history)")
        if detail['close'] <= sma:
            return False, (f"RSI(2) {detail['rsi2']:.1f} < {RSI2_LO} but close "
                           f"{detail['close']:.1f} <= 200d SMA {sma:.1f}")
        return True, (f"RSI(2) {detail['rsi2']:.1f} < {RSI2_LO} and close "
                      f"{detail['close']:.1f} > 200d SMA {sma:.1f}")
    return False, f"RSI(2) {detail['rsi2']:.1f} >= {RSI2_LO}"


def rsi2_exit(detail, stop, held, entry_px=None):
    if held >= MAX_HOLD:
        return True, f"time stop ({held}d >= {MAX_HOLD}d)"
    if detail['rsi2'] > RSI2_HI:
        return True, f"RSI(2) {detail['rsi2']:.1f} > {RSI2_HI}"
    return False, "hold"


def rsi2_stop(detail):
    # NEVER-LOSE-MONEY: rest the 2*ATR distance as a hard protective stop
    # (previously 'sizing only, no order' — now the same number IS the stop).
    return detail['close'] - STOP_ATR * detail['atr']


def rsi2_trail(detail, state):
    """Breakeven-lock (NOT a trailing stop): once the dip-buy is +1*ATR in profit,
    raise the protective stop to breakeven (entry). Ratchet-up only. The validated
    RSI2 exit remains RSI(2)>70 / time stop — this only locks the downside.
    (Validated — research/adaptive_stop_study.py: breakeven beats fixed on RSI2:
    ES PF 1.63->1.72 + maxDD -33k->-25k; NQ PF 1.45->1.54.)"""
    if not np.isfinite(detail['atr']):
        return None, None, "no ATR"
    entry_px = float(state.get('entry', 0.0) or 0.0)
    if entry_px <= 0:
        return None, None, "no entry"
    profit_atr = (float(detail['close']) - entry_px) / float(detail['atr'])
    if profit_atr >= BREAKEVEN_ATR:
        return entry_px, None, (f"breakeven-lock: +{profit_atr:.1f} ATR "
                                f"-> stop=entry {entry_px:.1f}")
    return None, None, f"below breakeven (+{profit_atr:.1f} ATR < {BREAKEVEN_ATR})"


# ===== 2-day short-term reversal (validated short-horizon edge) =====
def rev2_entry(detail):
    """Buy a 2-day drop larger than 1xATR (short-term reversal / mean reversion).

    Validated 2026-08-19 (research/short_horizon_edges_study.py +
    short_horizon_deepdive.py): ES PF 1.54 / NQ 1.62 / YM 1.26 @1t, OOS 1.19-1.70,
    win 71-76%, hold 3.4d, survives 3-tick, independent of RSI2 (corr +0.07-0.14).
    Connors 200d-SMA trend filter (SAME as RSI2) added 2026-08-19 — backtest
    (research/rev2_sma_compare.py) showed it halves maxDD (ES -29k->-14k,
    NQ -44k->-26k) and lifts PF (ES 1.54->2.07, NQ 1.61->2.04) by skipping
    falling-knife dips below the 200d MA."""
    rv = detail['rev2']
    if not np.isfinite(rv) or not np.isfinite(detail['atr']) or detail['atr'] <= 0:
        return False, "no reversal data"
    sma = detail['sma200']
    if not np.isfinite(sma):
        return False, "no 200d SMA yet (insufficient history)"
    if detail['close'] <= sma:
        return False, (f"2d return {rv:.2%} < -1xATR but close "
                       f"{detail['close']:.1f} <= 200d SMA {sma:.1f} (falling knife)")
    k = REV2_THRESH_ATR * detail['atr'] / detail['close']
    if rv < -k:
        return True, (f"2d return {rv:.2%} < -{REV2_THRESH_ATR:.0f}xATR "
                      f"({-k:.2%}) and close {detail['close']:.1f} > 200d SMA {sma:.1f}")
    return False, f"2d return {rv:.2%} >= -{REV2_THRESH_ATR:.0f}xATR ({-k:.2%})"


def rev2_exit(detail, stop, held, entry_px=None):
    """Revert-to-entry + 3-day time stop (the validated reversal exit)."""
    if held >= REV2_MAX_HOLD:
        return True, f"time stop ({held}d >= {REV2_MAX_HOLD}d)"
    if entry_px is not None and detail['close'] > entry_px:
        return True, f"revert: close {detail['close']:.1f} > entry {entry_px:.1f}"
    return False, "hold"


# ===== trailing-stop function (Donchian chandelier; tighten-only) =====
def donchian_trail(detail, state):
    """Chandelier: candidate = (highest close since entry) - 3*ATR, ratchet-up.

    `peak` is tracked in state (restart-safe) and advanced with today's close;
    the raised stop rests from tomorrow. Returns (new_stop_or_None, new_peak,
    reason). new_stop is None when the candidate does not exceed the current
    stop; new_peak always advances so a later ATR fall still sees the true high.
    """
    if not np.isfinite(detail['atr']):
        return None, None, "no ATR"
    entry_px = float(state.get('entry', 0.0) or 0.0)
    peak = float(state.get('peak', 0.0) or 0.0)
    if peak <= 0:
        peak = entry_px                        # legacy position (pre-tagging)
    new_peak = max(peak, float(detail['close']))
    candidate = new_peak - CHAND_ATR * float(detail['atr'])
    return candidate, new_peak, (f"chandelier peak {new_peak:.1f} - 3*ATR"
                                 f"({detail['atr']:.1f}) = {candidate:.1f}")


# HORIZON-SPLIT STOPS (owner directive 2026-08-16): live.py is the SWING lane
# (2-3 day) — it uses CLOSE-BASED signal/trailing exits (avoid intra-bar noise
# fills) and keeps a WIDE ~3xATR hard stop (chandelier) as CATASTROPHIC
# protection only. Intraday lanes (live_intraday.py) keep intraday 2xATR stops
# + EOD flatten. `horizon`/`exit_mode` are declarative metadata for reviewers.
STRATEGIES = [
    {'name': 'DONCHIAN', 'label': 'Donchian/ATR long (chandelier trail)',
     'entry': donchian_entry, 'exit': donchian_exit, 'stop': donchian_stop,
     'trail': donchian_trail, 'horizon': 'swing', 'exit_mode': 'close',
     'stop_width': '3xATR chandelier (catastrophic)'},
    {'name': 'RSI2', 'label': 'RSI(2) buy-dip long (>200d SMA, 2*ATR + breakeven-lock)',
     'entry': rsi2_entry, 'exit': rsi2_exit, 'stop': rsi2_stop,
     'trail': rsi2_trail, 'horizon': 'swing', 'exit_mode': 'close',
     'stop_width': '2xATR fixed + breakeven-lock @ +1ATR'},
    {'name': 'RSI2PT', 'label': 'RSI(2) buy-dip long + 0.5% take-profit (A/B vs RSI2)',
     'entry': rsi2_entry, 'exit': rsi2_exit, 'stop': rsi2_stop,
     'horizon': 'swing', 'exit_mode': 'target',
     'stop_width': '2xATR fixed + 0.5% broker-side take-profit',
     'take_profit_pct': TAKE_PROFIT_PCT},
    {'name': 'REV2', 'label': '2-day reversal long (2d drop >1xATR, >200d SMA, revert/3d exit)',
     'entry': rev2_entry, 'exit': rev2_exit, 'stop': rsi2_stop,
     'horizon': 'swing', 'exit_mode': 'close',
     'stop_width': '2xATR fixed'},
]


# ===== contract =====
def front_month(now=None):
    """Front-month contract (YYYYMM), quarterly Mar/Jun/Sep/Dec. MES & MNQ share it."""
    now = now or dt.date.today()
    for m in (3, 6, 9, 12):
        if now.month <= m:
            return f"{now.year}{m:02d}"
    return f"{now.year + 1}03"


def held_days(df, entry_date):
    """Number of trading bars strictly after entry date."""
    if not entry_date:
        return 0
    e = pd.Timestamp(entry_date)
    idx = df.index
    if getattr(idx, 'tz', None) is not None:
        e = e.tz_localize(idx.tz)
    return int((idx > e).sum())


# ===== DynamoDB helpers =====
def log_dynamo(table, pk, sk, data):
    table.put_item(Item={'pk': pk, 'sk': sk, **data})


def get_state(table, pk, sk):
    r = table.get_item(Key={'pk': pk, 'sk': sk})
    return r.get('Item')


def _last_fill_price(ib, symbol, side, qty=None):
    """Price of the most recent broker fill for `symbol`+`side` (or None).

    Used to attribute an intraday position-close to the ACTUAL fill (a
    take-profit limit fills at the target, a stop fills at the stop price) —
    without this the bot would mis-record a target fill as a stop fill and
    understate the A/B P&L. Reads ib.fills() (Fill has .contract + .execution).
    """
    try:
        fills = ib.fills()
    except Exception:
        return None
    best, best_t = None, None
    for f in fills:
        ex = getattr(f, 'execution', None)
        if ex is None or ex.side != side:
            continue
        sym = getattr(getattr(f, 'contract', None), 'symbol', None)
        if sym != symbol:
            continue
        if qty is not None and getattr(ex, 'shares', None) != qty:
            continue
        t = getattr(ex, 'time', None)
        if t is None or (best_t is not None and t <= best_t):
            continue
        best_t = t
        px = getattr(ex, 'price', None) or getattr(ex, 'avgPrice', None)
        if px is not None:
            best = float(px)
    return best


def _archive_daily_bar(c, df):
    """Archive the latest daily bar under the DATA ticker (ES/NQ for MES/MNQ)."""
    if df is None or df.empty:
        return
    try:
        data_sym = c['data'].replace('=F', '')      # ES=F -> ES, NQ=F -> NQ
        last = df.iloc[-1]
        bar = {
            'date': df.index[-1].strftime('%Y-%m-%d'),
            'symbol': data_sym,
            'open': float(last['Open']), 'high': float(last['High']),
            'low': float(last['Low']), 'close': float(last['Close']),
            'volume': float(last['Volume']) if 'Volume' in df.columns else None,
        }
        archive_daily_bar(data_sym, bar)
    except Exception as e:
        print(f"[{c['symbol']}] daily bar archive failed: {e}")


# ===== per-strategy signal evaluation (pure, NO IBKR) =====
def evaluate_signal(dynamo, df, detail, sym, strat, today):
    """Compute + log the signal for one strategy on finalized data.

    Pure pandas (no IBKR) so it can run BEFORE the gateway connect — logging
    SIGNAL# here guarantees every EOD cycle leaves an auditable signal record
    even when IBKR is down, which makes a missed signal DETECTABLE rather than
    silently lost (the 08-18 failure class)."""
    sname = strat['name']
    tag = f"{sym}_{sname}"
    state = get_state(dynamo, f"POSITION#{tag}", 'current') or {}
    pos = int(state.get('pos', 0))
    entry_date = state.get('entry_date')
    held = held_days(df, entry_date)
    entry, ereason = strat['entry'](detail)
    sig = {
        'signal': 'LONG' if entry else ('EXIT' if pos > 0 else 'NONE'),
        'strategy': sname,
        'close': str(round(detail['close'], 2)),
        'pos': pos, 'held_days': held, 'reason': ereason, 'ts': int(time.time()),
    }
    if sname == 'DONCHIAN':
        sig.update({
            'don_hi': str(round(detail['don_hi'], 2)) if not np.isnan(detail['don_hi']) else '',
            'don_lo': str(round(detail['don_lo'], 2)) if not np.isnan(detail['don_lo']) else '',
            'atr': str(round(detail['atr'], 2)),
        })
    elif sname == 'REV2':
        sig['rev2'] = str(round(detail['rev2'], 4))
        sig['atr'] = str(round(detail['atr'], 2))
    else:
        sig['rsi2'] = str(round(detail['rsi2'], 2))
        sig['sma200'] = str(round(detail['sma200'], 2))
    log_dynamo(dynamo, f"SIGNAL#{tag}", today, sig)
    return entry, ereason, pos, held


# ===== per-strategy runner =====
def run_strategy(ib, dynamo, con, sym, df, detail, c, strat, today, mode, ctrl=None,
                 risk=None, exec_mgr=None):
    sname = strat['name']
    tag = f"{sym}_{sname}"                       # e.g. MES_DONCHIAN, MES_RSI2
    state = get_state(dynamo, f"POSITION#{tag}", 'current') or {}
    stop = float(state['stop']) if state.get('stop') else None
    entry_px = float(state['entry']) if state.get('entry') else None
    entry, ereason, pos, held = evaluate_signal(dynamo, df, detail, sym, strat, today)

    if pos > 0:
        should_exit, xreason = strat['exit'](detail, stop, held, entry_px)
        if should_exit:
            # Cancel the resting GTC stop BEFORE the market close (race-free),
            # then close via the execution manager (idempotent + fill-verified).
            exit_intent = TradeIntent(scope='live', tag=tag, symbol=sym, action='SELL',
                                      side='LONG', qty=pos, order_type='MKT', stop_price=0.0,
                                      contract_month=front_month(), bar_time=today,
                                      signal_reason=xreason)
            res = exec_mgr.submit_exit(exit_intent, con, cancel_stop=True)
            if res.status == 'DUPLICATE':
                print(f">>> {mode} {tag} duplicate exit signal — skip (idempotent)")
                return
            if res.status == 'UNKNOWN':
                print(f">>> {mode} {tag} EXIT UNKNOWN (timeout) — not recording close; "
                      f"reconcile will resolve")
                return
            exit_px = res.avg_px if res.avg_px > 0 else detail['close']
            if risk is not None and entry_px is not None:
                risk.record_close(realized_pnl('LONG', entry_px, exit_px, c['point_value'], pos))
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'EXIT', 'qty': pos, 'reason': xreason, 'strategy': sname,
                'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': 0, 'stop': '0', 'entry': '0', 'entry_date': '', 'ts': int(time.time())})
            print(f">>> {mode} {tag} EXIT {pos} ({xreason})")
        elif not exec_mgr.is_stop_open(sym, 'LONG', ref=tag):
            # position closed intraday (protective stop OR take-profit target
            # filled). Read the ACTUAL closing fill price so a target fill is
            # recorded at the target, not mis-attributed to the stop.
            exit_px = _last_fill_price(ib, sym, 'SELL', qty=pos)
            if exit_px is None:
                exit_px = stop if stop is not None else detail['close']
            if risk is not None and entry_px is not None:
                risk.record_close(realized_pnl('LONG', entry_px, exit_px, c['point_value'], pos))
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'EXIT', 'qty': pos, 'reason': 'target/stop-filled (intraday)',
                'strategy': sname, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': 0, 'stop': '0', 'entry': '0', 'entry_date': '', 'ts': int(time.time())})
            print(f">>> {mode} {tag} EXIT via protective stop/target (intraday fill)")
        else:
            # HOLD — ratchet the trailing stop (chandelier) for tomorrow.
            if 'trail' in strat:
                new_stop, new_peak, treason = strat['trail'](detail, state)
                changed = False
                if new_peak is not None:
                    old_peak = float(state.get('peak', 0.0) or 0.0)
                    if new_peak > old_peak + 1e-9:
                        state['peak'] = str(round(new_peak, 2))
                        changed = True
                if (new_stop is not None and stop is not None
                        and float(new_stop) > float(stop)):
                    res = exec_mgr.trail_stop(con, sym, 'LONG', pos, float(new_stop),
                                              ref=tag, tif='GTC')
                    if res.status == 'TRAILED':
                        state['stop'] = str(round(new_stop, 2))
                        stop = new_stop
                        changed = True
                        print(f">>> {mode} {tag} TRAIL stop -> {new_stop:.1f} ({treason})")
                if changed:
                    log_dynamo(dynamo, f"POSITION#{tag}", 'current',
                               {**state, 'ts': int(time.time())})
            print(f">>> {mode} {tag} hold pos={pos} held={held}d | "
                  f"close {detail['close']:.1f} {strat['label']}")
    elif entry:
        if not control_allows_entry(ctrl or {}):
            print(f">>> {mode} {tag} no entry — control state {control_state(ctrl or {})}")
            return
        if risk is None:
            risk = RiskEngine(RiskConfig(risk_budget_usd=RISK_BUDGET))
        allowed, why = risk.can_enter()
        if not allowed:
            print(f">>> {mode} {tag} blocked by risk: {why}")
            return
        stop_price = strat['stop'](detail)
        vol = realized_vol_daily(df['Close'], 20)
        size = risk.position_size(detail['close'] - stop_price,
                                  point_value=c['point_value'],
                                  realized_vol=vol, price=detail['close'])
        if size > 0:
            intent = TradeIntent(scope='live', tag=tag, symbol=sym, action='BUY',
                                 side='LONG', qty=size, order_type='MKT',
                                 stop_price=float(stop_price), contract_month=front_month(),
                                 bar_time=today, signal_reason=ereason)
            tp_pct = strat.get('take_profit_pct')
            tp_price = float(detail['close']) * (1 + tp_pct) if tp_pct else None
            res = exec_mgr.submit_entry(intent, con, take_profit=tp_price)
            if res.status == 'DUPLICATE':
                print(f">>> {mode} {tag} duplicate signal {res.signal_id} — skip (idempotent)")
                return
            if res.status == 'UNKNOWN':
                print(f">>> {mode} {tag} ENTRY UNKNOWN (timeout) — no state written; "
                      f"reconcile will resolve")
                return
            if res.filled_qty <= 0:
                print(f">>> {mode} {tag} ENTRY NOT FILLED (status={res.status}) — no state written")
                return
            if res.filled_qty < size:
                print(f">>> {mode} {tag} PARTIAL fill {res.filled_qty}/{size} — writing actual qty")
                size = res.filled_qty
            entry_px_filled = res.avg_px if res.avg_px > 0 else detail['close']
            risk.record_fill()
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'BUY', 'qty': size, 'entry': str(round(entry_px_filled, 2)),
                'stop': str(round(stop_price, 2)), 'contract': front_month(),
                'strategy': sname, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': size, 'stop': str(round(stop_price, 2)),
                'entry': str(round(entry_px_filled, 2)),
                'entry_date': today, 'peak': str(round(float(detail['close']), 2)),
                'stop_mode': 'chandelier' if 'trail' in strat else 'fixed',
                'contract': front_month(), 'ts': int(time.time())})
            print(f">>> {mode} {tag} ENTRY: BUY {size} @ {round(entry_px_filled, 2)}, "
                  f"stop {round(stop_price, 1)} ({ereason})")
        else:
            print(f">>> {mode} {tag} size=0 (stop too wide for budget), skip")
    else:
        print(f"[{today}] {mode} {tag} flat, no entry ({ereason})")


# ===== main =====
def main():
    dynamo = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()
    mode = 'LIVE' if LIVE else 'PAPER'

    # Data-freshness guard: daily signals need the FINALIZED close (>= 17:00 ET).
    if not data_finalized():
        print(f"[{today}] {mode} SKIP — before daily-close finalization (stale-data guard)")
        return

    # Dedupe guard: skip if this bot already ran today (double-schedule defence).
    if already_ran_today(dynamo, 'live', today):
        print(f"[{today}] {mode} already ran today (RUN#live) — skip (dedupe guard)")
        return
    # 1. data (fetch before IBKR so we can still log signals if connect fails)
    data = {}
    for c in CONTRACTS:
        df = yf.download(c['data'], period='2y', interval='1d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[c['symbol']] = df
        _archive_daily_bar(c, df)

    # 1b. evaluate + log every signal on FINALIZED data BEFORE mark_ran — a crash
    #     here leaves no RUN# marker, so a same-day retry re-evaluates instead of
    #     silently missing the signal (the 08-18 failure class). IBKR not needed.
    for c in CONTRACTS:
        df = data[c['symbol']]
        if df.empty or len(df) < LOOKBACK + 5:
            continue
        detail = compute(df)
        for strat in STRATEGIES:
            evaluate_signal(dynamo, df, detail, c['symbol'], strat, today)

    mark_ran_today(dynamo, 'live', today)

    # 2. connect IBKR
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=70, timeout=8)
    except Exception as e:
        print(f"[{today}] {mode} IBKR connect failed: {e}")
        return

    try:
        # 3. account guard — refuse orders on paper/live mismatch (fail-closed)
        ok, why = account_mode_ok(mode, ib.managedAccounts())
        if not ok:
            print(f"[{today}] {mode} HALT — {why}")
            return

        # 4. control plane — honour kill/pause/flatten BEFORE any order (fail-closed)
        try:
            ctrl = get_control(dynamo)
        except ControlUnavailable as e:
            print(f"[{today}] {mode} HALT — control state unavailable (fail-closed): {e}")
            return
        if control_state(ctrl) is None:
            print(f"[{today}] {mode} HALT — unknown control state (fail-closed)")
            return
        if wants_flatten(ctrl):
            all_tags = [f"{c['symbol']}_{s['name']}" for c in CONTRACTS for s in STRATEGIES]
            flatten_ibkr(ib, [c['symbol'] for c in CONTRACTS], dynamo, all_tags, today, mode)
            ack_flatten(dynamo, 'live')
            clear_flatten(dynamo)
        if control_state(ctrl) == 'KILLED':
            print(f"[{today}] {mode} KILLED — all trading halted (positions flattened)")
            return
        if control_state(ctrl) == 'PAUSED':
            print(f"[{today}] {mode} PAUSED — no new entries; managing exits only")

        # 5. persistent risk engine — ONE instance for the whole run so
        #    daily_pnl / daily_trades / consecutive_losses accumulate across
        #    strategies (not re-instantiated per symbol x strategy).
        #    Loaded from the ledger so a crash/re-run does NOT reset the
        #    daily-loss cap / consecutive-loss brake to zero. Fail-closed:
        #    an unreadable ledger HALTS the run (no new entries).
        risk_cfg = RiskConfig(risk_budget_usd=RISK_BUDGET,
                              max_concurrent_positions=len(CONTRACTS) * len(STRATEGIES),
                              max_trades_per_day=len(CONTRACTS) * len(STRATEGIES))
        try:
            risk = RiskEngine.load(risk_cfg, RiskLedger(dynamo, scope='live'))
        except RiskStateUnavailable as e:
            print(f"[{today}] {mode} HALT — risk state unreadable (fail-closed): {e}")
            return
        open_n = 0
        for c in CONTRACTS:
            for s in STRATEGIES:
                st = get_state(dynamo, f"POSITION#{c['symbol']}_{s['name']}", 'current') or {}
                if int(st.get('pos', 0)) > 0:
                    open_n += 1
        risk.set_open_positions(open_n)
        risk.touch_data()

        # 6. broker reconciliation — halt on any mismatch/unknown (fail-closed).
        #    Never assume success: a timeout is UNKNOWN, not a rejection.
        r = reconcile(ib, dynamo, today_iso=today)
        if not r.ok:
            print(f"[{today}] {mode} HALT — reconciliation {r.status}: {r.reason}")
            risk.emergency_halt(f"reconciliation {r.status}: {r.reason}")
            return

        # 7. execution manager — the ONLY component that submits orders to IBKR.
        exec_mgr = ExecutionManager(ib, dynamo, scope='live')

        for c in CONTRACTS:
            sym = c['symbol']
            df = data[sym]
            if df.empty or len(df) < LOOKBACK + 5:
                print(f"[{today}] {sym}: insufficient data ({len(df)} bars)")
                continue
            detail = compute(df)

            # 4. qualify contract (front-month, dynamic roll) — once per symbol
            try:
                con = ib.qualifyContracts(Future(sym, front_month(), 'CME'))[0]
            except Exception as e:
                print(f"[{today}] {sym}: contract qualify failed: {e}")
                continue

            for strat in STRATEGIES:
                run_strategy(ib, dynamo, con, sym, df, detail, c, strat, today, mode,
                             ctrl, risk, exec_mgr)
    finally:
        ib.disconnect()


if __name__ == '__main__':
    main()

