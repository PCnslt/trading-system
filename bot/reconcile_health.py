"""Reconcile watchdog — read-only. Empty stdout = healthy (silent), non-empty = alert.

Reads RECONCILE/system (written by bot/reconcile_daemon.py) and prints an alert
line when the broker-vs-internal reconciliation is NOT healthy:
  - state missing (daemon never wrote / not running), or
  - status != MATCH, or
  - state is stale (daemon stopped updating).

Deployed as a Hermes cron `no_agent` script job (deliver=telegram) so the alert
reaches the group. Keeps stdout empty on MATCH+fresh to stay silent.
"""
import os
import sys
import time

import boto3
from dotenv import load_dotenv

load_dotenv()

TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
REGION = os.getenv('AWS_REGION', 'us-east-1')
STALE_S = int(os.getenv('RECONCILE_STALE_S', '120'))

table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)

try:
    rec = table.get_item(Key={'pk': 'RECONCILE', 'sk': 'system'}).get('Item')
except Exception as e:  # noqa: BLE001
    print(f"🚨 reconcile watchdog: cannot read RECONCILE state: {e}")
    sys.exit(0)

if not rec:
    print("🚨 reconcile watchdog: RECONCILE state missing (daemon not running?)")
    sys.exit(0)

status = rec.get('status', '?')
age = int(time.time()) - int(rec.get('ts', 0))
if status != 'MATCH':
    print(f"🚨 reconcile watchdog: status={status} — {rec.get('reason', '')} ({age}s ago)")
elif age > STALE_S:
    print(f"🚨 reconcile watchdog: reconcile state STALE ({age}s old) — daemon may be down")
# else: MATCH + fresh -> silent (healthy)
