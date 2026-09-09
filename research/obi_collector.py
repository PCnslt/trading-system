#!/usr/bin/env python3
"""Forward OBI (Order Book Imbalance) collector — FULL universe, pre-market + open.

OBI = (bid_size_top - ask_size_top) / (bid_size_top + ask_size_top)  in [-1, +1]

Captures the top-of-book bid/ask SIZE for the full universe via RH get_equity_price_book
(4 symbols/call), computes OBI, writes one parquet per sweep to S3  obi/<date>/obi_<HHMM>.parquet.

READ-ONLY: get_equity_price_book only. Never places an order.
Runs pre-market (07:00-09:30 ET) + the open (09:30-10:00 ET) when the OBI signal matters.
"""
import os, sys, json, time, io
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()
from hardening.rh_client import RHClient
import boto3
import pandas as pd

NY = ZoneInfo('America/New_York')
BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
S3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
BOOK_CALL = 4
PACING = 0.15          # seconds between book calls


def universe():
    p = os.path.join(_ROOT, 'research', 'universe_1500.json')
    return list(dict.fromkeys(json.load(open(p))['symbols']))


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main():
    now = dt.datetime.now(NY)
    # pre-market + the first 30 min of RTH (OBI signal window 08:30-09:15)
    m = now.hour * 60 + now.minute
    if not (420 <= m <= 600):   # 07:00 .. 10:00 ET
        print(f'{now:%H:%M} ET — outside OBI window, no-op')
        return

    syms = universe()
    rh = RHClient()
    rows = []
    for ch in chunks(syms, BOOK_CALL):
        try:
            raw = rh._tool('get_equity_price_book', symbols=list(ch))
            books = {b.get('symbol'): b for b in ((raw.get('data') or {}).get('books') or [])}
        except Exception as e:
            print(f'  book call {ch[:2]}... ERR {e!r}')
            books = {}
        for b in books.values():
            sym = b.get('symbol')
            bids, asks = b.get('bids') or [], b.get('asks') or []
            if not bids or not asks:
                continue
            try:
                bp = float(bids[0]['price']); bq = float(bids[0].get('quantity') or 0)
                ap = float(asks[0]['price']); aq = float(asks[0].get('quantity') or 0)
            except Exception:
                continue
            tot = bq + aq
            obi = (bq - aq) / tot if tot > 0 else None
            mid = (bp + ap) / 2
            spread = (ap - bp) / mid * 1e4 if mid > 0 else None
            rows.append({'ts': now.isoformat(), 'symbol': sym,
                         'bid_price': bp, 'ask_price': ap,
                         'bid_size': bq, 'ask_size': aq, 'obi': obi,
                         'mid': round(mid, 4), 'spread_bp': round(spread, 2) if spread else None})
        time.sleep(PACING)

    if rows:
        df = pd.DataFrame(rows)
        key = f"obi/{now.date().isoformat()}/obi_{now.strftime('%H%M')}.parquet"
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        S3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
        print(f'{now:%H:%M:%S} ET — OBI sweep: {len(df)}/{len(syms)} symbols -> s3://{BUCKET}/{key}')
    else:
        print(f'{now:%H:%M:%S} ET — OBI sweep: 0 books (feed down?)')


if __name__ == '__main__':
    main()
