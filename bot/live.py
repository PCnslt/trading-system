"""Live trading bot — TWO long-only strategies, MES + MNQ (paper forward-test).

Strategies (each tracked INDEPENDENTLY, tagged in DynamoDB pk):

  1) DONCHIAN — Donchian/ATR breakout (exact port of bot/futures_scan.py
     `sig_donchian` long-only — the validated trend edge: full-period PF
     2.23/1.80, walk-forward OOS PF 2.08/2.14 on ES/NQ):
       Entry : close > prior 20-day high   (h.rolling(20).max().shift(1))
       Stop  : 2*ATR below entry on fill, GTC, then CHANDELIER-TRAILED 3*ATR
               below the running high (tighten-only, never loosened).
       Exits : 5-day time stop -> close <= stop -> close < prior 20-day low.

  2) RSI2 — RSI(2) buy-the-dip (exact port of bot/allmarkets_scan.py
     `sig_rsi2` long-only — the validated buy-dip edge: OOS PF 2.69/2.21/1.79
     on ES/NQ/YM):
       Entry : RSI(2) < 10   (buy the dip)
       Exit  : RSI(2) > 70 (primary), 5-day time stop, or the ATR-RATCHET stop
               (2*ATR on fill -> breakeven at entry+1*ATR -> trail 2*ATR below
               running high at entry+2*ATR; tighten-only backstop).

Data: yfinance ES=F / NQ=F daily (same % action as MES/MNQ).
Execution: IBKR paper (DUR193467) MES + MNQ, front-month, dynamic roll.
Logging: DynamoDB pk tagged per strategy —
  SIGNAL#<sym>_<STRAT> / TRADE#<sym>_<STRAT> / POSITION#<sym>_<STRAT>
  (e.g. SIGNAL#MES_DONCHIAN, SIGNAL#MES_RSI2). A 'strategy' attribute is also
  written on each item. Paper only — LIVE env var stays false.
Run daily via cron 23:00 UTC.
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

from risk import RiskEngine, RiskConfig, realized_pnl
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
RISK_BUDGET = float(os.getenv('RISK_BUDGET', '50000'))
LIVE = os.getenv('LIVE', 'false').lower() == 'true'   # flip to true for real money

LOOKBACK = 20
STOP_ATR = 2.0
MAX_HOLD = 5
RSI2_LO = 10.0    # RSI(2) buy-the-dip entry
RSI2_HI = 70.0    # RSI(2) exit

# ---- intelligent trailing-stop params (paper-only, tighten-only, revertible) ----
CHAND_ATR = 3.0              # Donchian chandelier trail distance (vs 2.0 initial)
RATCHET_BREAKEVEN_ATR = 1.0  # RSI2: raise to breakeven at entry + 1*ATR
RATCHET_TRAIL_ATR = 2.0      # RSI2: trail (peak close - 2*ATR) at entry + 2*ATR

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
    return pd.DataFrame({'close': c, 'don_hi': don_hi, 'don_lo': don_lo,
                         'atr': atr, 'rsi2': r2}).iloc[-1]


# ===== strategy interface: entry -> (bool, reason); exit -> (bool, reason);
#      stop(detail) -> protective stop price (hard stop, never-lose-money). =====
def donchian_entry(detail):
    if not np.isnan(detail['don_hi']) and detail['close'] > detail['don_hi']:
        return True, f"close {detail['close']:.1f} > 20d-high {detail['don_hi']:.1f}"
    return False, f"close {detail['close']:.1f} <= 20d-high {detail['don_hi']:.1f}"


def donchian_exit(detail, stop, held):
    """Close-based exits, in backtest order: time stop -> ATR stop -> breakout."""
    if held >= MAX_HOLD:
        return True, f"time stop ({held}d >= {MAX_HOLD}d)"
    if stop is not None and detail['close'] <= stop:
        return True, f"close {detail['close']:.1f} <= stop {stop:.1f}"
    if not np.isnan(detail['don_lo']) and detail['close'] < detail['don_lo']:
        return True, f"close {detail['close']:.1f} < 20d-low {detail['don_lo']:.1f}"
    return False, "hold"


def donchian_stop(detail):
    return detail['close'] - STOP_ATR * detail['atr']


def rsi2_entry(detail):
    if detail['rsi2'] < RSI2_LO:
        return True, f"RSI(2) {detail['rsi2']:.1f} < {RSI2_LO}"
    return False, f"RSI(2) {detail['rsi2']:.1f} >= {RSI2_LO}"


def rsi2_exit(detail, stop, held):
    if held >= MAX_HOLD:
        return True, f"time stop ({held}d >= {MAX_HOLD}d)"
    if detail['rsi2'] > RSI2_HI:
        return True, f"RSI(2) {detail['rsi2']:.1f} > {RSI2_HI}"
    return False, "hold"


def rsi2_stop(detail):
    # NEVER-LOSE-MONEY: rest the 2*ATR distance as a hard protective stop
    # (previously 'sizing only, no order' — now the same number IS the stop).
    return detail['close'] - STOP_ATR * detail['atr']


# ===== trailing-stop functions (tighten-only; called each eval while holding) =====
# Each returns (new_stop_or_None, reason). The runner only calls exec_mgr.trail_stop
# when new_stop is not None AND above the currently resting stop (never loosens).
def highest_close_since_entry(df, entry_date):
    """Max close on bars strictly AFTER entry_date (matches held_days)."""
    if not entry_date or df is None or df.empty:
        return None
    e = pd.Timestamp(entry_date)
    idx = df.index
    if getattr(idx, 'tz', None) is not None:
        e = e.tz_localize(idx.tz)
    after = df.loc[idx > e, 'Close']
    if after.empty:
        return None
    return float(after.max())


def donchian_trail(detail, state, df):
    """Chandelier: candidate = (highest close since entry) - 3*ATR, only upward."""
    peak = highest_close_since_entry(df, state.get('entry_date'))
    if peak is None or not np.isfinite(detail['atr']):
        return None, "no close since entry / no ATR"
    candidate = peak - CHAND_ATR * detail['atr']
    return candidate, (f"chandelier {peak:.1f} - 3*ATR({detail['atr']:.1f}) "
                       f"= {candidate:.1f}")


def rsi2_trail(detail, state, df):
    """ATR ratchet: breakeven at entry+1*ATR, trail (peak-2*ATR) at entry+2*ATR.

    RSI(2)>70 remains the PRIMARY exit; the ratchet is the backstop, not the
    primary. Entry-price and +1/+2*ATR thresholds use ENTRY-time ATR (stable);
    the trail distance uses the CURRENT ATR (chandelier-style running distance).
    """
    entry_px = float(state['entry']) if state.get('entry') else None
    entry_atr = float(state['entry_atr']) if state.get('entry_atr') else None
    if entry_px is None or entry_atr is None:
        return None, "missing entry/entry_atr"
    close = detail['close']
    candidate = None
    if close >= entry_px + RATCHET_BREAKEVEN_ATR * entry_atr:
        candidate = entry_px          # breakeven
    if close >= entry_px + RATCHET_TRAIL_ATR * entry_atr:
        peak = highest_close_since_entry(df, state.get('entry_date'))
        if peak is not None and np.isfinite(detail['atr']):
            candidate = peak - RATCHET_TRAIL_ATR * detail['atr']
    if candidate is None:
        return None, (f"below breakeven (close {close:.1f} < "
                      f"entry+1*ATR {entry_px + RATCHET_BREAKEVEN_ATR * entry_atr:.1f})")
    return candidate, f"ratchet -> {candidate:.1f}"


STRATEGIES = [
    {'name': 'DONCHIAN', 'label': 'Donchian/ATR long',
     'entry': donchian_entry, 'exit': donchian_exit, 'stop': donchian_stop,
     'trail': donchian_trail},
    {'name': 'RSI2', 'label': 'RSI(2) buy-dip long',
     'entry': rsi2_entry, 'exit': rsi2_exit, 'stop': rsi2_stop,
     'trail': rsi2_trail},
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


# ===== per-strategy runner =====
def run_strategy(ib, dynamo, con, sym, df, detail, c, strat, today, mode, ctrl=None,
                 risk=None, exec_mgr=None):
    sname = strat['name']
    tag = f"{sym}_{sname}"                       # e.g. MES_DONCHIAN, MES_RSI2
    state = get_state(dynamo, f"POSITION#{tag}", 'current') or {}
    pos = int(state.get('pos', 0))
    stop = float(state['stop']) if state.get('stop') else None
    entry_px = float(state['entry']) if state.get('entry') else None
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
    else:
        sig['rsi2'] = str(round(detail['rsi2'], 2))
    log_dynamo(dynamo, f"SIGNAL#{tag}", today, sig)

    if pos > 0:
        should_exit, xreason = strat['exit'](detail, stop, held)
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
        elif not exec_mgr.is_stop_open(sym, 'LONG'):
            # state long but GTC stop no longer resting -> filled intraday
            exit_px = stop if stop is not None else detail['close']
            if risk is not None and entry_px is not None:
                risk.record_close(realized_pnl('LONG', entry_px, exit_px, c['point_value'], pos))
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'EXIT', 'qty': pos, 'reason': 'stop-filled (intraday)',
                'strategy': sname, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': 0, 'stop': '0', 'entry': '0', 'entry_date': '', 'ts': int(time.time())})
            print(f">>> {mode} {tag} EXIT via protective stop (intraday fill)")
        else:
            # holding: tighten the trailing stop (tighten-only) before reporting.
            if 'trail' in strat:
                new_stop, treason = strat['trail'](detail, state, df)
                if (new_stop is not None and stop is not None
                        and float(new_stop) > float(stop)):
                    res = exec_mgr.trail_stop(con, sym, 'LONG', pos, float(new_stop),
                                              tif='GTC')
                    if res.status == 'TRAILED':
                        log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                            'pos': pos, 'stop': str(round(new_stop, 2)),
                            'entry': str(round(entry_px, 2)) if entry_px is not None else '0',
                            'entry_date': entry_date or '',
                            'entry_atr': state.get('entry_atr', ''),
                            'contract': state.get('contract', front_month()),
                            'ts': int(time.time())})
                        print(f">>> {mode} {tag} TRAIL stop -> {new_stop:.1f} ({treason})")
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
        size = risk.position_size(detail['close'] - stop_price, point_value=c['point_value'])
        if size > 0:
            intent = TradeIntent(scope='live', tag=tag, symbol=sym, action='BUY',
                                 side='LONG', qty=size, order_type='MKT',
                                 stop_price=float(stop_price), contract_month=front_month(),
                                 bar_time=today, signal_reason=ereason)
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
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'BUY', 'qty': size, 'entry': str(round(entry_px_filled, 2)),
                'stop': str(round(stop_price, 2)), 'contract': front_month(),
                'strategy': sname, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': size, 'stop': str(round(stop_price, 2)),
                'entry': str(round(entry_px_filled, 2)),
                'entry_date': today, 'entry_atr': str(round(detail['atr'], 4)),
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

    # Dedupe guard: skip if this bot already ran today (double-schedule defence).
    if already_ran_today(dynamo, 'live', today):
        print(f"[{today}] {mode} already ran today (RUN#live) — skip (dedupe guard)")
        return
    mark_ran_today(dynamo, 'live', today)

    # 1. data (fetch before IBKR so we can still log signals if connect fails)
    data = {}
    for c in CONTRACTS:
        df = yf.download(c['data'], period='2y', interval='1d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[c['symbol']] = df
        _archive_daily_bar(c, df)

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
                              max_concurrent_positions=len(CONTRACTS) * len(STRATEGIES))
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
