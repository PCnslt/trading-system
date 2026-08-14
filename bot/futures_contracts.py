"""Contract resolver — full futures chain + rollover schedule (roadmap Phase 4).

READ-ONLY on the trading side: reqContractDetails only (no orders, no account
writes). Two intentional side effects, both safe:
  1) DynamoDB  CONTRACT#<sym>  (sk='active') — current active contract for bots.
  2) S3        contracts/<sym>/contracts.json + rollover.json — cold metadata.

Symbols: CME index (ES/NQ/MES/MNQ/RTY/YM) + CBOT rates (ZB/ZN/ZF/ZT/UB/TN).
Rollover: quarterly Mar/Jun/Sep/Dec. `rollover_date = expiry - ROLL_DAYS` is a
documented CONVENTION (not broker-observed OI roll) — the ACTIVE front is the
exact nearest expiry from the chain, so trading resolution stays exact.
"""
import os
import sys
import time
import calendar
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from dotenv import load_dotenv
from ib_insync import IB, Future

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
CLIENT_ID = 73          # distinct from live.py(70) / bonds(71) / intraday(72) / backfill agent(90)

ROLL_DAYS = 8           # roll N days before expiry (documented convention)
YEARS_BACK = 3          # schedule depth back (matches IBKR daily-bar depth)
YEARS_FWD = 5           # schedule depth forward

SYMBOLS = [
    ('ES', 'CME'), ('NQ', 'CME'), ('MES', 'CME'), ('MNQ', 'CME'),
    ('RTY', 'CME'), ('YM', 'CBOT'),
    ('ZB', 'CBOT'), ('ZN', 'CBOT'), ('ZF', 'CBOT'), ('ZT', 'CBOT'),
    ('UB', 'CBOT'), ('TN', 'CBOT'),
]


def front_month(now=None):
    """Front-month contract month (YYYYMM), quarterly Mar/Jun/Sep/Dec."""
    now = now or dt.date.today()
    for m in (3, 6, 9, 12):
        if now.month <= m:
            return f"{now.year}{m:02d}"
    return f"{now.year + 1}03"


def _expiry_date(ymd):
    return dt.datetime.strptime(ymd, '%Y%m%d').date()


def _roll_date(expiry):
    return (expiry - dt.timedelta(days=ROLL_DAYS))


def third_friday(year, month):
    """3rd Friday of a month (equity-index futures expiry convention)."""
    fridays = [w[calendar.FRIDAY] for w in calendar.monthcalendar(year, month)
               if w[calendar.FRIDAY] != 0]
    return dt.date(year, month, fridays[2])


def _month_end(year, month):
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def _approx_expiry(sym, year, month):
    """Approximate expiry date for a quarterly futures month (derived fallback)."""
    if sym in ('ES', 'NQ', 'MES', 'MNQ', 'RTY', 'YM'):
        return third_friday(year, month)
    return _month_end(year, month)   # rates (ZB/ZN/ZF/ZT/UB/TN) ~ month-end


def _quarterly_months(start, end):
    out = []
    for y in range(start.year, end.year + 1):
        for m in (3, 6, 9, 12):
            d = _month_end(y, m)
            if start <= d <= end:
                out.append((y, m))
    return out


def fetch_chain(ib, sym, exchange):
    """Full ACTIVE chain for a symbol via reqContractDetails (sorted by expiry)."""
    cd = ib.reqContractDetails(Future(sym, exchange=exchange))
    if not cd:
        alt = 'CME' if exchange == 'CBOT' else 'CBOT'
        cd = ib.reqContractDetails(Future(sym, exchange=alt))
        if cd:
            exchange = alt
    rows = []
    for c in cd:
        con = c.contract
        rows.append({
            'conId': con.conId,
            'symbol': con.symbol,
            'expiry': con.lastTradeDateOrContractMonth,
            'multiplier': con.multiplier,
            'exchange': con.exchange,
            'currency': con.currency,
            'tradingClass': con.tradingClass,
            'minTick': c.minTick,
            'tradingHours': c.tradingHours,
            'liquidHours': c.liquidHours,
            'marketName': c.marketName,
        })
    rows.sort(key=lambda r: r['expiry'])
    return rows, exchange


