"""Read-only paper status report for the daily summary cron (23:45 UTC).

Prints a concise, plain-text report from DynamoDB (table trading-data):

  1. OPEN POSITIONS — every POSITION#* row with pos > 0 (daily + intraday).
  2. INTRADAY (today) — latest signal + today's trades for MES_FADESHORT /
     MES_DONCH15 (the intraday lane).
  3. DATA HEALTH — freshness of the three data paths: IBKR intraday bars,
     equity daily ingest (OHLCV#*), crypto ticker (QUOTE#*).

Read-only; never places orders. Safe to run any time.
"""
import os
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
        else:
            lines.append(f'  {tag}: no signal yet (bot not run today)')
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
    # IBKR intraday bars (fresh = the 15-min bot ran with live bars)
    fs = _latest('SIGNAL#MES_FADESHORT')
    lines.append(f"  IBKR intraday bars: {'ok' if fs and '_err' not in fs else 'stale'} "
                 f"(last {_age_str(fs.get('ts')) if fs and '_err' not in fs else '—'} ago)")
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
