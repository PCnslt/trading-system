#!/usr/bin/env python3
"""Market Light — a market-regime filter (green/yellow/red) that scales position size.

Three dimensions, each 0-100:
  1. BREADTH  = % of the universe trading above its 20-day SMA (healthy market = high).
  2. INDEX    = equal-weight universe index vs its 200-day SMA (trend).
  3. EXTREME  = today's >8% up vs <8% down movers (panic asymmetry; many downs = red).

Aggregate = 0.4*breadth + 0.4*index + 0.2*extreme  ->  green(>=60) / yellow(40-59) / red(<40).

Persists MARKETLIGHT#<date> to DynamoDB for the live lane to consume, and prints a
human-readable status. Read-only (no orders).
"""
import os, sys, json, time, io
import datetime as dt
from zoneinfo import ZoneInfo
import boto3, pandas as pd, numpy as np

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
TABLE = os.getenv('DYNAMO_TABLE', 'trading-data')
S3 = boto3.client('s3', region_name=REGION)

def load_closes(max_names=300):
    """{sym: close Series} for the top liquid names (breadth/extreme proxy)."""
    with open(os.path.join(os.path.dirname(__file__), '..', 'research', 'universe_1500.json')) as f:
        raw = json.load(f)
    syms = raw.get('symbols', raw) if isinstance(raw, dict) else raw
    out = {}
    for sym in syms[:max_names]:
        k = f'ibkr/equities/daily/{sym}.parquet'
        try:
            df = pd.read_parquet(io.BytesIO(S3.get_object(Bucket=BUCKET, Key=k)['Body'].read()))
            df['date'] = pd.to_datetime(df['date'])
            out[sym] = df.set_index('date')['close'].sort_index()
        except Exception:
            continue
    return out

def score_clamped(x, lo=0.0, hi=100.0):
    return float(np.clip(x, lo, hi))

def compute():
    closes = load_closes()
    if len(closes) < 50:
        print(f'MARKETLIGHT: only {len(closes)} symbols — insufficient data')
        return
    today = dt.datetime.now(NY).date()

    # build an equal-weight index panel over the last ~260 days
    panel = pd.DataFrame(closes).sort_index().tail(260)
    rets = panel.pct_change()
    avg = panel.mean(axis=1)

    # 1. breadth: % above 20-day SMA (use the LAST row)
    sma20 = panel.rolling(20).mean().iloc[-1]
    last = panel.iloc[-1]
    breadth = float((last > sma20).mean() * 100)

    # 2. index: avg close vs 200-day SMA
    sma200 = avg.rolling(200).mean().iloc[-1]
    idx_score = score_clamped(50 + (avg.iloc[-1] / sma200 - 1) * 1000)

    # 3. extreme: last-day >8% up vs <8% down movers
    day_ret = rets.iloc[-1]
    up8 = int((day_ret > 0.08).sum())
    dn8 = int((day_ret < -0.08).sum())
    ext_score = score_clamped(50 + (up8 - dn8) * 10)

    score = round(0.4 * breadth + 0.4 * idx_score + 0.2 * ext_score)
    light = 'green' if score >= 60 else ('yellow' if score >= 40 else 'red')
    sizing = {'green': 1.0, 'yellow': 0.5, 'red': 0.0}[light]

    dims = {'breadth': round(breadth), 'index': round(idx_score), 'extreme': round(ext_score)}
    item = {'pk': f'MARKETLIGHT#{today}', 'sk': 'latest', 'score': int(score), 'light': light,
            'sizing': str(sizing), 'breadth': int(round(breadth)), 'index': int(round(idx_score)),
            'extreme': int(round(ext_score)), 'up8': int(up8), 'dn8': int(dn8), 'n': int(len(closes)),
            'ts': int(time.time())}
    boto3.resource('dynamodb', region_name=REGION).Table(TABLE).put_item(Item=item)

    print(f'MARKETLIGHT {today}  {light.upper()}  score={score}/100  size={sizing:.1f}x')
    print(f'  breadth={breadth:.0f}% above 20SMA   index={idx_score:.0f}   extreme={ext_score:.0f} '
          f'(up8={up8} dn8={dn8})   n={len(closes)}')
    return item

if __name__ == '__main__':
    compute()
