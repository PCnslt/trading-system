"""Live intraday bot — MES paper forward-test on real-time IBKR 5m/15m bars.

Two intraday strategies, each tracked INDEPENDENTLY (tagged in DynamoDB pk),
flattened by end of session (no overnight risk):

  1) FADESHORT — intraday fade-rally SHORT (RSI2 + Bollinger).
     A noise-filtered intraday port of the two VALIDATED daily fade-rally
     triggers from live_bondsfx.py (RSI2SHORT: RSI(2) > 90; BBANDSHORT:
     close > upper band). On 5m bars, RSI(2) > 90 alone fires on every 2-bar
     pop, so the entry requires BOTH:
       Entry : RSI(2) > 90  AND  close > upper Bollinger band (20-bar, 2.0 sd)
       Exit  : close <= mid band (reversion done), 2*ATR hard stop, or EOD flatten.
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
avoids netting the same contract. EOD flatten from 15:45 ET.

Schedule: cron every 15 min during RTH (09:30-16:00 ET weekdays). The bot
re-gates internally: entries 09:30-15:30 ET, flatten from 15:45 ET.
Paper only — LIVE env var stays false.

EXECUTION MODE (2026-08-16, intraday-first Gate-1 validation): the backtest
(research/intraday_validate.py -> INTRADAY_GATE1_VALIDATION.md) found NO cost-surviving
intraday edge — all 5 candidates (ORB/MOM/VWAP/DONCH15/FADESHORT) are NO-GO or
HOLD at 3-tick slippage + commission. Per "validated edges only +
never-lose-money", this bot now runs SIGNAL-ONLY by default (bars + SIGNAL#
still collected every run, no paper orders). Set INTRA_EXECUTION=paper to
re-enable paper fills for a LATER validated edge.
"""
import os
import sys
import time
import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv
from ib_insync import IB, Future

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.s3_archive import archive_intraday_bars

from risk import RiskEngine, RiskConfig, realized_pnl
from hardening.risk_ledger import RiskLedger, RiskStateUnavailable
from hardening.reconciler import reconcile
from hardening.exec_manager import ExecutionManager, TradeIntent
from intraday_scan import load_ibkr_bars, prep_rth
from control import (get_control, control_state, control_allows_entry, wants_flatten,
                     clear_flatten, ack_flatten, flatten_ibkr, ControlUnavailable,
                     account_mode_ok)

load_dotenv()
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

# ===== config =====
IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
CLIENT_ID = 72                                     # distinct from live.py(70)/bonds(71)
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
INTRA_RISK_BUDGET = float(os.getenv('INTRA_RISK_BUDGET', '25000'))  # intraday sleeve
INTRA_RISK_PCT = 0.01     # 1% risk/trade MAX (owner: 0.5-1%, capital-preservation objective)
LIVE = os.getenv('LIVE', 'false').lower() == 'true'
EXECUTION_MODE = os.getenv('INTRA_EXECUTION', 'NONE').upper()   # 'NONE' | 'PAPER'

CONTRACT = {'symbol': 'MES', 'exchange': 'CME', 'point_value': 5.0}
DURATION = '5 D'      # enough warmup for 20-bar Bollinger (5m) + 20-bar Donchian (15m)

