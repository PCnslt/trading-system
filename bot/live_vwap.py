"""Live VWAP intraday sleeve — MES + MNQ paper forward-test (real fills).

Lane 10 RE-ACTIVATION (scoped equity-index sleeve). The volume-filtered
VWAP 2-sigma reversion edge validated OOS PF 1.11–1.38 @1t on the
equity-index group (S&P/Nasdaq/Dow/Russell) — see
`research/LANE10_VWAP_SWEEP.md`. Metals/energy stay permanently excluded
(cross-asset NO-GO). This bot forward-tests the MES/MNQ sleeve with REAL
IBKR paper fills + hard protective stops + a round-trip journal, per the
laptop directive (2026-08-18).

Signal (exact port of `research/lane10_vwap_sweep.py::make_vwap_sweep`):
  - Session-cumulative VWAP on RTH 5-min bars: vwap = Σ(tp·vol)/Σ(vol).
  - z = (close − vwap) / σ(close−vwap), σ = per-day rolling VWAP_SD_N.
  - Enter LONG when z < −VWAP_K; SHORT when z > +VWAP_K.
  - HIGH-VOLUME filter: enter only when current-bar volume ≥ HV_MULT ×
    20-bar rolling mean volume (fade only genuine high-participation
    extensions, not low-volume drift).
  - Exit on reversion to VWAP; 2×ATR hard protective stop; EOD flatten.

Execution: IBKR paper (DUR193467) MES + MNQ, front-month, dynamic roll.
Every entry rests a native-bracket protective stop at fill (never-lose-
money); the reconciler verifies a stop exists on every open position.
Round-trip journal: SIGNAL#/TRADE#/POSITION# keyed per `<sym>_VWAP` tag.
clientId=79 (distinct from live.py 70 / live_intraday 72 / live_gc 78).

Execution mode: `VWAP_EXECUTION` env, default **PAPER** (real paper fills).
Set `VWAP_EXECUTION=NONE` for signal-only. Live money stays off (`LIVE`
env never true here).

Cross-bot safety: stands down on a symbol already held by the daily bot
(live.py) or the intraday bot (live_intraday) to avoid netting the same
contract in the shared paper account.

Schedule: Hermes cron every 15 min during RTH (09:30–16:00 ET weekdays),
like live_intraday. Entries 09:30–15:30 ET; EOD flatten from 15:45 ET.
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
# --- SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb
_sb()

# ===== config =====
IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
CLIENT_ID = 79                                     # distinct from 70/71/72/78
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
VWAP_RISK_BUDGET = float(os.getenv('VWAP_RISK_BUDGET', '25000'))  # intraday sleeve
VWAP_RISK_PCT = 0.01                               # 1% risk/trade MAX (owner 0.5-1%)
LIVE = os.getenv('LIVE', 'false').lower() == 'true'
EXECUTION_MODE = os.getenv('VWAP_EXECUTION', 'PAPER').upper()   # 'PAPER' | 'NONE'

# strategy params (match lane10_vwap_sweep.py / intraday_validate.py)
VWAP_K = float(os.getenv('VWAP_K', '2.0'))
VWAP_SD_N = 10
VWAP_HV_WIN = 20
VWAP_HV_MULT = float(os.getenv('VWAP_HV_MULT', '1.0'))   # high-volume filter multiplier
VWAP_ATR_N = 14
VWAP_STOP_ATR = 2.0    # hard protective stop width (2xATR), sizing proxy == stop

# execution sleeve (micro index contracts; % action == ES/NQ)
SYMBOLS = [
    {'symbol': 'MES', 'exchange': 'CME', 'point_value': 5.0},
    {'symbol': 'MNQ', 'exchange': 'CME', 'point_value': 2.0},
]

DURATION = '2 D'       # full current session VWAP + warmup for rolling std/vol

# session window (America/New_York). RTH 09:30-16:00 ET, DST-aware via zoneinfo.
NY = ZoneInfo('America/New_York')
RTH_OPEN = dt.time(9, 30)
RTH_CLOSE = dt.time(16, 0)
ENTRY_CUTOFF = dt.time(15, 30)   # no new entries in the last 30 min
EOD_FLATTEN = dt.time(15, 45)    # flatten any open position from 15:45 ET

# Other bots that may hold the same symbol in the shared paper account.
# Stand down on overlap (never net the same contract).
OTHER_BOT_TAGS = {
    'MES': ['MES_DONCHIAN', 'MES_RSI2', 'MES_FADESHORT', 'MES_DONCH15'],
    'MNQ': ['MNQ_DONCHIAN', 'MNQ_RSI2'],
}


# ===== indicators =====
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def session_cumsum(s):
    """Cumulative sum reset at each day boundary (for VWAP). Matches intraday_validate."""
    out = s.copy()
    cur = 0.0
    prev_day = None
    for i in range(len(s)):
        d = s.index[i].date()
        if d != prev_day:
            cur = 0.0
            prev_day = d
        v = s.iloc[i]
        cur += (0.0 if pd.isna(v) else v)
        out.iloc[i] = cur
    return out


# ===== strategy detail builder (last-bar values) =====
def vwap_detail(df):
    """Compute VWAP band + high-volume filter state on the last RTH 5-min bar."""
    c = df['Close']
    h, l = df['High'], df['Low']
    tp = (h + l + c) / 3
    vol = df['Volume'].clip(lower=0.0)
    vwap = session_cumsum(tp * vol) / session_cumsum(vol).replace(0, np.nan)
    dev = c - vwap
    sd = dev.groupby(df['date']).rolling(VWAP_SD_N, min_periods=VWAP_SD_N).std().reset_index(level=0, drop=True)
    atr = wilder_atr(h, l, c, VWAP_ATR_N)
    roll_vol = vol.rolling(VWAP_HV_WIN, min_periods=VWAP_HV_WIN).mean()

    v = float(vwap.iloc[-1]) if np.isfinite(vwap.iloc[-1]) else np.nan
    s = float(sd.iloc[-1]) if np.isfinite(sd.iloc[-1]) else np.nan
    a = float(atr.iloc[-1]) if np.isfinite(atr.iloc[-1]) else np.nan
    rv = float(roll_vol.iloc[-1]) if np.isfinite(roll_vol.iloc[-1]) else np.nan
    cv = float(vol.iloc[-1])
    z = (float(c.iloc[-1]) - v) / s if (np.isfinite(v) and np.isfinite(s) and s > 0) else np.nan

    high_vol = None
    if VWAP_HV_MULT > 0 and np.isfinite(rv) and rv > 0:
        high_vol = cv >= VWAP_HV_MULT * rv

    return {
        'close': float(c.iloc[-1]),
        'vwap': v,
        'sd': s,
        'z': z,
        'atr': a,
        'vol': cv,
        'roll_vol': rv,
        'high_vol': high_vol,
    }


# ===== strategy interface =====
def vwap_entry(d):
    if not np.isfinite(d['z']):
        return 0, (f"insufficient history: z=NaN (sd={d['sd']}, vwap={d['vwap']})")
    if VWAP_HV_MULT > 0 and d['high_vol'] is False:
        return 0, (f"low volume: vol {d['vol']:.0f} < {VWAP_HV_MULT}x rolling {d['roll_vol']:.0f}")
    if d['z'] < -VWAP_K:
        return 1, (f"close {d['close']:.1f} < VWAP−{VWAP_K}σ "
                   f"(vwap {d['vwap']:.1f}, z={d['z']:.2f})")
    if d['z'] > VWAP_K:
        return -1, (f"close {d['close']:.1f} > VWAP+{VWAP_K}σ "
                    f"(vwap {d['vwap']:.1f}, z={d['z']:.2f})")
    return 0, (f"z={d['z']:.2f} inside band (±{VWAP_K}σ)")


def vwap_exit(d, side):
    if side == 'LONG' and np.isfinite(d['vwap']) and d['close'] >= d['vwap']:
        return True, f"close {d['close']:.1f} >= VWAP {d['vwap']:.1f} (reversion done)"
    if side == 'SHORT' and np.isfinite(d['vwap']) and d['close'] <= d['vwap']:
        return True, f"close {d['close']:.1f} <= VWAP {d['vwap']:.1f} (reversion done)"
    return False, "hold"


def vwap_stop(d, side):
    # Hard protective stop at 2xATR from entry close (never-lose-money).
    # The sizing distance and the protective stop are the SAME number.
    if not np.isfinite(d['atr']):
        return None
    if side == 'LONG':
        return d['close'] - VWAP_STOP_ATR * d['atr']
    return d['close'] + VWAP_STOP_ATR * d['atr']


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


def _read_state(dynamo, tag, today):
    st = get_state(dynamo, f"POSITION#{tag}", 'current') or {}
    if st.get('session_date') != today:      # stale (previous session) -> flat
        return {}
    return st


def _other_bot_holds(dynamo, sym, today):
    """True if another bot holds `sym` right now (cross-bot stand-down)."""
    for tag in OTHER_BOT_TAGS.get(sym, []):
        st = get_state(dynamo, f"POSITION#{tag}", 'current') or {}
        if int(st.get('pos', 0)) > 0:
            return True, tag
    return False, None


def _archive_bars(sym, df):
    """Persist this run's RTH 5-min bars to S3 (keeps the 5-min archive fresh)."""
    if df is None or df.empty:
        return
    try:
        date = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')  # S3 key date stays UTC
        records = [{'ts': idx.isoformat(), 'open': float(r['Open']),
                    'high': float(r['High']), 'low': float(r['Low']),
                    'close': float(r['Close']), 'volume': float(r['Volume'])}
                   for idx, r in df.iterrows()]
        archive_intraday_bars(sym, '5min', date, records)
        print(f"[{sym}] archived {len(records)} 5min bars -> futures-bars/intraday/{sym}/5min/{date}.json")
    except Exception as e:
        print(f"[{sym}] intraday bars archive failed: {e}")


