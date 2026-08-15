#!/usr/bin/env python3
"""Binance.US historical daily-candle backfill -> S3 crypto-hist/<sym>/daily.json.

Research-first (verified 2026-08-15, live against the public API):
  - klines: GET /api/v3/klines?symbol=<S>&interval=1d&limit=1000 (public, no key).
    Returns up to 1000 candles; paginate backward with `endTime` to reach deeper
    history (Binance.US launched ~2019).
  - Rate limits (exchangeInfo): REQUEST_WEIGHT 3600/min, RAW_REQUESTS 6100/min,
    ORDERS 100/s + 200k/day. klines weight is ~1-2/request; a full multi-symbol
    paginated backfill stays far under limits (sleep 0.3s between calls).
  - Fees (spot, standard tier): 0.1% maker / 0.1% taker (0.075% w/ BNB). The
    sweep cost model uses the conservative 0.1%/side.

Writes S3 (cold, ADDITIVE — new `crypto-hist/` prefix, no other writer):
  crypto-hist/<sym>/daily.json  {symbol, interval, fetched_at, bars:[{date,o,h,l,c,v}]}

This is INGESTION ONLY (read-only on the trading side, no orders).
"""
import os
import sys
import time
import json
import datetime as dt

import requests
import boto3
from dotenv import load_dotenv

# Robust to running from /tmp or the repo: resolve the repo .env explicitly.
REPO = os.environ.get('TRADING_REPO', os.path.expanduser('~/trading-system'))
load_dotenv(os.path.join(REPO, '.env'))
load_dotenv()

S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
BASE = 'https://api.binance.us/api/v3'
INTERVAL = '1d'
MAX_PER_REQ = 1000
MAX_YEARS = 6   # cap depth (~2019 Binance.US launch)

# BTC + ETH + 4 liquid alts. The 4 in the live ticker (crypto_tick.py) first.
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'LTCUSDT', 'ADAUSDT']


def _cutoff_ms():
    return int((dt.datetime.now(dt.timezone.utc)
                - dt.timedelta(days=365 * MAX_YEARS)).timestamp() * 1000)


def fetch_klines(sym, end_ms=None):
    params = {'symbol': sym, 'interval': INTERVAL, 'limit': MAX_PER_REQ}
    if end_ms is not None:
        params['endTime'] = end_ms
    r = requests.get(f'{BASE}/klines', params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError(f'unexpected klines response: {str(data)[:200]}')
    return data


def paginate(sym):
    """Walk backward from the newest candle to the depth cap. Newest-first."""
    candles = []
    end_ms = None
    while True:
        batch = fetch_klines(sym, end_ms=end_ms)
        if not batch:
            break
        candles = batch + candles                       # prepend older batch
        oldest_open = batch[0][0]
        if len(batch) < MAX_PER_REQ or oldest_open <= _cutoff_ms():
            break
        end_ms = oldest_open - 1                        # next (older) page
        if len(candles) >= MAX_PER_REQ * 8:             # hard safety cap
            break
    return candles


def normalize(kline):
    # [openTime, open, high, low, close, volume, closeTime, quoteVol, ...]
    ts = kline[0] // 1000
    return {
        'date': dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime('%Y-%m-%d'),
        'open': float(kline[1]), 'high': float(kline[2]),
        'low': float(kline[3]), 'close': float(kline[4]),
        'volume': float(kline[5]),
    }


def main():
    s3 = boto3.client('s3', region_name=AWS_REGION)
    for sym in SYMBOLS:
        try:
            raw = paginate(sym)
            bars = [normalize(k) for k in raw]
            if not bars:
                print(f'{sym}: no candles returned — skip')
                continue
            key = f'crypto-hist/{sym}/daily.json'
            payload = {
                'symbol': sym, 'interval': INTERVAL,
                'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'bars': bars,
            }
            s3.put_object(Bucket=S3_BUCKET, Key=key,
                          Body=json.dumps(payload, default=str))
            print(f'{sym}: {len(bars)} daily candles '
                  f'({bars[0]["date"]} .. {bars[-1]["date"]}) -> {key}')
        except Exception as e:  # noqa: BLE001
            print(f'{sym}: ERROR {e!r}')
        time.sleep(0.3)   # stay far under REQUEST_WEIGHT


if __name__ == '__main__':
    main()