def rollover_schedule(sym, exchange, chain, today=None):
    """Rollover schedule: active chain expiries (exact) + derived quarterly cycle."""
    today = today or dt.date.today()
    today_ymd = today.strftime('%Y%m%d')
    by_expiry = {r['expiry']: r for r in chain}

    # active front = nearest expiry >= today
    active = None
    for r in chain:
        if r['expiry'] >= today_ymd:
            active = r
            break

    schedule = []
    start = dt.date(today.year - YEARS_BACK, 1, 1)
    end = dt.date(today.year + YEARS_FWD, 12, 31)
    for (y, m) in _quarterly_months(start, end):
        approx = _approx_expiry(sym, y, m)
        ymd = approx.strftime('%Y%m%d')
        exact = by_expiry.get(ymd)           # chain has the exact date
        expiry = exact['expiry'] if exact else ymd
        source = 'chain' if exact else 'derived'
        schedule.append({
            'expiry': expiry,
            'conId': exact['conId'] if exact else None,
            'rollover_date': _roll_date(_expiry_date(expiry)).isoformat(),
            'source': source,
            'front': bool(active and expiry == active['expiry']),
        })

    return {
        'symbol': sym,
        'exchange': exchange,
        'roll_convention': f'quarterly Mar/Jun/Sep/Dec; rollover_date = expiry - {ROLL_DAYS}d (convention)',
        'active': active,
        'schedule': schedule,
    }


def build_all(ib):
    """Fetch chains + schedules for every symbol. Returns {sym: {chain, schedule, exchange}}."""
    out = {}
    for sym, exchange in SYMBOLS:
        try:
            chain, exchange = fetch_chain(ib, sym, exchange)
            if not chain:
                print(f"[{sym}] EMPTY chain — skipping")
                continue
            sched = rollover_schedule(sym, exchange, chain)
            out[sym] = {'chain': chain, 'schedule': sched, 'exchange': exchange}
            a = sched['active']
            print(f"[{sym}] {len(chain)} contracts, active {a['expiry']} "
                  f"(conId={a['conId']}, mult={a['multiplier']}, {a['tradingClass']})")
        except Exception as e:
            print(f"[{sym}] FAILED: {e!r}")
        time.sleep(1)
    return out


def write_contracts(data):
    """DynamoDB CONTRACT#<sym> + S3 contracts/<sym>/{contracts,rollover}.json."""
    dyn = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    s3 = boto3.client('s3', region_name=AWS_REGION)
    import json
    for sym, d in data.items():
        a = d['schedule']['active']
        roll_date = _roll_date(_expiry_date(a['expiry'])).isoformat()
        # DynamoDB active contract (hot)
        dyn.put_item(Item={
            'pk': f'CONTRACT#{sym}', 'sk': 'active',
            'conId': int(a['conId']), 'expiry': a['expiry'],
            'multiplier': a['multiplier'], 'exchange': d['exchange'],
            'currency': a['currency'], 'tradingClass': a['tradingClass'],
            'minTick': str(a['minTick']),
            'rollover_date': roll_date,
            'ts': int(time.time()),
        })
        # S3 cold metadata
        s3.put_object(Bucket=S3_BUCKET, Key=f'contracts/{sym}/contracts.json',
                      Body=json.dumps(d['chain'], indent=2))
        s3.put_object(Bucket=S3_BUCKET, Key=f'contracts/{sym}/rollover.json',
                      Body=json.dumps(d['schedule'], indent=2, default=str))
        print(f"[{sym}] CONTRACT# + contracts/{sym}/{{contracts,rollover}}.json written")
    return len(data)


def main():
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=15, readonly=True)
        print(f"connected clientId={CLIENT_ID} accounts={ib.managedAccounts()} (READ-ONLY)")
        data = build_all(ib)
        n = write_contracts(data)
        print(f"\nDONE: {n}/{len(SYMBOLS)} symbols resolved. Trading side untouched.")
    finally:
        ib.disconnect()


if __name__ == '__main__':
    main()
