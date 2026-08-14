"""Live intraday bot — MES paper forward-test on real-time IBKR 5m/15m bars.

Two intraday strategies, each tracked INDEPENDENTLY (tagged in DynamoDB pk),
flattened by end of session (no overnight risk):

  1) FADESHORT — intraday fade-rally SHORT (RSI2 + Bollinger).
     A noise-filtered intraday port of the two VALIDATED daily fade-rally
     triggers from live_bondsfx.py (RSI2SHORT: RSI(2) > 90; BBANDSHORT:
     close > upper band). On 5m bars, RSI(2) > 90 alone fires on every 2-bar
     pop, so the entry requires BOTH:
       Entry : RSI(2) > 90  AND  close > upper Bollinger band (20-bar, 2.0 sd)
       Exit  : close <= mid band (reversion done), or EOD flatten. NO stop
               (the daily fade-rally backtest has none; 2*ATR used for sizing).
     HONEST: this is an intraday HYPOTHESIS, not a validated intraday edge —
     the daily fade-rally was validated on bonds/FX, not intraday MES.

  2) DONCH15 — 15m Donchian(20)/ATR breakout, BOTH directions (port of the
     `_donchian_15m` cell in intraday_scan.py):
       Entry : close break of prior 20-bar channel (long > hi, short < lo)
       Stop  : 2*ATR protective stop (DAY)
       Exit  : close crosses the opposite channel mid, or 2*ATR stop, or EOD.
     The preliminary 60-day scan was thin (long PF 0.08/18, short 1.27/21 —
     NOT statistically meaningful); this forward-test exists to collect real
     sample. Both directions kept (breakout goes either way).

Data: IBKR reqHistoricalData (paper DUR193467) — 5m for FADESHORT, 15m for
DONCH15 — via load_ibkr_bars()/prep_rth() from bot/intraday_scan.py.
Execution: IBKR paper MES, front-month, dynamic roll. clientId=72 (distinct
from live.py's 70 and live_bondsfx.py's 71).
State: POSITION#MES_<STRAT> / 'current', keyed by session_date so a new day
starts flat. Only ONE intraday strategy holds MES at a time (global gate) —
avoids netting the same contract. EOD flatten from 19:45 UTC (15:45 ET).

Schedule: cron every 15 min during RTH (13:30-20:00 UTC weekdays). The bot
re-gates internally: entries 13:30-19:30 UTC, flatten from 19:45 UTC.
Paper only — LIVE env var stays false.
"""
import os
import sys
import time
import datetime as dt

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv
from ib_insync import IB, Future, MarketOrder, StopOrder

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.s3_archive import archive_intraday_bars

from risk import RiskEngine, RiskConfig, realized_pnl
from execution import confirm_fill
from intraday_scan import load_ibkr_bars, prep_rth
from control import (get_control, control_state, control_allows_entry, wants_flatten,
                     clear_flatten, ack_flatten, flatten_ibkr, ControlUnavailable,
                     account_mode_ok)

load_dotenv()

# ===== config =====
IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
CLIENT_ID = 72                                     # distinct from live.py(70)/bonds(71)
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
INTRA_RISK_BUDGET = float(os.getenv('INTRA_RISK_BUDGET', '25000'))  # intraday sleeve
LIVE = os.getenv('LIVE', 'false').lower() == 'true'

CONTRACT = {'symbol': 'MES', 'exchange': 'CME', 'point_value': 5.0}
DURATION = '5 D'      # enough warmup for 20-bar Bollinger (5m) + 20-bar Donchian (15m)

# session window (UTC). MES RTH 9:30-16:00 ET == 13:30-20:00 UTC.
RTH_OPEN_UTC = dt.time(13, 30)
RTH_CLOSE_UTC = dt.time(20, 0)
ENTRY_CUTOFF_UTC = dt.time(19, 30)   # no new entries in the last 30 min
EOD_FLATTEN_UTC = dt.time(19, 45)    # flatten any open position from 15:45 ET