# ===== per-symbol runner =====
def run_symbol(ib, dynamo, spec, df, now, today, mode, ctrl, risk, exec_mgr):
    sym = spec['symbol']
    tag = f"{sym}_VWAP"
    detail = vwap_detail(df)
    state = _read_state(dynamo, tag, today)
    pos = int(state.get('pos', 0))
    side = state.get('side')                  # 'LONG' / 'SHORT'
    stop = float(state['stop']) if state.get('stop') else None
    entry_px = float(state['entry']) if state.get('entry') else None

    now_t = now.time()
    in_window = RTH_OPEN <= now_t < RTH_CLOSE
    eod = now_t >= EOD_FLATTEN
    entry_allowed = in_window and now_t < ENTRY_CUTOFF

    entry_side, ereason = vwap_entry(detail)

    # skip flat, outside-RTH runs silently (no SIGNAL spam on pre/post-session runs)
    if pos == 0 and not in_window:
        print(f"[{now.isoformat()}] {mode} {tag} flat, outside RTH — skip")
        return

    sig = {
        'signal': 'EXIT' if pos > 0 else ('SHORT' if entry_side == -1
                                          else ('LONG' if entry_side == 1 else 'NONE')),
        'strategy': 'VWAP',
        'close': str(round(detail['close'], 2)),
        'vwap': str(round(detail['vwap'], 2)) if np.isfinite(detail['vwap']) else '',
        'z': str(round(detail['z'], 2)) if np.isfinite(detail['z']) else '',
        'high_vol': str(detail['high_vol']),
        'pos': pos, 'side': side or '', 'reason': ereason,
        'eod': eod, 'session_date': today, 'ts': int(time.time()),
        'execution': EXECUTION_MODE,
    }
    log_dynamo(dynamo, f"SIGNAL#{tag}", now.isoformat(), sig)

    if EXECUTION_MODE != 'PAPER':
        print(f"[{now.isoformat()}] {mode} {tag} SIGNAL-ONLY ({sig['signal']}) {ereason}")
        return

    if pos > 0:
        # open position -> evaluate exit / EOD flatten
        if eod:
            _exit(dynamo, ib, spec, tag, side, pos, 'EOD-flatten',
                  detail['close'], today, mode, risk, entry_px, exec_mgr)
            return
        should_exit, xreason = vwap_exit(detail, side)
        if should_exit:
            _exit(dynamo, ib, spec, tag, side, pos, xreason,
                  detail['close'], today, mode, risk, entry_px, exec_mgr)
        elif not exec_mgr.is_stop_open(sym, side, ref=tag):
            # protective stop no longer resting -> filled intraday
            exit_px = stop if stop is not None else detail['close']
            if risk is not None and entry_px is not None:
                risk.record_close(realized_pnl(side, entry_px, exit_px, spec['point_value'], pos))
            log_dynamo(dynamo, f"TRADE#{tag}", now.isoformat(), {
                'side': 'EXIT', 'qty': pos, 'exit_px': str(stop),
                'reason': 'stop-filled', 'strategy': 'VWAP', 'ts': int(time.time())})
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
            held, held_by = _other_bot_holds(dynamo, sym, today)
            if held:
                print(f"[{today}] {mode} {tag} no entry — {held_by} already holds {sym}")
                return
            allowed, why = risk.can_enter()
            if not allowed:
                print(f">>> {mode} {tag} blocked by risk: {why}")
                return
            nside = 'SHORT' if entry_side == -1 else 'LONG'
            stop_px = vwap_stop(detail, nside)
            if stop_px is None:
                print(f">>> {mode} {tag} no ATR for stop — skip (fail-closed)")
                return
            stop_dist = abs(stop_px - detail['close'])
            size = risk.position_size(stop_dist, point_value=spec['point_value'])
            if size <= 0:
                print(f">>> {mode} {tag} size=0 (stop too wide for budget), skip")
                return
            action = 'SELL' if entry_side == -1 else 'BUY'
            intent = TradeIntent(scope='live_vwap', tag=tag, symbol=sym, action=action,
                                 side=nside, qty=size, order_type='MKT',
                                 stop_price=float(stop_px), contract_month=front_month(),
                                 bar_time=now.isoformat(), signal_reason=ereason)
            res = exec_mgr.submit_entry(intent, spec['con'], stop_tif='DAY')
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
                'strategy': 'VWAP', 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': size, 'side': nside, 'stop': str(round(stop_px, 2)),
                'entry': str(round(entry_px_filled, 2)), 'entry_ts': now.isoformat(),
                'session_date': today, 'contract': front_month(), 'ts': int(time.time())})
            print(f">>> {mode} {tag} ENTRY: {nside} {size} @ {round(entry_px_filled, 2)}, "
                  f"stop {round(stop_px, 1)} ({ereason})")
        else:
            gate = 'EOD' if eod else ('entry-cutoff' if not entry_allowed else 'no-signal')
            print(f"[{today}] {mode} {tag} flat ({gate}): {ereason}")


