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
import sys
import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')


def _now_et() -> dt.datetime:
    return dt.datetime.now(ET)


def _in_rth(now: dt.datetime) -> bool:
    return now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) <= (16, 0)


def _rh_protection_counts():
    """(positions_held, positions_with_a_resting_stop) on the RH LIVE account.

    Robinhood reports a stop as type='market' + trigger='stop' + stop_price, and a
    resting order's state is 'confirmed' (there is no 'open' state) — matching on
    type=='stop_market' finds nothing, which is how naked positions went unnoticed.
    Returns (None, None) if the broker cannot be read, so a token/API problem never
    masquerades as "no naked positions".
    """
    sys.path.insert(0, '/home/ubuntu/trading-system')
    from hardening.rh_client import RHClient
    rh = RHClient()
    acct = rh._resolve_account()
    held = [p for p in rh.get_positions(acct) if float(p.get('quantity') or 0) > 0]
    if not held:
        return 0, 0
    resting = {
        o.get('symbol') for o in rh.list_orders(acct)
        if o.get('side') == 'sell'
        and o.get('stop_price') not in (None, '', '0', '0.000000')
        and (o.get('state') or '').lower() in ('confirmed', 'queued', 'unconfirmed',
                                               'partially_filled')
    }
    return len(held), sum(1 for p in held if p['symbol'] in resting)


def main() -> None:
    now = _now_et()
    if not _in_rth(now):
        return  # silent off-hours

    alerts = []

    # 1. IB Gateway API socket.
    # The PAPER gateway (4002) is intentionally DOWN: IBKR permits one session per
    # username, so the live gateway on 4001 owns it and the paper gw + its watchdog
    # are disabled. Checking 4002 produced a daily false "IB Gateway DOWN" alert
    # while the live gateway was healthy. Check whichever port the bots use, and
    # only alarm if NEITHER is listening.
    gw_port = int(os.getenv('IBKR_PORT', '4001'))
    ports = [gw_port] + [p for p in (4001, 4002) if p != gw_port]
    live_ports = []
    for p in ports:
        try:
            s = socket.create_connection(('127.0.0.1', p), timeout=3)
            s.close()
            live_ports.append(p)
        except Exception:
            pass
    if not live_ports:
        alerts.append(f"IB Gateway DOWN (no API port listening, tried {ports})")
    elif gw_port not in live_ports:
        alerts.append(f"IB Gateway on the CONFIGURED port {gw_port} is down "
                      f"(listening instead: {live_ports})")

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

    # 4. intraday bars archived today (bot liveness).
    # The MES intraday lane runs on the PAPER gateway (4002), which is deliberately
    # disabled while the live gateway owns the single permitted session. Alerting on
    # missing MES bars in that state is a guaranteed daily false alarm about a lane
    # we chose to switch off — so only check it when the paper gateway is actually up.
    if 4002 in live_ports:
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

    # 5. Robinhood LIVE lane: any position without a resting protective stop is the
    # one condition that must never be silent (2026-08-25: 9 filled entries were
    # left naked because the bot could not read its own fills back).
    try:
        rh_open, rh_stopped = _rh_protection_counts()
        if rh_open is not None and rh_open > rh_stopped:
            alerts.append(f"RH NAKED POSITIONS: {rh_open} held, only {rh_stopped} "
                          f"have a resting stop — run bot/emergency_protect_rh_positions.py")
    except Exception:
        pass  # never let a broker read failure mask the other checks

    if alerts:
        print("⚠️ Trading health check FAILED (RTH):")
        for a in alerts:
            print(f"  • {a}")
    # else: empty stdout = silent


if __name__ == '__main__':
    main()