# FADESHORT (5m) params
FADE_RSI2_OVERBOUGHT = 90.0
FADE_BOLL_N = 20
FADE_BOLL_K = 2.0
FADE_ATR_N = 14
FADE_STOP_ATR = 2.0    # sizing proxy only (no GTC stop in backtest)

# DONCH15 (15m) params
DC_N = 20
DC_ATR_N = 14
DC_STOP_ATR = 2.0


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


def bollinger(close, n, k):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid, mid + k * sd, mid - k * sd


# ===== strategy detail builders (last-bar values) =====
def fadeshort_detail(df):
    c = df['Close']
    mid, upper, _ = bollinger(c, FADE_BOLL_N, FADE_BOLL_K)
    return {
        'close': float(c.iloc[-1]),
        'rsi2': float(rsi(c, 2).iloc[-1]),
        'boll_upper': float(upper.iloc[-1]),
        'boll_mid': float(mid.iloc[-1]),
        'atr': float(wilder_atr(df['High'], df['Low'], c, FADE_ATR_N).iloc[-1]),
    }


def donch15_detail(df):
    h, l, c = df['High'], df['Low'], df['Close']
    hi = h.rolling(DC_N).max().shift(1)
    lo = l.rolling(DC_N).min().shift(1)
    return {
        'close': float(c.iloc[-1]),
        'don_hi': float(hi.iloc[-1]),
        'don_lo': float(lo.iloc[-1]),
        'mid': float((hi.iloc[-1] + lo.iloc[-1]) / 2),
        'atr': float(wilder_atr(h, l, c, DC_ATR_N).iloc[-1]),
    }


# ===== strategy interface =====
# entry(detail) -> (side, reason); side: -1 short, +1 long, 0 flat
# exit(detail, side) -> (bool, reason)
# stop(detail, side) -> stop price (protective, or sizing proxy when no stop order)
def fadeshort_entry(d):
    extended = d['close'] > d['boll_upper']
    ob = d['rsi2'] > FADE_RSI2_OVERBOUGHT
    if ob and extended:
        return -1, (f"overbought: RSI2 {d['rsi2']:.1f} > {FADE_RSI2_OVERBOUGHT} "
                    f"AND close {d['close']:.1f} > upper {d['boll_upper']:.1f}")
    return 0, (f"no fade: RSI2 {d['rsi2']:.1f} (need >{FADE_RSI2_OVERBOUGHT}) / "
               f"close {d['close']:.1f} vs upper {d['boll_upper']:.1f}")


def fadeshort_exit(d, side):
    if d['close'] <= d['boll_mid']:
        return True, f"close {d['close']:.1f} <= mid band {d['boll_mid']:.1f} (reversion done)"
    return False, "hold"


def fadeshort_stop(d, side):
    return d['close'] + FADE_STOP_ATR * d['atr']   # above entry (sizing proxy, no order)


def donch15_entry(d):
    if np.isnan(d['don_hi']) or np.isnan(d['don_lo']):
        return 0, "insufficient history"
    if d['close'] > d['don_hi']:
        return 1, f"close {d['close']:.1f} > 15m 20-bar high {d['don_hi']:.1f}"
    if d['close'] < d['don_lo']:
        return -1, f"close {d['close']:.1f} < 15m 20-bar low {d['don_lo']:.1f}"
    return 0, f"inside channel [{d['don_lo']:.1f}, {d['don_hi']:.1f}]"


def donch15_exit(d, side):
    if np.isnan(d['mid']):
        return False, "insufficient history"
    if side == 'LONG' and d['close'] < d['mid']:
        return True, f"close {d['close']:.1f} < channel mid {d['mid']:.1f}"
    if side == 'SHORT' and d['close'] > d['mid']:
        return True, f"close {d['close']:.1f} > channel mid {d['mid']:.1f}"
    return False, "hold"


def donch15_stop(d, side):
    if side == 'LONG':
        return d['close'] - DC_STOP_ATR * d['atr']
    return d['close'] + DC_STOP_ATR * d['atr']


