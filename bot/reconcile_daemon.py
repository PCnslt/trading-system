"""Reconciliation daemon — periodic broker-vs-DynamoDB reconcile (systemd, 45s).

The fast DETECTOR between bot runs. Own clientId (76) — distinct from
live(70)/bonds(71)/intraday(72)/tick-recorder(74)/daily-collect(75).

Each cycle:
  1. refresh broker truth (reqPositions + reqOpenOrders + reqExecutions),
  2. run the shared reconciler (hardening/reconciler.py),
  3. write RECONCILE/system = {status, reason, positions, ts, mismatch_streak},
  4. on a SUSTAINED MISMATCH (MISMATCH_PAUSE_THRESHOLD consecutive cycles,
     ~90s) flip CONTROL/system -> PAUSED (never KILLED — existing positions
     stay managed to exit). A transient UNKNOWN (gateway blip) never pauses.

This daemon NEVER places orders. It MAY mutate CONTROL/system (PAUSED only) on
sustained MISMATCH — the close-the-unprotected-window fix (GAP-1). The bots
enforce halting via their OWN startup reconcile (live query, authoritative);
this daemon shortens the detection window from the bot cadence to ~45s and now
also closes the gap between detection and the next bot run (up to 15min
intraday / 24h daily) by auto-pausing on a sustained MISMATCH.

Fail-closed: an unreachable gateway or failed broker query is written as
UNKNOWN — never MATCH, never "assume flat".
"""
import json
import os
import sys
import time
import datetime as dt

import boto3
from dotenv import load_dotenv
from ib_insync import IB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hardening.reconciler import reconcile
from control import set_control

load_dotenv()
# --- SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb
_sb()

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
CLIENT_ID = 76
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
INTERVAL_S = 45

RECONCILE_PK = 'RECONCILE'
RECONCILE_SK = 'system'

# GAP-1: auto-pause on SUSTAINED MISMATCH. The reconciler flags a missing/orphaned
# stop within ~45s, but the next bot run may be 15min (intraday) / 24h (daily)
# away — an unprotected position must not sit that long. After
# MISMATCH_PAUSE_THRESHOLD consecutive MISMATCH cycles (~90s), flip
# CONTROL/system -> PAUSED (NOT KILLED: existing positions are still managed to
# exit). A transient UNKNOWN (gateway blip) must NEVER halt the system.
MISMATCH_PAUSE_THRESHOLD = 2


def evaluate_auto_pause(current_status, streak):
    """Return (new_streak, should_pause) for one reconcile cycle.

    MATCH    -> reset streak to 0; never pause.
    MISMATCH -> increment streak; pause once it reaches the threshold.
    UNKNOWN  -> streak unchanged; NEVER pause (a gateway blip must not halt the
                system — UNKNOWN neither advances nor resets the MISMATCH
                streak; only a verified MATCH clears it).
    """
    if current_status == 'MISMATCH':
        s = streak + 1
        return s, s >= MISMATCH_PAUSE_THRESHOLD
    if current_status == 'MATCH':
        return 0, False
    return streak, False


def write_state(table, status, reason, positions=None, unaccounted=None,
                mismatch_streak=None):
    item = {'pk': RECONCILE_PK, 'sk': RECONCILE_SK, 'status': status,
            'reason': reason, 'ts': int(time.time())}
    if positions is not None:
        item['positions'] = json.dumps(positions)
    if unaccounted:
        item['unaccounted_fills'] = json.dumps(unaccounted)
    if mismatch_streak is not None:
        item['mismatch_streak'] = mismatch_streak
    try:
        table.put_item(Item=item)
    except Exception as e:  # noqa: BLE001
        print(f"reconcile-daemon: failed to write RECONCILE state: {e}")


def _read_streak(table):
    """Last persisted MISMATCH streak (survives daemon restarts)."""
    try:
        item = table.get_item(Key={'pk': RECONCILE_PK, 'sk': RECONCILE_SK}).get('Item') or {}
        return int(item.get('mismatch_streak', 0) or 0)
    except Exception:  # noqa: BLE001 — fail safe: a restart mid-stream just delays pause ~90s
        return 0


def _pause_system(table):
    """Flip CONTROL/system -> PAUSED (idempotent; NEVER KILLED)."""
    try:
        item = table.get_item(Key={'pk': 'CONTROL', 'sk': 'system'}).get('Item') or {}
    except Exception:  # noqa: BLE001
        item = {}
    if item.get('state') == 'PAUSED':
        return
    set_control(table, state='PAUSED',
                auto_pause_reason='sustained reconcile MISMATCH '
                                 f'({MISMATCH_PAUSE_THRESHOLD} consecutive 45s cycles)')
    print(f"CRITICAL reconcile: sustained MISMATCH -> CONTROL PAUSED "
          f"(existing positions still managed to exit)")


def refresh(ib):
    ib.reqPositions()
    ib.reqOpenOrders()
    try:
        ib.reqExecutions()
    except Exception:  # noqa: BLE001 - executions optional; positions/orders gate
        pass
    ib.sleep(1.5)


def main():
    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    ib = IB()
    while True:
        try:
            if not ib.isConnected():
                ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=10)
            refresh(ib)
            r = reconcile(ib, table)
            streak = _read_streak(table)
            new_streak, should_pause = evaluate_auto_pause(r.status, streak)
            if r.status == 'MATCH':
                print(f"[{dt.datetime.now(dt.timezone.utc).isoformat()}] reconcile MATCH")
            else:
                print(f"CRITICAL reconcile {r.status}: {r.reason}")
            if should_pause:
                _pause_system(table)
            write_state(table, r.status, r.reason,
                        positions=r.positions, unaccounted=r.unaccounted_fills,
                        mismatch_streak=new_streak)
        except Exception as e:  # noqa: BLE001 - any failure -> UNKNOWN, never MATCH
            print(f"CRITICAL reconcile UNKNOWN: {e}")
            # UNKNOWN is neutral: keep the streak unchanged, never pause.
            streak = _read_streak(table)
            write_state(table, 'UNKNOWN', str(e), mismatch_streak=streak)
        time.sleep(INTERVAL_S)


if __name__ == '__main__':
    main()
