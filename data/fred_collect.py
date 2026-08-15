#!/usr/bin/env python3
"""FRED macro collector — public fredgraph.csv (NO API key needed).

Pulls the free FRED CSV export for a small macro series set and archives to
S3 `macro/<series>.json`. Frequency is inferred from the series (daily for
DGS10/DGS2/DGS30/DFEDTARU/T10Y2Y/VIXCLS, monthly for CPIAUCSL/UNRATE/PAYEMS).

Series:
  DGS10   10y Treasury constant maturity (daily)
  DGS2    2y  Treasury constant maturity (daily)
  DGS30   30y Treasury constant maturity (daily)
  DFEDTARU Fed funds target upper bound (daily)
  CPIAUCSL CPI (monthly)
  UNRATE   unemployment rate (monthly)
  PAYEMS   nonfarm payrolls (monthly)
  T10Y2Y   10y-2y spread (daily)
  VIXCLS   VIX close (daily)

Idempotent + self-healing: overwrites the same <series>.json each run. FRED's
missing-value sentinel is '.' (also 'ND' in some exports) -> stored as null.

Usage: python data/fred_collect.py
"""
import os
import sys
import time
import json
import datetime as dt

import boto3
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PACING_S = float(os.getenv('FRED_PACING_S', '1.0'))
FRED_CSV = 'https://fred.stlouisfed.org/graph/fredgraph.csv'

SERIES = [
    'DGS10', 'DGS2', 'DGS30', 'DFEDTARU', 'CPIAUCSL',
    'UNRATE', 'PAYEMS', 'T10Y2Y', 'VIXCLS',
]

# Daily-frequency series (for documentation); monthly series are the rest.
DAILY = {'DGS10', 'DGS2', 'DGS30', 'DFEDTARU', 'T10Y2Y', 'VIXCLS'}


def _num(v):
    v = (v or '').strip()
    if v in ('', '.', 'ND', 'na', 'NA'):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def fetch_series(series):
    r = requests.get(FRED_CSV, params={'id': series}, timeout=60)
    if r.status_code != 200:
        print(f"  [{series}] HTTP {r.status_code}")
        return None
    lines = r.text.strip().splitlines()
    if not lines:
        print(f"  [{series}] empty response")
        return None
    # header is line 0: observation_date,<series>  (name varies)
    obs = []
    for ln in lines[1:]:
        parts = ln.split(',')
        if len(parts) < 2:
            continue
        date = parts[0].strip()
        val = _num(parts[1])
        if date and val is not None:
            obs.append({'date': date, 'value': val})
    return obs


def main():
    s3 = boto3.client('s3', region_name=AWS_REGION)
    n = 0
    for i, series in enumerate(SERIES):
        if i > 0:
            time.sleep(PACING_S)
        try:
            obs = fetch_series(series)
            if not obs:
                print(f"  [{series}] NO DATA — skip")
                continue
            payload = {
                'series': series,
                'source': 'fred',
                'frequency': 'daily' if series in DAILY else 'monthly',
                'observations': obs,
                'fetchedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            key = f'macro/{series}.json'
            s3.put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(payload))
            print(f"  [{series}] {len(obs)} obs ({obs[0]['date']}..{obs[-1]['date']}) "
                  f"-> s3://{S3_BUCKET}/{key}")
            n += 1
        except Exception as e:
            print(f"  [{series}] FAILED: {e!r}")
    print(f"\nDONE: {n}/{len(SERIES)} FRED series -> S3 macro/.")


if __name__ == '__main__':
    main()