STRATEGIES = [
    {'name': 'FADESHORT', 'barsize': '5 mins', 'label': 'intraday fade-rally short',
     'has_stop_order': False,
     'detail': fadeshort_detail, 'entry': fadeshort_entry,
     'exit': fadeshort_exit, 'stop': fadeshort_stop,
     'sig_keys': ['rsi2', 'boll_upper', 'boll_mid', 'atr']},
    {'name': 'DONCH15', 'barsize': '15 mins', 'label': '15m Donchian/ATR breakout',
     'has_stop_order': True,
     'detail': donch15_detail, 'entry': donch15_entry,
     'exit': donch15_exit, 'stop': donch15_stop,
     'sig_keys': ['don_hi', 'don_lo', 'mid', 'atr']},
]


# ===== contract / clock =====
def front_month(now=None):
    now = now or dt.date.today()
    for m in (3, 6, 9, 12):
        if now.month <= m:
            return f"{now.year}{m:02d}"
    return f"{now.year + 1}03"


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


# ===== DynamoDB helpers =====
def log_dynamo(table, pk, sk, data):
    table.put_item(Item={'pk': pk, 'sk': sk, **data})


def get_state(table, pk, sk):
    r = table.get_item(Key={'pk': pk, 'sk': sk})
    return r.get('Item')


def _archive_bars(sname, barsize, df):
    """Persist this run's RTH bars to S3 before they're discarded.

    One object per (barsize, session_date), overwritten each run so the key
    always holds the latest full window (bounded: 1 object/day/barsize).
    """
    if df is None or df.empty:
        return
    try:
        slug = barsize.replace(' mins', 'min')       # '5 mins' -> '5min'
        date = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
        records = [{'date': idx.isoformat(), 'open': float(r['Open']),
                    'high': float(r['High']), 'low': float(r['Low']),
                    'close': float(r['Close']), 'volume': float(r['Volume'])}
                   for idx, r in df.iterrows()]
        archive_intraday_bars(CONTRACT['symbol'], slug, date, records)
        print(f"[{sname}] archived {len(records)} {slug} bars -> "
              f"futures-bars/intraday/{CONTRACT['symbol']}/{slug}/{date}.json")
    except Exception as e:
        print(f"[{sname}] intraday bars archive failed: {e}")


def _read_state(dynamo, sname, today):
    st = get_state(dynamo, f"POSITION#MES_{sname}", 'current') or {}
    if st.get('session_date') != today:      # stale (previous session) -> flat
        return {}
    return st


def _other_open(dynamo, exclude, today):
    for sname in ('FADESHORT', 'DONCH15'):
        if sname == exclude:
            continue
        st = _read_state(dynamo, sname, today)
        if int(st.get('pos', 0)) > 0:
            return True, sname
    return False, None


# The DAILY index bot (live.py, clientId 70) holds MES overnight in the SAME
# paper account. Its tags:
DAILY_MES_TAGS = ['MES_DONCHIAN', 'MES_RSI2']


def _daily_mes_held(dynamo):
    """True if the daily bot currently holds MES (from its DynamoDB state)."""
    for tag in DAILY_MES_TAGS:
        st = get_state(dynamo, f'POSITION#{tag}', 'current') or {}
        if int(st.get('pos', 0)) > 0:
            return True, tag
    return False, None


# ===== IBKR helpers =====
def stop_open(ib, sym, side):
    action = 'SELL' if side == 'LONG' else 'BUY'
    return any(o.contract.symbol == sym and o.order.action == action
               and o.order.orderType == 'STP' for o in ib.openOrders())


def _place_close(ib, con, side, qty):
    """Market order to close: sell a long, buy-to-cover a short."""
    action = 'SELL' if side == 'LONG' else 'BUY'
    ib.placeOrder(con, MarketOrder(action, qty, tif='DAY'))


def _cancel_stops(ib, sym):
    for o in ib.openOrders():
        if o.contract.symbol == sym and o.order.orderType == 'STP':
            ib.cancelOrder(o)


