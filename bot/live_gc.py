"""Live gold (GC) momentum bot — paper EXECUTION (Donchian L/S + TSMOM L/S).

Promotes the gc_signals.py signal-only lane to paper execution (owner directive
2026-08-16): GC gold momentum is the single strongest, best-confirmed futures
edge (research/EDGE_SWEEP.md) — Donchian long/short (full PF 1.45, OOS 1.81,
IBKR 1.31, 3-tick 1.42) and TSMOM sign-of-12m-return (1.37 / 1.73 / 1.99 / 1.35).

Data: yfinance GC=F daily (same % action as the COMEX GC contract). GC COMEX L1
is DELAYED on paper (metals), so signals come from the daily bar; orders route
to the GC paper contract through the SAME execution path live.py uses:

    signal -> TradeIntent -> risk/admission -> ExecutionManager -> IBKR paper order
    + mandatory never-lose-money protective stop (chokepoint: submit_entry
    refuses stop_price <= 0; the reconciler verifies a stop rests on every open
    GC position).

Strategies (each tracked INDEPENDENTLY, tagged in DynamoDB pk):

  1) DONCHIAN — 20-day breakout, long AND short (bidirectional, per the sweep):
       Entry : close > prior 20d high -> LONG ; close < prior 20d low -> SHORT.
       Stop  : CHANDELIER trail — 3*ATR beyond the best close since entry,
               ratcheted in the profitable direction only (tighten-only):
               long  = highest-close - 3*ATR (ratchet up);
               short = lowest-close  + 3*ATR (ratchet down).
       Exits : 5-day time stop -> close crosses the stop -> reverse breakout
               (long: close < 20d low ; short: close > 20d high).

  2) TSMOM — sign of 12-month return (monthly rebalance in the backtest):
       Entry : ret_12m > 0 -> LONG ; ret_12m < 0 -> SHORT.
       Stop  : FIXED 3*ATR hard stop (never-lose-money floor; NOT trailed — the
               validated exit is the 12m sign flip, so the stop is a
               catastrophic floor, not a profit-lock).
       Exits : 12m return flips sign (or the stop is hit).

Execution: IBKR paper (DUR193467) GC, front-month (Feb/Apr/Jun/Aug/Oct/Dec).
Logging: DynamoDB pk tagged per strategy —
  SIGNAL#GC_DONCHIAN / SIGNAL#GC_TSMOM
  TRADE#GC_DONCHIAN / TRADE#GC_TSMOM
  POSITION#GC_DONCHIAN / POSITION#GC_TSMOM   (side stored — bidirectional)
Paper only — LIVE env var stays false. Run daily via cron ~19:00 ET (like live.py).

Sizing honesty: GC = 100 oz = $100/point. A 3*ATR chandelier stop on gold
(~$76 ATR) risks ~$23k per contract, so the paper sleeve (GC_RISK_BUDGET) is
sized ~$1.5M so 1 contract is ~1.5% of budget. This is a FORWARD-TEST sizing
config, NOT a live-capital commitment — a real-money GC sleeve must be that
large (or trade the MGC micro at $10/point).
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
from data.symbol_registry import front_month_for
from data.s3_archive import archive_scan_results

from risk import RiskEngine, RiskConfig, realized_pnl, realized_vol_daily
from hardening.risk_ledger import RiskLedger, RiskStateUnavailable
from hardening.reconciler import reconcile
from hardening.exec_manager import ExecutionManager, TradeIntent
from control import (get_control, control_state, control_allows_entry, wants_flatten,
                     clear_flatten, ack_flatten, flatten_ibkr, already_ran_today,
                     mark_ran_today, ControlUnavailable, account_mode_ok)

load_dotenv()

# ===== config =====
IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
LIVE = os.getenv('LIVE', 'false').lower() == 'true'

DATA_TICKER = 'GC=F'
SYMBOL = 'GC'
EXCHANGE = 'COMEX'
POINT_VALUE = 100.0            # full GC = 100 oz = $100/point
CLIENT_ID = 78                 # distinct: live(70) intraday(72) contracts(73) tick(74) daily(75) reconcile(76) options(77)
BOT_KEY = 'live_gc'

# Full GC (100 oz) at 3*ATR risks ~$23k/contract -> paper sleeve sized so
# 1 contract is ~1.5% of budget. FORWARD-TEST sizing, not a live commitment.
GC_RISK_BUDGET = float(os.getenv('GC_RISK_BUDGET', '1500000'))

LOOKBACK = 20
MAX_HOLD = 5
CHAND_ATR = float(os.getenv('GC_CHAND_ATR', '3.0'))            # Donchian chandelier width
TSMOM_STOP_ATR = float(os.getenv('GC_TSMOM_STOP_ATR', '3.0'))  # TSMOM fixed hard stop
TSMOM_LOOKBACK = 252
MIN_BARS = 260             # >= 1y so TSMOM's 12m return is computable


def _s(v):
    """Stringify a number for DynamoDB; NaN -> ''."""
    try:
        f = float(v)
        return '' if f != f else str(round(f, 4))
    except (TypeError, ValueError):
        return str(v)


# ===== indicators =====
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def compute(df):
    """Latest-bar indicators (dict). don_hi/don_lo are PRIOR 20-day extremes
    (shift(1) — today excluded), matching futures_scan.py / gc_signals.py."""
    h, l, c = df['High'], df['Low'], df['Close']
    don_hi = h.rolling(LOOKBACK).max().shift(1).iloc[-1]
    don_lo = l.rolling(LOOKBACK).min().shift(1).iloc[-1]
    atr = float(wilder_atr(h, l, c, 14).iloc[-1])
    ret_12m = float(c.iloc[-1] / c.iloc[-TSMOM_LOOKBACK] - 1.0)
    return {'close': float(c.iloc[-1]), 'don_hi': don_hi, 'don_lo': don_lo,
            'atr': atr, 'ret_12m': ret_12m}


# ===== strategy interface =====
# desired(detail)          -> (side_or_None, reason)     direction to be in
# stop(detail, side)       -> protective stop price
# exit(detail, side, stop, held, desired) -> (bool, reason)
# trail(detail, state, side) -> (new_stop_or_None, new_extreme_or_None, reason)  [optional]
def donchian_desired(detail):
    c, hi, lo = detail['close'], detail['don_hi'], detail['don_lo']
    if not np.isnan(hi) and c > hi:
        return 'LONG', f"close {c:.1f} > 20d-high {hi:.1f}"
    if not np.isnan(lo) and c < lo:
        return 'SHORT', f"close {c:.1f} < 20d-low {lo:.1f}"
    return None, f"close {c:.1f} within 20d range [{_s(lo)}, {_s(hi)}]"


def donchian_stop(detail, side):
    if side == 'LONG':
        return detail['close'] - CHAND_ATR * detail['atr']
    return detail['close'] + CHAND_ATR * detail['atr']


def donchian_exit(detail, side, stop, held, desired):
    c = detail['close']
    if held >= MAX_HOLD:
        return True, f"time stop ({held}d >= {MAX_HOLD}d)"
    if side == 'LONG':
        if stop is not None and c <= stop:
            return True, f"close {c:.1f} <= stop {stop:.1f}"
        if not np.isnan(detail['don_lo']) and c < detail['don_lo']:
            return True, f"close {c:.1f} < 20d-low {detail['don_lo']:.1f}"
    else:
        if stop is not None and c >= stop:
            return True, f"close {c:.1f} >= stop {stop:.1f}"
        if not np.isnan(detail['don_hi']) and c > detail['don_hi']:
            return True, f"close {c:.1f} > 20d-high {detail['don_hi']:.1f}"
    return False, "hold"


def donchian_trail(detail, state, side):
    """Chandelier: candidate = best-close-since-entry ± 3*ATR, ratchet only.

    For a long the best close is the peak (max) and the stop ratchets UP; for a
    short the best close is the trough (min) and the stop ratchets DOWN. `peak` /
    `trough` are tracked in state (restart-safe) and advanced with today's close.
    """
    if not np.isfinite(detail['atr']):
        return None, None, "no ATR"
    entry_px = float(state.get('entry', 0.0) or 0.0)
    atr = float(detail['atr'])
    if side == 'LONG':
        ext = float(state.get('peak', 0.0) or 0.0)
        if ext <= 0:
            ext = entry_px                      # legacy/pre-tagging position
        new_ext = max(ext, float(detail['close']))
        candidate = new_ext - CHAND_ATR * atr
        return candidate, new_ext, (f"chandelier peak {new_ext:.1f} - {CHAND_ATR:.0f}*ATR"
                                    f"({atr:.1f}) = {candidate:.1f}")
    ext = float(state.get('trough', 0.0) or 0.0)
    if ext <= 0:
        ext = entry_px
    new_ext = min(ext, float(detail['close']))
    candidate = new_ext + CHAND_ATR * atr
    return candidate, new_ext, (f"chandelier trough {new_ext:.1f} + {CHAND_ATR:.0f}*ATR"
                                f"({atr:.1f}) = {candidate:.1f}")


def tsmom_desired(detail):
    r = detail['ret_12m']
    if r > 0:
        return 'LONG', f"12m return {r:.2%} > 0"
    if r < 0:
        return 'SHORT', f"12m return {r:.2%} < 0"
    return None, f"12m return {r:.2%} flat"


def tsmom_stop(detail, side):
    if side == 'LONG':
        return detail['close'] - TSMOM_STOP_ATR * detail['atr']
    return detail['close'] + TSMOM_STOP_ATR * detail['atr']


def tsmom_exit(detail, side, stop, held, desired):
    c = detail['close']
    if desired is not None and desired != side:
        return True, f"12m signal flipped to {desired}"
    if side == 'LONG' and stop is not None and c <= stop:
        return True, f"close {c:.1f} <= stop {stop:.1f}"
    if side == 'SHORT' and stop is not None and c >= stop:
        return True, f"close {c:.1f} >= stop {stop:.1f}"
    return False, "hold"


STRATEGIES = [
    {'name': 'DONCHIAN', 'label': 'Donchian L/S breakout (chandelier 3*ATR trail)',
     'desired': donchian_desired, 'exit': donchian_exit, 'stop': donchian_stop,
     'trail': donchian_trail},
    {'name': 'TSMOM', 'label': '12m-return sign (fixed 3*ATR hard stop)',
     'desired': tsmom_desired, 'exit': tsmom_exit, 'stop': tsmom_stop},
]


# ===== helpers =====
def held_days(df, entry_date):
    """Number of trading bars strictly after entry date."""
    if not entry_date:
        return 0
    e = pd.Timestamp(entry_date)
    idx = df.index
    if getattr(idx, 'tz', None) is not None:
        e = e.tz_localize(idx.tz)
    return int((idx > e).sum())


def log_dynamo(table, pk, sk, data):
    table.put_item(Item={'pk': pk, 'sk': sk, **data})


def get_state(table, pk, sk):
    r = table.get_item(Key={'pk': pk, 'sk': sk})
    return r.get('Item')


# ===== per-strategy runner =====
def run_strategy(ib, dynamo, con, sym, df, detail, strat, today, mode, ctrl=None,
                 risk=None, exec_mgr=None):
    sname = strat['name']
    tag = f"{sym}_{sname}"
    state = get_state(dynamo, f"POSITION#{tag}", 'current') or {}
    pos = int(state.get('pos', 0))
    side = state.get('side') or None
    stop = float(state['stop']) if state.get('stop') else None
    entry_px = float(state['entry']) if state.get('entry') else None
    entry_date = state.get('entry_date')
    held = held_days(df, entry_date)

    desired, dreason = strat['desired'](detail)

    sig = {
        'signal': 'EXIT' if pos > 0 else (desired or 'NONE'),
        'strategy': sname,
        'close': _s(detail['close']),
        'side': (side or desired or ''),
        'pos': pos, 'held_days': held, 'reason': dreason, 'ts': int(time.time()),
        'promoted': True, 'candidate': False,
        'mode': f'{mode}-EXEC', 'execution': 'IBKR-PAPER', 'venue': 'futures (GC COMEX)',
    }
    if sname == 'DONCHIAN':
        sig.update({'don_hi': _s(detail['don_hi']), 'don_lo': _s(detail['don_lo']),
                    'atr': _s(detail['atr'])})
    else:
        sig['ret_12m'] = _s(detail['ret_12m'])
    log_dynamo(dynamo, f"SIGNAL#{tag}", today, sig)

    if pos > 0:
        should_exit, xreason = strat['exit'](detail, side, stop, held, desired)
        if should_exit:
            action = 'SELL' if side == 'LONG' else 'BUY'
            exit_intent = TradeIntent(scope=BOT_KEY, tag=tag, symbol=sym, action=action,
                                      side=side, qty=pos, order_type='MKT', stop_price=0.0,
                                      contract_month=front_month_for(sym), bar_time=today,
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
                risk.record_close(realized_pnl(side, entry_px, exit_px, POINT_VALUE, pos))
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'EXIT', 'qty': pos, 'reason': xreason, 'strategy': sname,
                'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': 0, 'side': '', 'stop': '0', 'entry': '0', 'entry_date': '',
                'ts': int(time.time())})
            print(f">>> {mode} {tag} EXIT {pos} ({xreason})")
        elif not exec_mgr.is_stop_open(sym, side, ref=tag):
            # state says open but the GTC stop is no longer resting -> filled intraday
            exit_px = stop if stop is not None else detail['close']
            if risk is not None and entry_px is not None:
                risk.record_close(realized_pnl(side, entry_px, exit_px, POINT_VALUE, pos))
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'EXIT', 'qty': pos, 'reason': 'stop-filled (intraday)',
                'strategy': sname, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': 0, 'side': '', 'stop': '0', 'entry': '0', 'entry_date': '',
                'ts': int(time.time())})
            print(f">>> {mode} {tag} EXIT via protective stop (intraday fill)")
        else:
            # HOLD — ratchet the chandelier trail (Donchian only; TSMOM is fixed).
            if 'trail' in strat:
                new_stop, new_ext, treason = strat['trail'](detail, state, side)
                changed = False
                ext_key = 'peak' if side == 'LONG' else 'trough'
                if new_ext is not None:
                    old_ext = float(state.get(ext_key, 0.0) or 0.0)
                    improved = (new_ext > old_ext + 1e-9) if side == 'LONG' \
                        else (old_ext <= 0 or new_ext < old_ext - 1e-9)
                    if improved:
                        state[ext_key] = _s(new_ext)
                        changed = True
                if (new_stop is not None and stop is not None and (
                        (side == 'LONG' and float(new_stop) > float(stop)) or
                        (side == 'SHORT' and float(new_stop) < float(stop)))):
                    res = exec_mgr.trail_stop(con, sym, side, pos, float(new_stop),
                                              ref=tag, tif='GTC')
                    if res.status == 'TRAILED':
                        state['stop'] = _s(new_stop)
                        stop = new_stop
                        changed = True
                        print(f">>> {mode} {tag} TRAIL stop -> {float(new_stop):.1f} ({treason})")
                if changed:
                    log_dynamo(dynamo, f"POSITION#{tag}", 'current',
                               {**state, 'ts': int(time.time())})
            print(f">>> {mode} {tag} hold pos={pos} side={side} held={held}d | "
                  f"close {detail['close']:.1f} {strat['label']}")
    elif desired in ('LONG', 'SHORT'):
        if not control_allows_entry(ctrl or {}):
            print(f">>> {mode} {tag} no entry — control state {control_state(ctrl or {})}")
            return
        if risk is None:
            risk = RiskEngine(RiskConfig(risk_budget_usd=GC_RISK_BUDGET))
        allowed, why = risk.can_enter()
        if not allowed:
            print(f">>> {mode} {tag} blocked by risk: {why}")
            return
        stop_price = strat['stop'](detail, desired)
        stop_distance = abs(detail['close'] - stop_price)
        vol = realized_vol_daily(df['Close'], 20)
        size = risk.position_size(stop_distance, point_value=POINT_VALUE,
                                  realized_vol=vol, price=detail['close'])
        if size > 0:
            action = 'BUY' if desired == 'LONG' else 'SELL'
            intent = TradeIntent(scope=BOT_KEY, tag=tag, symbol=sym, action=action,
                                 side=desired, qty=size, order_type='MKT',
                                 stop_price=float(stop_price),
                                 contract_month=front_month_for(sym), bar_time=today,
                                 signal_reason=dreason)
            res = exec_mgr.submit_entry(intent, con)
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
            ext_key = 'peak' if desired == 'LONG' else 'trough'
            pos_item = {
                'pos': size, 'side': desired, 'stop': _s(stop_price),
                'entry': _s(entry_px_filled), 'entry_date': today,
                ext_key: _s(detail['close']),
                'stop_mode': 'chandelier' if 'trail' in strat else 'fixed',
                'contract': front_month_for(sym), 'ts': int(time.time()),
            }
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'BUY' if desired == 'LONG' else 'SELL', 'qty': size,
                'entry': _s(entry_px_filled), 'stop': _s(stop_price),
                'contract': front_month_for(sym), 'strategy': sname, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', pos_item)
            print(f">>> {mode} {tag} ENTRY: {'BUY' if desired == 'LONG' else 'SELL'} {size} "
                  f"@ {round(entry_px_filled, 2)}, stop {round(stop_price, 1)} ({dreason})")
        else:
            print(f">>> {mode} {tag} size=0 (stop too wide for budget), skip")
    else:
        print(f"[{today}] {mode} {tag} flat, no entry ({dreason})")


# ===== main =====
def main():
    dynamo = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()
    mode = 'LIVE' if LIVE else 'PAPER'

    if already_ran_today(dynamo, BOT_KEY, today):
        print(f"[{today}] {mode} already ran today (RUN#{BOT_KEY}) — skip (dedupe guard)")
        return
    mark_ran_today(dynamo, BOT_KEY, today)

    # 1. data (fetch before IBKR so we still know the signal if connect fails)
    df = yf.download(DATA_TICKER, period='3y', interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df is None or df.empty or len(df) < MIN_BARS:
        print(f"[{today}] insufficient GC data ({0 if df is None else len(df)} bars) — skip")
        return

    # 2. connect IBKR
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=8)
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
            flatten_ibkr(ib, [SYMBOL], dynamo,
                         [f"{SYMBOL}_{s['name']}" for s in STRATEGIES], today, mode)
            ack_flatten(dynamo, BOT_KEY)
            clear_flatten(dynamo)
        if control_state(ctrl) == 'KILLED':
            print(f"[{today}] {mode} KILLED — all trading halted (positions flattened)")
            return
        if control_state(ctrl) == 'PAUSED':
            print(f"[{today}] {mode} PAUSED — no new entries; managing exits only")

        # 5. persistent risk engine (one instance for the whole run; restart-safe).
        risk_cfg = RiskConfig(risk_budget_usd=GC_RISK_BUDGET,
                              max_concurrent_positions=len(STRATEGIES))
        try:
            risk = RiskEngine.load(risk_cfg, RiskLedger(dynamo, scope=BOT_KEY))
        except RiskStateUnavailable as e:
            print(f"[{today}] {mode} HALT — risk state unreadable (fail-closed): {e}")
            return
        open_n = 0
        for s in STRATEGIES:
            st = get_state(dynamo, f"POSITION#{SYMBOL}_{s['name']}", 'current') or {}
            if int(st.get('pos', 0)) > 0:
                open_n += 1
        risk.set_open_positions(open_n)
        risk.touch_data()

        # 6. broker reconciliation — halt on any mismatch/unknown (fail-closed).
        r = reconcile(ib, dynamo, today_iso=today)
        if not r.ok:
            print(f"[{today}] {mode} HALT — reconciliation {r.status}: {r.reason}")
            risk.emergency_halt(f"reconciliation {r.status}: {r.reason}")
            return

        # 7. execution manager — the ONLY component that submits orders to IBKR.
        exec_mgr = ExecutionManager(ib, dynamo, scope=BOT_KEY)

        # 8. qualify contract (front-month, GC Feb/Apr/Jun/Aug/Oct/Dec cycle)
        try:
            con = ib.qualifyContracts(Future(SYMBOL, front_month_for(SYMBOL), EXCHANGE))[0]
        except Exception as e:
            print(f"[{today}] {mode} GC contract qualify failed: {e}")
            return

        detail = compute(df)
        for strat in STRATEGIES:
            run_strategy(ib, dynamo, con, SYMBOL, df, detail, strat, today, mode,
                         ctrl, risk, exec_mgr)

        # 9. forward-test snapshot (continuity with the former signal-only lane)
        try:
            payload = {'lane': 'futures', 'symbol': SYMBOL, 'date': today,
                       'mode': f'{mode}-EXEC', 'signals': []}
            for s in STRATEGIES:
                st = get_state(dynamo, f"POSITION#{SYMBOL}_{s['name']}", 'current') or {}
                sg = get_state(dynamo, f"SIGNAL#{SYMBOL}_{s['name']}", today) or {}
                payload['signals'].append({'family': s['name'], 'signal': sg.get('signal'),
                                           'pos': st.get('pos', 0), 'side': st.get('side', ''),
                                           'reason': sg.get('reason')})
            archive_scan_results('gc-signals', payload)
        except Exception as e:
            print(f"  signal archive failed: {e!r}")
    finally:
        ib.disconnect()


if __name__ == '__main__':
    main()