# session window (America/New_York). MES RTH 09:30-16:00 ET, DST-aware via zoneinfo.
NY = ZoneInfo('America/New_York')
RTH_OPEN = dt.time(9, 30)
RTH_CLOSE = dt.time(16, 0)
ENTRY_CUTOFF = dt.time(15, 30)   # no new entries in the last 30 min
EOD_FLATTEN = dt.time(15, 45)    # flatten any open position from 15:45 ET

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
    return d['close'] + FADE_STOP_ATR * d['atr']   # above entry (hard stop, never-lose-money)


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
     'detail': fadeshort_detail, 'entry': fadeshort_entry,
     'exit': fadeshort_exit, 'stop': fadeshort_stop,
     'sig_keys': ['rsi2', 'boll_upper', 'boll_mid', 'atr']},
    {'name': 'DONCH15', 'barsize': '15 mins', 'label': '15m Donchian/ATR breakout',
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


def now_et():
    return dt.datetime.now(NY)


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
        date = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')  # S3 key date stays UTC (storage convention)
        records = [{'ts': idx.isoformat(), 'open': float(r['Open']),
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
# paper account. Its tags (ALL FOUR strategies — keep in sync with live.py STRATEGIES):
DAILY_MES_TAGS = ['MES_DONCHIAN', 'MES_RSI2', 'MES_RSI2PT', 'MES_REV2']


def _daily_mes_held(dynamo):
    """True if the daily bot currently holds MES (from its DynamoDB state)."""
    for tag in DAILY_MES_TAGS:
        st = get_state(dynamo, f'POSITION#{tag}', 'current') or {}
        if int(st.get('pos', 0)) > 0:
            return True, tag
    return False, None


# ===== runner =====
def run_strategy(ib, dynamo, con, strat, df, now, today, mode, ctrl=None, risk=None,
                 exec_mgr=None):
    sname = strat['name']
    tag = f"MES_{sname}"
    detail = strat['detail'](df)
    state = _read_state(dynamo, sname, today)
    pos = int(state.get('pos', 0))
    side = state.get('side')                  # 'LONG' / 'SHORT'
    stop = float(state['stop']) if state.get('stop') else None
    entry_px = float(state['entry']) if state.get('entry') else None

    now_t = now.time()
    in_window = RTH_OPEN <= now_t < RTH_CLOSE
    eod = now_t >= EOD_FLATTEN
    entry_allowed = in_window and now_t < ENTRY_CUTOFF

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
        'execution': EXECUTION_MODE,
    }
    for k in strat['sig_keys']:
        v = detail.get(k)
        sig[k] = str(round(v, 2)) if v is not None and not (isinstance(v, float) and np.isnan(v)) else ''
    log_dynamo(dynamo, f"SIGNAL#{tag}", now.isoformat(), sig)

    if EXECUTION_MODE != 'PAPER':
        # validated-edges-only: no intraday candidate cleared the Gate-1 cost
        # stress (research/INTRADAY_GATE1_VALIDATION.md) — log the signal, place no orders.
        print(f"[{now.isoformat()}] {mode} {tag} SIGNAL-ONLY ({sig['signal']}) {sig['reason']}")
        return

    if pos > 0:
        # open position -> evaluate exit / EOD flatten
        if eod:
            _exit(dynamo, ib, con, tag, sname, side, pos, 'EOD-flatten',
                  detail['close'], today, mode, risk, entry_px, exec_mgr)
            return
        should_exit, xreason = strat['exit'](detail, side)
        if should_exit:
            _exit(dynamo, ib, con, tag, sname, side, pos, xreason,
                  detail['close'], today, mode, risk, entry_px, exec_mgr)
        elif not exec_mgr.is_stop_open('MES', side):
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
            intent = TradeIntent(scope='live_intraday', tag=tag, symbol='MES', action=action,
                                 side=nside, qty=size, order_type='MKT',
                                 stop_price=float(stop_px), contract_month=front_month(),
                                 bar_time=now.isoformat(), signal_reason=ereason)
            res = exec_mgr.submit_entry(intent, con, stop_tif='DAY')
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


def _exit(dynamo, ib, con, tag, sname, side, pos, reason, exit_px, today, mode,
          risk=None, entry_px=None, exec_mgr=None):
    # Close via the execution manager: cancels the resting stop first (race-free)
    # and verifies the fill. On UNKNOWN (timeout) do NOT record a clean close —
    # leave state intact so reconciliation surfaces the ambiguity.
    action = 'SELL' if side == 'LONG' else 'BUY'
    exit_intent = TradeIntent(scope='live_intraday', tag=tag, symbol='MES', action=action,
                              side=side, qty=pos, order_type='MKT', stop_price=0.0,
                              contract_month=front_month(), bar_time=now_et().isoformat(),
                              signal_reason=reason)
    res = exec_mgr.submit_exit(exit_intent, con, cancel_stop=True)
    if res.status == 'DUPLICATE':
        print(f">>> {mode} {tag} duplicate exit — skip (idempotent)")
        return
    if res.status == 'UNKNOWN':
        print(f">>> {mode} {tag} EXIT UNKNOWN (timeout) — not recording close; "
              f"reconcile will resolve")
        return
    actual_px = res.avg_px if res.avg_px > 0 else exit_px
    if risk is not None and entry_px is not None:
        risk.record_close(realized_pnl(side, entry_px, actual_px, CONTRACT['point_value'], pos))
    log_dynamo(dynamo, f"TRADE#{tag}", now_et().isoformat(), {
        'side': 'EXIT', 'qty': pos, 'exit_px': str(round(actual_px, 2)),
        'reason': reason, 'strategy': sname, 'ts': int(time.time())})
    log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
        'pos': 0, 'side': '', 'stop': '0', 'entry': '0',
        'session_date': today, 'ts': int(time.time())})
    print(f">>> {mode} {tag} EXIT {side} {pos} @ {actual_px:.2f} ({reason})")


# ===== main =====
def main():
    dynamo = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)
    now = now_et()
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

        # persistent risk engine — ONE instance for the whole run, loaded from
        # the ledger so the intraday daily-loss cap / consecutive-loss brake
        # survive the every-15-min process restarts. Fail-closed: an unreadable
        # ledger HALTS the run (no new entries).
        try:
            risk = RiskEngine.load(RiskConfig(risk_budget_usd=INTRA_RISK_BUDGET,
                                              risk_pct=INTRA_RISK_PCT,
                                              max_concurrent_positions=1),
                                   RiskLedger(dynamo, scope='live_intraday'))
        except RiskStateUnavailable as e:
            print(f"[{now.isoformat()}] {mode} HALT — risk state unreadable (fail-closed): {e}")
            return
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

        r = reconcile(ib, dynamo, today_iso=today)
        if not r.ok:
            print(f"CRITICAL {mode} reconcile {r.status}: {r.reason}")
            risk.emergency_halt(f"reconciliation {r.status}: {r.reason}")
            return

        # execution manager — the ONLY component that submits orders to IBKR.
        exec_mgr = ExecutionManager(ib, dynamo, scope='live_intraday')

        for strat in STRATEGIES:
            df = bars[strat['name']]
            min_bars = FADE_BOLL_N + 5 if strat['name'] == 'FADESHORT' else DC_N + 5
            if df.empty or len(df) < min_bars:
                print(f"[{now.isoformat()}] {mode} {strat['name']}: insufficient bars ({len(df)})")
                continue
            run_strategy(ib, dynamo, con, strat, df, now, today, mode, ctrl, risk, exec_mgr)
    finally:
        ib.disconnect()


if __name__ == '__main__':
    main()