# ===== runner =====
def run_strategy(ib, dynamo, con, strat, df, now, today, mode, ctrl=None, risk=None):
    sname = strat['name']
    tag = f"MES_{sname}"
    detail = strat['detail'](df)
    state = _read_state(dynamo, sname, today)
    pos = int(state.get('pos', 0))
    side = state.get('side')                  # 'LONG' / 'SHORT'
    stop = float(state['stop']) if state.get('stop') else None
    entry_px = float(state['entry']) if state.get('entry') else None

    now_t = now.time()
    in_window = RTH_OPEN_UTC <= now_t < RTH_CLOSE_UTC
    eod = now_t >= EOD_FLATTEN_UTC
    entry_allowed = in_window and now_t < ENTRY_CUTOFF_UTC

    entry_side, ereason = strat['entry'](detail)

    # skip flat, outside-RTH runs silently (no SIGNAL spam on pre/post-session runs)
    if pos == 0 and not in_window:
        print(f"[{now.isoformat()}] {mode} {tag} flat, outside RTH — skip")
        return

    sig = {
        'signal': 'EXIT' if pos > 0 else ('SHORT' if entry_side == -1
                                          else ('LONG' if entry_side == 1 else 'NONE')),
        'strategy': sname,
        'close': str(round(detail['close'], 2)),
        'pos': pos, 'side': side or '', 'reason': ereason,
        'eod': eod, 'session_date': today, 'ts': int(time.time()),
    }
    for k in strat['sig_keys']:
        v = detail.get(k)
        sig[k] = str(round(v, 2)) if v is not None and not (isinstance(v, float) and np.isnan(v)) else ''
    log_dynamo(dynamo, f"SIGNAL#{tag}", now.isoformat(), sig)

    if pos > 0:
        # open position -> evaluate exit / EOD flatten
        if eod:
            _exit(dynamo, ib, con, tag, sname, side, pos, 'EOD-flatten',
                  detail['close'], today, mode, risk, entry_px)
            return
        should_exit, xreason = strat['exit'](detail, side)
        if should_exit:
            _exit(dynamo, ib, con, tag, sname, side, pos, xreason,
                  detail['close'], today, mode, risk, entry_px)
        elif strat['has_stop_order'] and not stop_open(ib, 'MES', side):
            # protective stop no longer resting -> filled intraday
            exit_px = stop if stop is not None else detail['close']
            if risk is not None and entry_px is not None:
                risk.record_close(realized_pnl(side, entry_px, exit_px, CONTRACT['point_value'], pos))
            log_dynamo(dynamo, f"TRADE#{tag}", now.isoformat(), {
                'side': 'EXIT', 'qty': pos, 'exit_px': str(stop),
                'reason': 'stop-filled', 'strategy': sname, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': 0, 'side': '', 'stop': '0', 'entry': '0',
                'session_date': today, 'ts': int(time.time())})
            print(f">>> {mode} {tag} EXIT via protective stop (intraday fill) @ {stop}")
        else:
            print(f">>> {mode} {tag} hold {side} {pos} | close {detail['close']:.1f} | {xreason}")
    else:
        # flat -> evaluate entry
        if entry_side != 0 and entry_allowed and not eod:
            if not control_allows_entry(ctrl or {}):
                print(f">>> {mode} {tag} no entry — control state {control_state(ctrl or {})}")
                return
            other, other_name = _other_open(dynamo, sname, today)
            if other:
                print(f"[{today}] {mode} {tag} no entry — {other_name} already holds MES")
                return
            if risk is None:
                risk = RiskEngine(RiskConfig(risk_budget_usd=INTRA_RISK_BUDGET))
            allowed, why = risk.can_enter()
            if not allowed:
                print(f">>> {mode} {tag} blocked by risk: {why}")
                return
            stop_px = strat['stop'](detail, 'SHORT' if entry_side == -1 else 'LONG')
            stop_dist = abs(stop_px - detail['close'])
            size = risk.position_size(stop_dist, point_value=CONTRACT['point_value'])
            if size <= 0:
                print(f">>> {mode} {tag} size=0 (stop too wide for budget), skip")
                return
            nside = 'SHORT' if entry_side == -1 else 'LONG'
            action = 'SELL' if entry_side == -1 else 'BUY'
            trade = ib.placeOrder(con, MarketOrder(action, size, tif='DAY'))
            filled, avg_px, fstatus = confirm_fill(ib, trade)
            if filled <= 0:
                print(f">>> {mode} {tag} ENTRY NOT FILLED (status={fstatus}) — no state written")
                return
            if filled < size:
                print(f">>> {mode} {tag} PARTIAL fill {filled}/{size} — writing actual qty")
                size = filled
            entry_px_filled = avg_px if avg_px > 0 else detail['close']
            if strat['has_stop_order']:
                saction = 'BUY' if entry_side == -1 else 'SELL'
                ib.placeOrder(con, StopOrder(saction, size, stop_px, tif='DAY'))
            risk.record_fill()
            log_dynamo(dynamo, f"TRADE#{tag}", now.isoformat(), {
                'side': nside, 'qty': size, 'entry': str(round(entry_px_filled, 2)),
                'stop': str(round(stop_px, 2)), 'contract': front_month(),
                'strategy': sname, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': size, 'side': nside, 'stop': str(round(stop_px, 2)),
                'entry': str(round(entry_px_filled, 2)), 'entry_ts': now.isoformat(),
                'session_date': today, 'contract': front_month(), 'ts': int(time.time())})
            print(f">>> {mode} {tag} ENTRY: {nside} {size} @ {round(entry_px_filled, 2)}, "
                  f"stop {round(stop_px, 1)} ({ereason})")
        else:
            gate = 'EOD' if eod else ('entry-cutoff' if not entry_allowed else 'no-signal')
            print(f"[{today}] {mode} {tag} flat ({gate}): {ereason}")


