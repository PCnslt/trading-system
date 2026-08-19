"""Session calendar + trading hours (roadmap Phase 4).

Extracts RTH open/close, holidays, and early-close days from the `liquidHours`
(and `tradingHours`) strings captured by bot/futures_contracts.py into
S3 contracts/<sym>/contracts.json — so this runs OFFLINE (no gateway load).

Outputs:
  - DynamoDB  SESSION#<sym> (sk='current')  -> next_open, next_close, is_open,
    regular_open/close, timezone.
  - S3        sessions/<sym>/calendar.json   -> parsed RTH days, holidays,
    early-close days, regular session.

Note: IBKR returns a rolling ~1-week window of session info; re-running this
script (or futures_contracts.py, which refreshes the source) extends it. RTH
here is the CME/CBOT "liquid" session (e.g. 08:30-16:00 ET for ES); the trading
bots' entry window is the narrower 09:30-16:00 ET — documented, not conflated.

READ-ONLY on the trading side: S3 reads + DynamoDB SESSION# writes only.
"""
import os
import re
import sys
import time
import json
import datetime as dt
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

from bot.futures_contracts import SYMBOLS

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
TZ = 'America/New_York'

_ENTRY = re.compile(r'^(\d{8}):(\d{4})-(\d{8}):(\d{4})$')
_CLOSED = re.compile(r'^(\d{8}):CLOSED$')


def parse_liquid(liquid_hours):
    """Parse liquidHours -> {days: [{date, open, close, status}], ...}.

    A same-day `D:T1-D:T2` entry is an RTH (liquid) session on date D.
    A cross-day `D1:T1-D2:T2` entry is an overnight (ETH) bridge — skipped for
    the RTH calendar but kept in `overnight`. `D:CLOSED` is a holiday/weekend.
    """
    days = {}
    overnight = []
    for part in (liquid_hours or '').split(';'):
        part = part.strip()
        if not part:
            continue
        m = _ENTRY.match(part)
        if m:
            d1, t1, d2, t2 = m.groups()
            if d1 == d2:
                days[d1] = {'date': d1, 'open': t1, 'close': t2, 'status': 'open'}
            else:
                overnight.append({'open_date': d1, 'open': t1,
                                  'close_date': d2, 'close': t2})
            continue
        m = _CLOSED.match(part)
        if m:
            days[m.group(1)] = {'date': m.group(1), 'status': 'closed'}
    return days, overnight


def _hm(hhmm):
    return dt.time(int(hhmm[:2]), int(hhmm[2:4]))


def _ymd(s):
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def build_calendar(sym, liquid_hours):
    days, overnight = parse_liquid(liquid_hours)
    day_list = [days[d] for d in sorted(days)]

    open_times = Counter((d['open'], d['close']) for d in day_list if d['status'] == 'open')
    regular = open_times.most_common(1)[0][0] if open_times else (None, None)
    regular_open, regular_close = regular

    holidays = [d['date'] for d in day_list
                if d['status'] == 'closed' and _ymd(d['date']).weekday() < 5]
    early = [d for d in day_list
             if d['status'] == 'open' and regular_close
             and _hm(d['close']) < _hm(regular_close)]

    return {
        'symbol': sym,
        'timezone': TZ,
        'regular_session': {'open': regular_open, 'close': regular_close},
        'window': {'start': day_list[0]['date'], 'end': day_list[-1]['date'],
                   'days': len(day_list)},
        'holidays': holidays,
        'early_close': early,
        'days': day_list,
        'overnight_bridges': overnight,
    }


def session_state(cal):
    """Compute is_open + next open/close (ISO) at the current NY wall-clock."""
    try:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo('America/New_York')).replace(tzinfo=None)
    except Exception:
        off = -4 if (3 < dt.datetime.now().month < 11) else -5
        now = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=off))

    ro, rc = cal['regular_session']['open'], cal['regular_session']['close']
    opens, closes = [], []
    for d in cal['days']:
        if d['status'] != 'open':
            continue
        date = _ymd(d['date'])
        opens.append(dt.datetime.combine(date, _hm(d['open'])))
        closes.append(dt.datetime.combine(date, _hm(d['close'])))

    is_open = any(o <= now < c for o, c in zip(opens, closes))
    next_open = next((t for t in opens if t > now), None)
    next_close = next((t for t in closes if t > now), None)

    return {
        'is_open': is_open,
        'next_open': next_open.isoformat() if next_open else None,
        'next_close': next_close.isoformat() if next_close else None,
        'regular_open': ro, 'regular_close': rc,
        'tz': TZ,
    }


def _load_contracts(s3, sym):
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=f'contracts/{sym}/contracts.json')
        return json.loads(obj['Body'].read())
    except Exception:
        return None


def main():
    s3 = boto3.client('s3', region_name=AWS_REGION)
    dyn = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    n = 0
    for sym, _ in SYMBOLS:
        chain = _load_contracts(s3, sym)
        if not chain:
            print(f"[{sym}] no contracts.json — skip")
            continue
        # liquidHours is symbol-level (same across the chain); use the first
        # contract that carries it (the oldest expiry may have an empty field).
        lh = next((c.get('liquidHours') for c in chain if c.get('liquidHours')), None)
        if not lh:
            print(f"[{sym}] no liquidHours in contracts.json — skip")
            continue
        cal = build_calendar(sym, lh)
        state = session_state(cal)
        # S3 calendar
        s3.put_object(Bucket=S3_BUCKET, Key=f'sessions/{sym}/calendar.json',
                      Body=json.dumps(cal, indent=2))
        # DynamoDB next session state
        dyn.put_item(Item={
            'pk': f'SESSION#{sym}', 'sk': 'current',
            'is_open': state['is_open'],
            'next_open': state['next_open'] or '',
            'next_close': state['next_close'] or '',
            'regular_open': state['regular_open'] or '',
            'regular_close': state['regular_close'] or '',
            'tz': state['tz'],
            'ts': int(time.time()),
        })
        rs = cal['regular_session']
        print(f"[{sym}] RTH {rs['open']}-{rs['close']} ({TZ}), {cal['window']['days']}d window, "
              f"{len(cal['holidays'])} holidays, {len(cal['early_close'])} early-close, "
              f"is_open={state['is_open']}, next_open={state['next_open']}")
        n += 1
    print(f"\nDONE: {n}/{len(SYMBOLS)} session calendars written. Trading side untouched.")


if __name__ == '__main__':
    main()

