"""Read-only paper status report for the daily summary cron (23:45 UTC).

Prints a concise, plain-text report from DynamoDB (table trading-data):

  1. OPEN POSITIONS — every POSITION#* row with pos > 0 (daily + intraday).
  2. INTRADAY (today) — latest signal + today's trades for MES_FADESHORT /
     MES_DONCH15 (the intraday lane).
  3. DATA HEALTH — freshness of the three data paths: IBKR intraday bars,
     equity daily ingest (OHLCV#*), crypto ticker (QUOTE#*).

Read-only; never places orders. Safe to run any time.

Ground-truth rule (see trading-bot-operations skill): "ran today" and "bars
fresh" MUST key on the latest S3 `futures-bars/intraday/…` archived-bar date
and/or the RUN# marker — NEVER on SIGNAL#/TRADE# presence. A flat session
(fresh bars, no signal) is HEALTHY, not "didn't run" / "stale".
"""
import os
import re
import datetime as dt

import boto3
from dotenv import load_dotenv

load_dotenv()

DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

INTRA_TAGS = ['MES_FADESHORT', 'MES_DONCH15']
# strategy tag -> implied side when a POSITION row stores no explicit 'side'
IMPLIED_SIDE = {
    'MES_DONCHIAN': 'LONG', 'MES_RSI2': 'LONG',
    'ZB_RSI2SHORT': 'SHORT', 'ZN_RSI2SHORT': 'SHORT',
    'ZB_BBANDSHORT': 'SHORT', 'ZN_BBANDSHORT': 'SHORT',
    'MES_FADESHORT': 'SHORT',
}

table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)

# ---- ground-truth data sources (NEVER key liveness/freshness on SIGNAL#/TRADE#) ----
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
INTRADAY_S3_PREFIX = 'futures-bars/intraday/MES/'   # the intraday lane's archived bars
INTRADAY_RUN_KEY = 'live_intraday'                   # RUN#<key>/<today> marker
BAR_STALE_DAYS = 3   # >3 calendar days behind = pipeline stopped (weekend+holiday safe)

_s3 = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client('s3', region_name=AWS_REGION)
    return _s3


def _date_from_bar_key(key):
    """'futures-bars/intraday/MES/15min/2026-08-14.json' -> '2026-08-14'."""
    m = re.search(r'/(\d{4}-\d{2}-\d{2})\.json$', key or '')
    return m.group(1) if m else None


def _latest_intraday_bar_date(prefix=INTRADAY_S3_PREFIX, client=None):
    """Most recent session date among archived intraday bars, read from the key's
    `<date>.json` (the BAR's date — NOT S3 LastModified, which a backfill resets).

    Ground truth for 'did the intraday bot archive bars for a given session'.
    Returns None on S3 error or no objects."""
    client = client or _s3_client()
    latest = None
    try:
        token = None
        while True:
            kw = dict(Bucket=S3_BUCKET, Prefix=prefix)
            if token:
                kw['ContinuationToken'] = token
            resp = client.list_objects_v2(**kw)
            for obj in resp.get('Contents', []):
                d = _date_from_bar_key(obj.get('Key'))
                if d and (latest is None or d > latest):
                    latest = d
            if resp.get('IsTruncated'):
                token = resp.get('NextContinuationToken')
            else:
                break
    except Exception:
        pass
    return latest


def _intraday_ran_today(today, tbl=None, latest_bar_date=None):
    """Ground truth for 'did the intraday bot run today': a MES intraday bar
    archive dated today OR the RUN#live_intraday marker. Never SIGNAL# presence."""
    if latest_bar_date == today:
        return True
    t = tbl if tbl is not None else table
    try:
        if t.get_item(Key={'pk': f'RUN#{INTRADAY_RUN_KEY}', 'sk': today}).get('Item'):
            return True
    except Exception:
        pass
    return False


def _intraday_bars_status(latest_date, today):
    """(status, note) for the intraday lane's bar freshness, keyed on the latest
    archived-bar session date (ground truth), never on SIGNAL# presence.
    'ok' = fresh OR market-closed within the weekend/holiday window (<= BAR_STALE_DAYS);
    'stale' = archive older than that (pipeline actually stopped)."""
    if latest_date is None:
        return 'stale', 'no MES intraday archive — check pipeline'
    try:
        age_days = (dt.date.fromisoformat(today) - dt.date.fromisoformat(latest_date)).days
    except ValueError:
        return 'stale', f'last {latest_date} (unparseable date)'
    if age_days == 0:
        return 'ok', f'archived {latest_date}'
    if age_days <= BAR_STALE_DAYS:
        return 'ok', f'last {latest_date} ({age_days}d, market closed/quiet)'
    return 'stale', f'last {latest_date} ({age_days}d ago — check pipeline)'