def _exit(dynamo, ib, con, tag, sname, side, pos, reason, exit_px, today, mode, risk=None, entry_px=None):
    _cancel_stops(ib, 'MES')
    _place_close(ib, con, side, pos)
    ib.sleep(1)
    if risk is not None and entry_px is not None:
        risk.record_close(realized_pnl(side, entry_px, exit_px, CONTRACT['point_value'], pos))
    log_dynamo(dynamo, f"TRADE#{tag}", now_utc().isoformat(), {
        'side': 'EXIT', 'qty': pos, 'exit_px': str(round(exit_px, 2)),
        'reason': reason, 'strategy': sname, 'ts': int(time.time())})
    log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
        'pos': 0, 'side': '', 'stop': '0', 'entry': '0',
        'session_date': today, 'ts': int(time.time())})
    print(f">>> {mode} {tag} EXIT {side} {pos} @ {exit_px:.2f} ({reason})")


def _reconcile(ib, dynamo, con, today, mode, risk=None):
    """Detect unaccounted MES positions. NEVER flatten the daily bot's MES and
    never flatten off stale IBKR truth — when in doubt, stand down (fail-closed).

    Returns True if safe to proceed, False if an unknown/unaccounted MES position
    was found (caller must halt new entries and alert an operator).
    """
    net = sum(int(p.position) for p in ib.positions() if p.contract.symbol == 'MES')
    expected_intra = 0
    for sname in ('FADESHORT', 'DONCH15'):
        st = _read_state(dynamo, sname, today)
        if int(st.get('pos', 0)) > 0:
            q = int(st['pos'])
            expected_intra += q if st.get('side') == 'LONG' else -q

    # Daily index bot (live.py) holds MES overnight in the SAME paper account.
    # Its position is authoritative — intraday must never reconcile/flatten it.
    expected_daily = 0
    for tag in DAILY_MES_TAGS:
        st = get_state(dynamo, f'POSITION#{tag}', 'current') or {}
        expected_daily += int(st.get('pos', 0))
    if expected_daily != 0:
        print(f"[{today}] {mode} reconcile: daily bot holds MES ({expected_daily}) — "
              f"skip reconcile (stand down, do NOT flatten)")
        return False

    if net != expected_intra:
        # Unaccounted MES — could be an orphaned intraday fill OR a daily bot
        # position whose state is stale. DO NOT flatten off IBKR alone.
        print(f"CRITICAL {mode}: MES net {net} != intraday expected {expected_intra} — "
              f"unknown position; standing down (no flatten, no entries)")
        if risk is not None:
            risk.emergency_halt("reconciliation mismatch")
        return False
    return True


