#!/usr/bin/env python3
"""Multi-timeframe crypto klines backfill -> S3 crypto/klines/<tf>/<sym>/<yyyymm>.parquet.

Full Binance.US USDT universe, resumable manifest, month-partitioned parquet.
Read-only ingestion (no orders). Run once now as a background backfill; the
live top-up lives in crypto_live.py (cron).
"""
import os, sys, json, time, io, argparse
import datetime as dt

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

import requests
import boto3
import pandas as pd

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
REGION = os.getenv('AWS_REGION', 'us-east-1')
BASE = 'https://api.binance.us/api/v3'

TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']
DEPTH_DAYS = {'1m': 7, '5m': 15, '15m': 30, '1h': 90, '4h': 180, '1d': 2500}
MAX_PER_REQ = 1000
MANIFEST = os.path.join(_ROOT, 'data', 'crypto_klines_manifest.json')
PACING = 0.2


def universe():
    r = requests.get(f'{BASE}/exchangeInfo', timeout=30)
    r.raise_for_status()
    return sorted(s['symbol'] for s in r.json().get('symbols', [])
                  if s.get('status') == 'TRADING' and s.get('quoteAsset') == 'USDT')


def fetch_klines(sym, interval, end_ms=None):
    p = {'symbol': sym, 'interval': interval, 'limit': MAX_PER_REQ}
    if end_ms:
        p['endTime'] = end_ms
    r = requests.get(f'{BASE}/klines', params=p, timeout=30)
    r.raise_for_status()
    d = r.json()
    if not isinstance(d, list):
        raise RuntimeError(f'unexpected: {str(d)[:200]}')
    return d


def backfill(sym, interval):
    depth_ms = int(DEPTH_DAYS[interval] * 86400 * 1000)
    start_ms = int(time.time() * 1000) - depth_ms
    candles, cursor = [], None
    while True:
        batch = fetch_klines(sym, interval, end_ms=cursor)
        if not batch:
            break
        candles = batch + candles
        if len(batch) < MAX_PER_REQ or batch[0][0] <= start_ms:
            break
        cursor = batch[0][0] - 1
        if len(candles) >= MAX_PER_REQ * 40:
            break
        time.sleep(PACING)
    return candles


def to_df(candles):
    rows = [{'open_time': k[0], 'open': float(k[1]), 'high': float(k[2]),
             'low': float(k[3]), 'close': float(k[4]), 'volume': float(k[5]),
             'close_time': k[6], 'quote_volume': float(k[7]), 'trades': k[8]}
            for k in candles]
    df = pd.DataFrame(rows)
    if not df.empty:
        df['ts'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    return df


def write_months(df, s3, sym, tf):
    df['ym'] = df['ts'].dt.strftime('%Y%m')
    for ym, g in df.groupby('ym'):
        g = g.drop(columns=['ym'])
        buf = io.BytesIO()
        g.to_parquet(buf, index=False)
        s3.put_object(Bucket=BUCKET,
                      Key=f'crypto/klines/{tf}/{sym}/{ym}.parquet',
                      Body=buf.getvalue())


def load_manifest():
    try:
        return set(json.load(open(MANIFEST)))
    except Exception:
        return set()


def save_manifest(done):
    with open(MANIFEST, 'w') as f:
        json.dump(sorted(done), f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='only N symbols')
    a = ap.parse_args()

    syms = universe()
    if a.limit:
        syms = syms[:a.limit]
    done = load_manifest()
    s3 = boto3.client('s3', region_name=REGION)
    print(f'universe={len(syms)} | already done={len(done)}', flush=True)

    for si, sym in enumerate(syms):
        for tf in TIMEFRAMES:
            key = f'{sym}|{tf}'
            if key in done:
                continue
            try:
                candles = backfill(sym, tf)
                df = to_df(candles)
                if not df.empty:
                    write_months(df, s3, sym, tf)
                done.add(key)
                print(f'[{si+1}/{len(syms)}] {sym} {tf}: {len(candles)} bars', flush=True)
            except Exception as e:
                print(f'  {sym} {tf}: ERR {e!r}', flush=True)
            time.sleep(PACING)
        save_manifest(done)
    save_manifest(done)
    print(f'DONE. manifest={len(done)}', flush=True)


if __name__ == '__main__':
    main()
