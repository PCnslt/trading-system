#!/usr/bin/env python3
"""Intraday 1-min equity bar backfill — paced, checkpointed, resume-safe.

Unlocks backtesting the intraday strategies (ORB, EMA-ride, red-to-green, etc.) that
were previously untestable. Verified 2026-08-27: 1-min bars are retrievable but ONLY
in ~1-month chunks (a 1Y/3Y single request times out -> 0 bars).

Design:
  - Universe: top N names by dollar volume (first N of universe_1500.json).
  - Chunk: monthly (1 M) -> ~6 requests/symbol for 6 months.
  - Pacing: sleep PACING_S between requests (IBKR 60 req/10min hard cap).
  - Checkpoint: manifest JSON (done symbol-months) -> resume on interruption.
  - Output: S3 ibkr/equities/intraday/1min/<sym>/<yyyymm>.parquet

Usage:
  ./venv/bin/python data/ibkr_intraday_backfill.py --months 6 --limit 200
"""
from __future__ import annotations
import argparse, io, json, os, sys, time
import datetime as dt
from dateutil.relativedelta import relativedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
import pandas as pd
from ib_insync import IB, Stock, util

S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
REGION = os.getenv('AWS_REGION', 'us-east-1')
IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4001'))
PACING_S = float(os.getenv('IBKR_INTRADAY_PACING_S', '10.5'))
MANIFEST = os.path.join(_ROOT, 'data', 'ibkr_intraday_manifest.json')


def universe(limit):
    p = os.path.join(_ROOT, 'research', 'universe_1500.json')
    syms = list(dict.fromkeys(json.load(open(p))['symbols']))
    return syms[:limit]


def load_manifest():
    if os.path.exists(MANIFEST):
        return set(json.load(open(MANIFEST)))
    return set()


def save_manifest(done):
    with open(MANIFEST, 'w') as f:
        json.dump(sorted(done), f)


def month_end(year, month):
    d = dt.date(year, month, 1) + relativedelta(months=1) - relativedelta(days=1)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--months', type=int, default=6)
    ap.add_argument('--limit', type=int, default=200)
    ap.add_argument('--useRTH', type=int, default=1)
    a = ap.parse_args()

    syms = universe(a.limit)
    done = load_manifest()
    s3 = boto3.client('s3', region_name=REGION)
    util.patchAsyncio()
    ib = IB()
    ib.connect(IBKR_HOST, IBKR_PORT, clientId=11, timeout=30, readonly=True)
    print(f'connected accounts={ib.managedAccounts()} (READ-ONLY)', flush=True)
    print(f'universe={len(syms)} symbols, {a.months} months back, pacing={PACING_S}s', flush=True)

    now = dt.date.today()
    total_ok = total_skip = total_fail = 0
    for si, sym in enumerate(syms):
        con = Stock(sym, 'SMART', 'USD')
        try:
            ib.qualifyContracts(con)
        except Exception as e:
            print(f'  {sym}: qualify FAILED {e!r}', flush=True)
            time.sleep(PACING_S)
            continue
        for m in range(a.months):
            ym = (now.replace(day=1) - relativedelta(months=m)).strftime('%Y%m')
            key = f'{sym}:{ym}'
            if key in done:
                total_skip += 1
                continue
            end = month_end(int(ym[:4]), int(ym[4:6]))
            try:
                bars = ib.reqHistoricalData(
                    con, endDateTime=end.strftime('%Y%m%d 16:00:00'),
                    durationStr='1 M', barSizeSetting='1 min',
                    whatToShow='TRADES', useRTH=a.useRTH, formatDate=1)
                if bars:
                    df = util.df(bars)
                    buf = io.BytesIO()
                    df.to_parquet(buf, index=False)
                    buf.seek(0)
                    s3.upload_fileobj(buf, S3_BUCKET,
                                      f'ibkr/equities/intraday/1min/{sym}/{ym}.parquet')
                    done.add(key)
                    total_ok += 1
                else:
                    total_fail += 1
            except Exception as e:
                total_fail += 1
                print(f'  {sym} {ym}: FAILED {e!r}', flush=True)
            time.sleep(PACING_S)
        if (si + 1) % 20 == 0:
            save_manifest(done)
            print(f'  [{si+1}/{len(syms)}] ok={total_ok} skip={total_skip} '
                  f'fail={total_fail}', flush=True)

    save_manifest(done)
    ib.disconnect()
    print(f'DONE ok={total_ok} skip={total_skip} fail={total_fail}', flush=True)


if __name__ == '__main__':
    main()
