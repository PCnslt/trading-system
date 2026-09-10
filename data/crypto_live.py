#!/usr/bin/env python3
"""Live crypto collector (cron, ~10 min): klines top-up + order book + account.

1. klines top-up  : last 500 candles for liquid symbols, merged into month parquets.
2. order book     : top-N liquid symbols depth snapshot -> crypto/book/<sym>/<ym>.parquet
3. account        : authenticated balance snapshot -> crypto/account/<ym>.json
All read-only. No orders.
"""
import os, sys, json, time, io, hashlib, hmac, urllib.parse
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
N_LIQUID = 30
BOOK_DEPTH = 20


def liquid_symbols(n=N_LIQUID):
    r = requests.get(f'{BASE}/ticker/24hr', timeout=30)
    r.raise_for_status()
    rows = [x for x in r.json() if x.get('symbol', '').endswith('USDT')]
    rows.sort(key=lambda x: float(x.get('quoteVolume', 0) or 0), reverse=True)
    return [x['symbol'] for x in rows[:n]]


def fetch_klines(sym, interval, limit=500):
    r = requests.get(f'{BASE}/klines',
                     params={'symbol': sym, 'interval': interval, 'limit': limit},
                     timeout=30)
    r.raise_for_status()
    return r.json()


def klines_to_df(candles):
    rows = [{'open_time': k[0], 'open': float(k[1]), 'high': float(k[2]),
             'low': float(k[3]), 'close': float(k[4]), 'volume': float(k[5]),
             'close_time': k[6], 'quote_volume': float(k[7]), 'trades': k[8]}
            for k in candles]
    df = pd.DataFrame(rows)
    if not df.empty:
        df['ts'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    return df


def upsert_klines(s3, sym, tf, df):
    df['ym'] = df['ts'].dt.strftime('%Y%m')
    for ym, g in df.groupby('ym'):
        key = f'crypto/klines/{tf}/{sym}/{ym}.parquet'
        try:
            obj = s3.get_object(Bucket=BUCKET, Key=key)
            old = pd.read_parquet(io.BytesIO(obj['Body'].read()))
            g = pd.concat([old, g], ignore_index=True)
        except Exception:
            pass
        g = g.drop(columns=['ym']).drop_duplicates(subset=['open_time']).sort_values('open_time')
        buf = io.BytesIO()
        g.to_parquet(buf, index=False)
        s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())


def snapshot_book(s3, sym):
    r = requests.get(f'{BASE}/depth', params={'symbol': sym, 'limit': BOOK_DEPTH},
                     timeout=20)
    r.raise_for_status()
    d = r.json()
    bids, asks = d.get('bids', []), d.get('asks', [])
    if not bids or not asks:
        return
    bid_size = sum(float(b[1]) for b in bids)
    ask_size = sum(float(a[1]) for a in asks)
    obi = (bid_size - ask_size) / (bid_size + ask_size) if (bid_size + ask_size) else 0.0
    best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
    spread = (best_ask - best_bid) / best_bid if best_bid else 0.0
    ym = dt.datetime.now(dt.UTC).strftime('%Y%m')
    ts = int(time.time() * 1000)
    key = f'crypto/book/{sym}/{ym}.parquet'
    row = pd.DataFrame([{'ts': ts, 'sym': sym, 'best_bid': best_bid,
                         'best_ask': best_ask, 'spread': spread, 'obi': obi,
                         'bid_size': bid_size, 'ask_size': ask_size}])
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        old = pd.read_parquet(io.BytesIO(obj['Body'].read()))
        row = pd.concat([old, row], ignore_index=True)
    except Exception:
        pass
    buf = io.BytesIO()
    row.to_parquet(buf, index=False)
    s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())


def snapshot_account(s3):
    try:
        # SSM-first secrets via infra loader
        from infra.ssm_secrets import load_ssm
        c = load_ssm(names=['/trading/binance_us/api_key', '/trading/binance_us/secret_key'])
        api_key = c.get('BINANCE_US_API_KEY', '')
        secret = c.get('BINANCE_US_SECRET_KEY', '')
    except Exception as e:
        print(f'account: SSM load failed {e!r}')
        return
    if not api_key or not secret:
        print('account: no creds')
        return
    ts = int(time.time() * 1000)
    qs = urllib.parse.urlencode({'timestamp': ts, 'recvWindow': 5000})
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    r = requests.get(f'{BASE}/account?{qs}&signature={sig}',
                     headers={'X-MBX-APIKEY': api_key}, timeout=20)
    r.raise_for_status()
    data = r.json()
    bal = [b for b in data.get('balances', [])
           if float(b.get('free', 0)) + float(b.get('locked', 0)) > 0]
    ym = dt.datetime.now(dt.UTC).strftime('%Y%m')
    key = f'crypto/account/{ym}.json'
    payload = {'ts': ts, 'fetched_at': dt.datetime.now(dt.UTC).isoformat(),
               'can_trade': data.get('canTrade'), 'balances': bal}
    s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(payload, default=str))
    print(f'account: {len(bal)} nonzero balances')


def main():
    s3 = boto3.client('s3', region_name=REGION)
    syms = liquid_symbols()
    print(f'liquid symbols: {len(syms)}')

    # 1. klines top-up (liquid only, keep the live window fresh)
    for sym in syms:
        for tf in TIMEFRAMES:
            try:
                candles = fetch_klines(sym, tf)
                df = klines_to_df(candles)
                if not df.empty:
                    upsert_klines(s3, sym, tf, df)
            except Exception as e:
                print(f'klines {sym} {tf}: {e!r}')
        time.sleep(0.15)

    # 2. order book snapshots
    for sym in syms:
        try:
            snapshot_book(s3, sym)
        except Exception as e:
            print(f'book {sym}: {e!r}')
        time.sleep(0.15)

    # 3. account snapshot
    try:
        snapshot_account(s3)
    except Exception as e:
        print(f'account: {e!r}')

    print('crypto_live done')


if __name__ == '__main__':
    main()
