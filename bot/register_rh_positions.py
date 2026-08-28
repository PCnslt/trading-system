#!/usr/bin/env python3
"""Register today's 9 recovered LIVE positions in the RH lane's book (RHPOS#).

bot/emergency_protect_rh_positions.py wrote POSITION#live_equities:<SYM> — the
IBKR lane's key format. bot/live_equities.py::load_book scans **RHPOS#<SYM>**,
so the RH lane could not see these positions at all: it would never manage their
exits (stop / time / revert) and could re-buy the same names tomorrow as if flat.

This writes the RHPOS#<SYM> sk='current' rows in exactly the shape the lane
expects (status OPEN, entry_date, entry_price, stop_price, size_usd, size_shares,
atr) using the REAL broker fill prices and the stop actually resting at RH, and
removes the mis-keyed POSITION# rows.

entry_date is set to the last CLOSED session (the bar the lane reasons on), so
the MAX_HOLD=5 time-stop clock starts correctly.
"""
import os, sys, time, json
import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
from hardening.rh_client import RHClient

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
SCOPE = 'live_equities'
DRY = os.getenv('DRY', '0') == '1'
RESTING = ('confirmed', 'queued', 'unconfirmed', 'partially_filled')


def _s(v):
    return str(round(float(v), 6))


def main():
    rh = RHClient()
    acct = rh._resolve_account()
    table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)

    # last CLOSED session date (the bar the lane reasons on)
    now = dt.datetime.now(NY)
    d = now.date() if now.hour >= 16 else now.date() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    entry_date = d.isoformat()

    positions = [p for p in rh.get_positions(acct) if float(p.get('quantity') or 0) > 0]
    orders = rh.list_orders(acct)
    stops = {}
    for o in orders:
        if (o.get('side') == 'sell'
                and o.get('stop_price') not in (None, '', '0', '0.000000')
                and (o.get('state') or '').lower() in RESTING):
            stops[o['symbol']] = float(o['stop_price'])

    print(f'entry_date (last closed session) = {entry_date}')
    print(f'{"sym":7}{"qty":>5}{"entry":>9}{"stop":>9}{"size$":>9}  action')
    n = 0
    for p in sorted(positions, key=lambda x: x['symbol']):
        sym = p['symbol']
        qty = float(p['quantity'])
        entry = float(p.get('average_buy_price') or p.get('average_price') or 0)
        if entry <= 0:
            # RH cost-basis fields can be None — never write entry_price=0 (breaks the
            # sell-monitor's stop calc). Resolve from the newest BUY fill order.
            for o in rh.list_orders(acct) or []:
                if (o.get('side') == 'buy' and (o.get('symbol') or '') == sym
                        and o.get('average_price')):
                    entry = float(o['average_price'])
                    break
        if entry <= 0:
            print(f'{sym:7}{qty:>5.0f}{"??":>9}{"NONE":>9}{"":>9}  SKIP (cost-basis unknown)')
            continue
        stop = stops.get(sym)
        if not stop:
            print(f'{sym:7}{qty:>5.0f}{entry:>9.2f}{"NONE":>9}{"":>9}  SKIP (no resting stop!)')
            continue
        atr = (entry - stop) / 2.0          # stop was set at entry - 2*ATR
        item = {
            'pk': f'RHPOS#{sym}', 'sk': 'current',
            'status': 'OPEN', 'entry_date': entry_date,
            'entry_price': _s(entry), 'stop_price': _s(stop),
            'size_usd': _s(qty * entry), 'size_shares': _s(qty),
            'atr': _s(atr), 'side': 'LONG',
            'source': 'register_rh_positions.py (recovered 2026-08-25)',
            'ts': int(time.time()),
        }
        if DRY:
            print(f'{sym:7}{qty:>5.0f}{entry:>9.2f}{stop:>9.2f}{qty*entry:>9.2f}  [dry] would write RHPOS#{sym}')
            continue
        table.put_item(Item=item)
        # drop the mis-keyed IBKR-format row so there is ONE source of truth
        try:
            table.delete_item(Key={'pk': f'POSITION#{SCOPE}:{sym}', 'sk': 'current'})
        except Exception as e:
            print(f'   (warn) could not delete POSITION#{SCOPE}:{sym}: {e!r}')
        n += 1
        print(f'{sym:7}{qty:>5.0f}{entry:>9.2f}{stop:>9.2f}{qty*entry:>9.2f}  wrote RHPOS#{sym}')

    print(f'\n{n} RHPOS# rows written')
    if not DRY:
        # verify the lane can now see them
        sys.path.insert(0, _ROOT)
        from bot.live_equities import load_book
        book = load_book(table, False)
        held = sorted(p['symbol'] for p in positions)
        seen = sorted(book)
        print(f'load_book() now sees {len(seen)}: {seen}')
        missing = [s for s in held if s not in seen]
        print(f'*** NOT IN BOOK: {missing} ***' if missing else '*** ALL POSITIONS IN THE LANE BOOK ***')


if __name__ == '__main__':
    main()