def _f(v):
    """Decimal/float -> float (None-safe)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _latest(pk, sk_prefix=None):
    """Latest item for pk, optionally with sk starts-with prefix (ScanIndexForward=False)."""
    try:
        if sk_prefix:
            resp = table.query(
                KeyConditionExpression='pk = :pk AND begins_with(sk, :p)',
                ExpressionAttributeValues={':pk': pk, ':p': sk_prefix},
                ScanIndexForward=False, Limit=1)
        else:
            resp = table.query(
                KeyConditionExpression='pk = :pk',
                ExpressionAttributeValues={':pk': pk},
                ScanIndexForward=False, Limit=1)
        items = resp.get('Items', [])
        return items[0] if items else None
    except Exception as e:
        return {'_err': str(e)}


def _now_utc():
    return dt.datetime.now(dt.timezone.utc)


def _age_str(ts_epoch):
    """Human age of an epoch-ts item; '—' if missing."""
    if ts_epoch is None:
        return '—'
    try:
        age = _now_utc().timestamp() - float(ts_epoch)
    except (TypeError, ValueError):
        return '—'
    if age < 0:
        return 'future'
    m = int(age // 60)
    if m < 60:
        return f'{m}m'
    h = m // 60
    if h < 48:
        return f'{h}h{m % 60:02d}m'
    return f'{h // 24}d'


def _sk_time(it):
    """HH:MM:SS from a TRADE item. sk is ISO for intraday bots and 'date#epoch'
    for daily bots; prefer the explicit `ts` epoch, fall back to parsing sk."""
    ts = it.get('ts')
    if ts:
        try:
            return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime('%H:%M:%S')
        except (ValueError, OSError, OverflowError):
            pass
    sk = it.get('sk', '')
    if '#' in sk:
        try:
            return dt.datetime.fromtimestamp(int(sk.split('#', 1)[1]),
                                             dt.timezone.utc).strftime('%H:%M:%S')
        except (ValueError, OSError, OverflowError):
            pass
    try:
        t = sk[11:19]
        return t if t else '--:--:--'
    except (IndexError, TypeError):
        return '--:--:--'


def _side_of(tag, state):
    return state.get('side') or IMPLIED_SIDE.get(tag, '?')


# ===== 1. open positions =====
def report_positions():
    lines = []
    try:
        resp = table.scan(
            FilterExpression='begins_with(pk, :p)',
            ExpressionAttributeValues={':p': 'POSITION#'})
    except Exception as e:
        return [f'  (scan error: {e})']
    open_rows = []
    for it in resp.get('Items', []):
        if int(it.get('pos', 0)) > 0:
            tag = it['pk'].split('#', 1)[1]
            open_rows.append((tag, it))
    if not open_rows:
        lines.append('  none (all flat)')
        return lines
    for tag, it in sorted(open_rows):
        side = _side_of(tag, it)
        entry = it.get('entry')
        stop = it.get('stop')
        lines.append(f"  {tag}: {side} {it['pos']} @ {entry} (stop {stop})")
    return lines


# ===== 2. intraday (today) =====
def report_intraday():
    lines = []
    today = _now_utc().date().isoformat()
    latest_bar = _latest_intraday_bar_date()
    ran_today = _intraday_ran_today(today, latest_bar_date=latest_bar)
    for tag in INTRA_TAGS:
        sig = _latest(f'SIGNAL#{tag}')
        pos_it = _latest(f'POSITION#{tag}')
        if pos_it is None or str(pos_it.get('session_date', '')) != today:
            pos = 0
            side = ''
        else:
            pos = int(pos_it.get('pos', 0))
            side = pos_it.get('side', '')
        if sig and '_err' not in sig:
            lines.append(
                f"  {tag}: signal={sig.get('signal')} close={sig.get('close')} "
                f"pos={pos}{'/' + side if side else ''} "
                f"({_age_str(sig.get('ts'))} ago)")
        elif ran_today:
            lines.append(f'  {tag}: no signal (bot ran today — flat)')
        else:
            lines.append(f'  {tag}: no signal (no bar archive today — last {latest_bar or "—"})')
        # today's trades
        trades = []
        try:
            resp = table.query(
                KeyConditionExpression='pk = :pk AND begins_with(sk, :p)',
                ExpressionAttributeValues={':pk': f'TRADE#{tag}', ':p': today})
            trades = resp.get('Items', [])
        except Exception:
            pass
        if trades:
            for t in sorted(trades, key=lambda x: x['sk']):
                side_, qty, px = t.get('side'), t.get('qty'), t.get('entry') or t.get('exit_px')
                reason = t.get('reason', '')
                lines.append(f"    {_sk_time(t)} {side_} {qty} @ {px} ({reason})")
    return lines


# ===== 3. data health =====
def report_health():
    lines = []
    today = _now_utc().date().isoformat()
    # IBKR intraday bars — keyed on the latest S3 archived-bar session date
    # (ground truth), NOT SIGNAL# presence: fresh bars + no signal = healthy.
    latest_date = _latest_intraday_bar_date()
    status, note = _intraday_bars_status(latest_date, today)
    lines.append(f'  IBKR intraday bars: {status} ({note})')
    # equity daily ingest
    ohlcv = _latest('OHLCV#AAPL')
    if ohlcv and '_err' not in ohlcv:
        lines.append(f"  equity ingest: last OHLCV#AAPL {ohlcv.get('sk')} ({_age_str(ohlcv.get('ts'))} ago)")
    else:
        lines.append('  equity ingest: no data')
    # crypto ticker
    q = _latest('QUOTE#BTCUSDT')
    if q and '_err' not in q:
        lines.append(f"  crypto ticker: last QUOTE#BTCUSDT ({_age_str(q.get('ts'))} ago)")
    else:
        lines.append('  crypto ticker: no data')
    # broker reconciliation (RECONCILE/system written by the reconcile daemon)
    try:
        rec = table.get_item(Key={'pk': 'RECONCILE', 'sk': 'system'}).get('Item')
    except Exception:
        rec = None
    if rec:
        st = rec.get('status', '?')
        flag = 'ok' if st == 'MATCH' else f'⚠ {st}'
        lines.append(f"  broker reconcile: {flag} ({_age_str(rec.get('ts'))} ago) — {rec.get('reason', '')}")
    else:
        lines.append('  broker reconcile: no state yet')
    return lines


def main():
    print('OPEN PAPER POSITIONS:')
    for l in report_positions():
        print(l)
    print('INTRADAY (today):')
    for l in report_intraday():
        print(l)
    print('DATA HEALTH:')
    for l in report_health():
        print(l)


if __name__ == '__main__':
    main()