def _exit(dynamo, ib, spec, tag, side, pos, reason, exit_px, today, mode,
          risk=None, entry_px=None, exec_mgr=None):
    sym = spec['symbol']
    action = 'SELL' if side == 'LONG' else 'BUY'
    exit_intent = TradeIntent(scope='live_vwap', tag=tag, symbol=sym, action=action,
                              side=side, qty=pos, order_type='MKT', stop_price=0.0,
                              contract_month=front_month(), bar_time=now_et().isoformat(),
                              signal_reason=reason)
    res = exec_mgr.submit_exit(exit_intent, spec['con'], cancel_stop=True)
    if res.status == 'DUPLICATE':
        print(f">>> {mode} {tag} duplicate exit — skip (idempotent)")
        return
    if res.status == 'UNKNOWN':
        print(f">>> {mode} {tag} EXIT UNKNOWN (timeout) — not recording close; "
              f"reconcile will resolve")
        return
    actual_px = res.avg_px if res.avg_px > 0 else exit_px
    if risk is not None and entry_px is not None:
        risk.record_close(realized_pnl(side, entry_px, actual_px, spec['point_value'], pos))
    log_dynamo(dynamo, f"TRADE#{tag}", now_et().isoformat(), {
        'side': 'EXIT', 'qty': pos, 'exit_px': str(round(actual_px, 2)),
        'reason': reason, 'strategy': 'VWAP', 'ts': int(time.time())})
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
        # account guard — refuse orders on paper/live mismatch (fail-closed)
        ok, why = account_mode_ok(mode, ib.managedAccounts())
        if not ok:
            print(f"[{now.isoformat()}] {mode} HALT — {why}")
            return

        # control plane — honour kill/pause/flatten BEFORE any order (fail-closed)
        try:
            ctrl = get_control(dynamo)
        except ControlUnavailable as e:
            print(f"[{now.isoformat()}] {mode} HALT — control state unavailable (fail-closed): {e}")
            return
        if control_state(ctrl) is None:
            print(f"[{now.isoformat()}] {mode} HALT — unknown control state (fail-closed)")
            return
        if wants_flatten(ctrl):
            all_tags = [f"{s['symbol']}_VWAP" for s in SYMBOLS]
            flatten_ibkr(ib, [s['symbol'] for s in SYMBOLS], dynamo, all_tags, today, mode)
            ack_flatten(dynamo, 'live_vwap')
            clear_flatten(dynamo)
        if control_state(ctrl) == 'KILLED':
            print(f"[{now.isoformat()}] {mode} KILLED — all trading halted (positions flattened)")
            return

        # persistent risk engine — ONE instance for the whole run (restart-safe).
        try:
            risk = RiskEngine.load(RiskConfig(risk_budget_usd=VWAP_RISK_BUDGET,
                                              risk_pct=VWAP_RISK_PCT,
                                              max_concurrent_positions=len(SYMBOLS)),
                                   RiskLedger(dynamo, scope='live_vwap'))
        except RiskStateUnavailable as e:
            print(f"[{now.isoformat()}] {mode} HALT — risk state unreadable (fail-closed): {e}")
            return
        open_n = 0
        for s in SYMBOLS:
            st = _read_state(dynamo, f"{s['symbol']}_VWAP", today)
            if int(st.get('pos', 0)) > 0:
                open_n += 1
        risk.set_open_positions(open_n)
        risk.touch_data()

        # qualify contracts + load bars
        bars = {}
        for s in SYMBOLS:
            try:
                con = ib.qualifyContracts(Future(s['symbol'], front_month(), s['exchange']))[0]
            except Exception as e:
                print(f"[{now.isoformat()}] {mode} {s['symbol']} contract qualify failed: {e}")
                continue
            s['con'] = con
            df = load_ibkr_bars(ib, con, duration=DURATION, bar_size='5 mins', rth=True)
            df = prep_rth(df) if not df.empty else df
            bars[s['symbol']] = df
            _archive_bars(s['symbol'], df)

        r = reconcile(ib, dynamo, today_iso=today)
        if not r.ok:
            print(f"CRITICAL {mode} reconcile {r.status}: {r.reason}")
            risk.emergency_halt(f"reconciliation {r.status}: {r.reason}")
            return

        # execution manager — the ONLY component that submits orders to IBKR.
        exec_mgr = ExecutionManager(ib, dynamo, scope='live_vwap')

        for s in SYMBOLS:
            df = bars.get(s['symbol'])
            if df is None or df.empty or len(df) < VWAP_SD_N + VWAP_HV_WIN + 5:
                print(f"[{now.isoformat()}] {mode} {s['symbol']}: insufficient bars ({0 if df is None else len(df)})")
                continue
            run_symbol(ib, dynamo, s, df, now, today, mode, ctrl, risk, exec_mgr)
    finally:
        ib.disconnect()


if __name__ == '__main__':
    main()
