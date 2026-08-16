"""Reconciliation daemon — periodic broker-vs-DynamoDB reconcile (systemd, 45s).

The fast DETECTOR between bot runs. Own clientId (76) — distinct from
live(70)/bonds(71)/intraday(72)/tick-recorder(74)/daily-collect(75).

Each cycle:
  1. refresh broker truth (reqPositions + reqOpenOrders + reqExecutions),
  2. run the shared reconciler (hardening/reconciler.py),
  3. write RECONCILE/system = {status, reason, positions, ts} to DynamoDB,
  4. on non-MATCH print a CRITICAL line (surfaced to Telegram by the health
     watchdog, which also reads RECONCILE/system and alerts on non-MATCH/stale).

This daemon NEVER places orders and never mutates CONTROL/system. The bots
enforce halting via their OWN startup reconcile (live query, authoritative);
this daemon shortens the detection window from the bot cadence to ~45s.

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


def write_state(table, status, reason, positions=None, unaccounted=None):
    item = {'pk': RECONCILE_PK, 'sk': RECONCILE_SK, 'status': status,
            'reason': reason, 'ts': int(time.time())}
    if positions is not None:
        item['positions'] = json.dumps(positions)
    if unaccounted:
        item['unaccounted_fills'] = json.dumps(unaccounted)
    try:
        table.put_item(Item=item)
    except Exception as e:  # noqa: BLE001
        print(f"reconcile-daemon: failed to write RECONCILE state: {e}")


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
            if r.status == 'MATCH':
                print(f"[{dt.datetime.now(dt.timezone.utc).isoformat()}] reconcile MATCH")
            else:
                print(f"CRITICAL reconcile {r.status}: {r.reason}")
            write_state(table, r.status, r.reason,
                        positions=r.positions, unaccounted=r.unaccounted_fills)
        except Exception as e:  # noqa: BLE001 - any failure -> UNKNOWN, never MATCH
            print(f"CRITICAL reconcile UNKNOWN: {e}")
            write_state(table, 'UNKNOWN', str(e))
        time.sleep(INTERVAL_S)


if __name__ == '__main__':
    main()

