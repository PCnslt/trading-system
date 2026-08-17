#!/usr/bin/env python3
"""Trading-system health monitor (invoked by ~/.hermes/scripts/trading_monitor.sh).

Empty stdout = healthy (SILENT). Non-empty stdout = ALERT -> Telegram.

Complements reconcile_watchdog.sh (*/5, RECONCILE only) and ibgw_health.sh
(*/30, gateway only) by also checking:
  * CONTROL/system == RUNNING (catches the auto-pause-on-MISMATCH that leaves
    the system PAUSED even after the gateway recovers), and
  * intraday bars actually archived today (catches a bot silently not running).

Self-gates to RTH (Mon-Fri 09:30-16:00 ET) so off-hours gateway restarts
(daily 04:00, weekly Sunday 2FA) never produce false alarms.
"""
import os
import socket
import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')


def _now_et() -> dt.datetime:
    return dt.datetime.now(ET)


def _in_rth(now: dt.datetime) -> bool:
    return now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) <= (16, 0)


def main() -> None:
    now = _now_et()
    if not _in_rth(now):
        return  # silent off-hours

    alerts = []

    # 1. IB Gateway API socket
    try:
        s = socket.create_connection(('127.0.0.1', 4002), timeout=3)
        s.close()
    except Exception:
        alerts.append("IB Gateway DOWN (port 4002 not listening)")

    # DynamoDB + S3 (boto3 lives in the trading-system venv)
    import boto3
    from dotenv import load_dotenv
    load_dotenv('/home/ubuntu/trading-system/.env')
    region = os.getenv('AWS_REGION', 'us-east-1')
    table_name = os.getenv('DYNAMODB_TABLE', 'trading-data')
    bucket = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

    dyn = boto3.resource('dynamodb', region_name=region)
    t = dyn.Table(table_name)

    try:
        r = t.get_item(Key={'pk': 'RECONCILE', 'sk': 'system'}).get('Item', {})
    except Exception as e:  # noqa: BLE001 - fail toward alert
        r = {'status': 'UNKNOWN', 'reason': f'read failed: {e}'}

    try:
        c = t.get_item(Key={'pk': 'CONTROL', 'sk': 'system'}).get('Item', {})
    except Exception as e:  # noqa: BLE001
        c = {'state': 'UNKNOWN'}

    # 2. reconcile must be MATCH
    if r.get('status') != 'MATCH':
        alerts.append(f"RECONCILE {r.get('status')}: {str(r.get('reason', ''))[:90]}")

    # 3. control must be RUNNING
    if c.get('state') != 'RUNNING':
        alerts.append(f"CONTROL {c.get('state')} (flatten={c.get('flatten', '?')})")

    # 4. intraday bars archived today (bot liveness)
    try:
        s3 = boto3.client('s3', region_name=region)
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        rr = s3.list_objects_v2(Bucket=bucket,
                                Prefix=f'futures-bars/intraday/MES/5min/{today}',
                                MaxKeys=1)
        if not rr.get('Contents'):
            alerts.append("no intraday MES bars archived today (bot not running?)")
    except Exception:
        pass  # best-effort; never false-alarm on an S3 blip

    if alerts:
        print("⚠️ Trading health check FAILED (RTH):")
        for a in alerts:
            print(f"  • {a}")
    # else: empty stdout = silent


if __name__ == '__main__':
    main()
