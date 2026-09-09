#!/usr/bin/env python3
"""Pre-market bar backfill — IBKR useRTH=False, WHOLE universe, multiple timeframes.

Fetches extended-hours (04:00-20:00 ET) bars and filters to the PRE-MARKET session
(04:00-09:30 ET). Timeframes: 1min, 2min, 5min, 15min, 30min, 1hour.
Max history per timeframe (monthly chunks). RESUMABLE via checkpoint manifest.

Store: S3  ibkr/equities/premarket/<TF>/<SYM>/<yyyymm>.parquet
Read-only (clientId 81, distinct). No orders.
"""
import os, sys, json, time, io, argparse
import datetime as dt

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

import boto3
import pandas as pd
from ib_insync import IB, Stock, util

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
REGION = os.getenv('AWS_REGION', 'us-east-1')
HOST = os.getenv('IBKR_HOST', '127.0.0.1')
PORT = int(os.getenv('IBKR_PORT', '4001'))

TIMEFRAMES = ['1 min', '2 mins', '5 mins', '15 mins', '30 mins', '1 hour']
# max months of history per timeframe (IBKR caps: finer = shorter history)
MAX_MONTHS = {'1 min': 12, '2 mins': 12, '5 mins': 24, '15 mins': 36, '30 mins': 60, '1 hour': 120}
# chunk size (days) per request, so we stay under IBKR's per-request bar cap
# useRTH=False ~= 16h/day => 1min=960 bars/day, 2min=480, 5min=192, 15min=64, 30min=32, 1h=16
CHUNK_DAYS = {'1 min': 8, '2 mins': 15, '5 mins': 30, '15 mins': 60, '30 mins': 90, '1 hour': 120}

MANIFEST = os.path.join(_ROOT, 'data', 'ibkr_premarket_manifest.json')
PACING = 5.0   # seconds between requests (stay well under the 60-req/10min cap)


def universe():
    p = os.path.join(_ROOT, 'research', 'universe_1500.json')
    return list(dict.fromkeys(json.load(open(p))['symbols']))


def load_manifest():
    try:
        return set(json.load(open(MANIFEST)))
    except Exception:
        return set()


def save_manifest(done):
    with open(MANIFEST, 'w') as f:
        json.dump(sorted(done), f)


def chunks_month_range(start, months, step_days):
    """Yield (end_date_str, n_days) chunks walking back from `start`."""
    end = start
    total_days = int(months * 30.5)
    while total_days > 0:
        n = min(step_days, total_days)
        yield end.strftime('%Y%m%d %H:%M:%S'), n
        end = end - dt.timedelta(days=n)
        total_days -= n


def premarket(df):
    """Keep only pre-market bars: 04:00 <= t < 09:30 ET (bar-start)."""
    ts = pd.to_datetime(df['date'])
    m = ts.dt.hour * 60 + ts.dt.minute
    return df[(m >= 240) & (m < 570)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='process only N symbols (0=all)')
    a = ap.parse_args()

    syms = universe()
    if a.limit:
        syms = syms[:a.limit]

    done = load_manifest()
    s3 = boto3.client('s3', region_name=REGION)
    ib = IB()
    ib.connect(HOST, PORT, clientId=81, timeout=20, readonly=True)
    print(f'connected {ib.managedAccounts()} | universe={len(syms)} | already done={len(done)}', flush=True)

    start = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    try:
        for si, sym in enumerate(syms):
            c = Stock(sym, 'SMART', 'USD')
            for tf in TIMEFRAMES:
                months = MAX_MONTHS[tf]
                for endstr, nd in chunks_month_range(start, months, CHUNK_DAYS[tf]):
                    key = f'{sym}|{tf}|{endstr[:8]}'
                    if key in done:
                        continue
                    try:
                        bars = ib.reqHistoricalData(c, endDateTime=endstr, durationStr=f'{nd} D',
                                                    barSizeSetting=tf, whatToShow='TRADES',
                                                    useRTH=False, formatDate=1)
                    except Exception as e:
                        print(f'  {sym} {tf} {endstr[:8]}: ERR {e!r}', flush=True)
                        time.sleep(PACING)
                        continue
                    if not bars:
                        done.add(key)
                        time.sleep(PACING)
                        continue
                    df = util.df(bars)
                    df['date'] = pd.to_datetime(df['date'])
                    pm = premarket(df)
                    if len(pm):
                        buf = io.BytesIO()
                        pm.to_parquet(buf, index=False)
                        s3.put_object(Bucket=BUCKET, Key=f'ibkr/equities/premarket/{tf.replace(" ","")}/{sym}/{endstr[:8]}.parquet',
                                      Body=buf.getvalue())
                    done.add(key)
                    time.sleep(PACING)
            save_manifest(done)
            if (si + 1) % 25 == 0:
                print(f'[{si+1}/{len(syms)}] {sym} done; manifest={len(done)}', flush=True)
    finally:
        save_manifest(done)
        ib.disconnect()
        print(f'DONE. manifest={len(done)}', flush=True)


if __name__ == '__main__':
    main()