# ===== main =====
def main():
    dynamo = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)
    now = now_utc()
    today = now.date().isoformat()
    mode = 'LIVE' if LIVE else 'PAPER'

    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"[{now.isoformat()}] {mode} IBKR connect failed: {e}")
        return

    try:
        con = ib.qualifyContracts(Future(CONTRACT['symbol'], front_month(),
                                         CONTRACT['exchange']))[0]
    except Exception as e:
        print(f"[{now.isoformat()}] {mode} MES contract qualify failed: {e}")
        ib.disconnect()
        return

    try:
        # account guard — refuse orders on paper/live mismatch (fail-closed)
        ok, why = account_mode_ok(mode, ib.managedAccounts())
        if not ok:
            print(f"[{now.isoformat()}] {mode} HALT — {why}")
            return

        # control plane — honour kill/pause/flatten BEFORE any order (fail-closed).
        # flatten_ibkr also resets DAILY MES tags because a global MES flatten
        # closes the daily bot's shared position too.
        try:
            ctrl = get_control(dynamo)
        except ControlUnavailable as e:
            print(f"[{now.isoformat()}] {mode} HALT — control state unavailable (fail-closed): {e}")
            return
        if control_state(ctrl) is None:
            print(f"[{now.isoformat()}] {mode} HALT — unknown control state (fail-closed)")
            return
        if wants_flatten(ctrl):
            flatten_ibkr(ib, [CONTRACT['symbol']], dynamo,
                         [f"MES_{s['name']}" for s in STRATEGIES] + DAILY_MES_TAGS,
                         today, mode)
            ack_flatten(dynamo, 'live_intraday')
            clear_flatten(dynamo)
        if control_state(ctrl) == 'KILLED':
            print(f"[{now.isoformat()}] {mode} KILLED — all trading halted (positions flattened)")
            return

        # cross-bot guard: never net/flatten the daily bot's MES position
        daily_held, daily_tag = _daily_mes_held(dynamo)
        if daily_held:
            print(f"[{now.isoformat()}] {mode} intraday STAND DOWN — "
                  f"daily bot holds MES ({daily_tag})")
            return

        # persistent risk engine — ONE instance for the whole run.
        risk = RiskEngine(RiskConfig(risk_budget_usd=INTRA_RISK_BUDGET,
                                     max_concurrent_positions=1))
        open_n = 0
        for sname in ('FADESHORT', 'DONCH15'):
            st = _read_state(dynamo, sname, today)
            if int(st.get('pos', 0)) > 0:
                open_n += 1
        risk.set_open_positions(open_n)
        risk.touch_data()

        bars = {}
        for strat in STRATEGIES:
            df = load_ibkr_bars(ib, con, duration=DURATION, bar_size=strat['barsize'], rth=True)
            bars[strat['name']] = prep_rth(df) if not df.empty else df
            _archive_bars(strat['name'], strat['barsize'], bars[strat['name']])

        if not _reconcile(ib, dynamo, con, today, mode, risk):
            print(f"[{now.isoformat()}] {mode} STAND DOWN — reconciliation failed / unknown MES position")
            return

        for strat in STRATEGIES:
            df = bars[strat['name']]
            min_bars = FADE_BOLL_N + 5 if strat['name'] == 'FADESHORT' else DC_N + 5
            if df.empty or len(df) < min_bars:
                print(f"[{now.isoformat()}] {mode} {strat['name']}: insufficient bars ({len(df)})")
                continue
            run_strategy(ib, dynamo, con, strat, df, now, today, mode, ctrl, risk)
    finally:
        ib.disconnect()


if __name__ == '__main__':
    main()
