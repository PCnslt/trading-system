import os, io, json
import datetime as dt
from zoneinfo import ZoneInfo
import boto3, pandas as pd, numpy as np

ET = ZoneInfo('America/New_York')
S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'
PREFIX = 'ibkr/equities/intraday/1min/'

def syms():
    pag = S3.get_paginator('list_objects_v2')
    out = set()
    for p in pag.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for o in p.get('Contents', []):
            parts = o['Key'].split('/')
            if len(parts) >= 5:
                out.add(parts[4])
    return sorted(out)

def load(sym):
    pag = S3.get_paginator('list_objects_v2')
    frames = []
    for p in pag.paginate(Bucket=BUCKET, Prefix=f'{PREFIX}{sym}/'):
        for o in p.get('Contents', []):
            b = S3.get_object(Bucket=BUCKET, Key=o['Key'])
            frames.append(pd.read_parquet(io.BytesIO(b['Body'].read())))
    df = pd.concat(frames)
    df['dt'] = pd.to_datetime(df['date'])
    return df.set_index('dt')

def backtest(df, thr, cost_bp):
    df = df.copy()
    df['day'] = df.index.normalize()
    rows = []
    for _, d in df.groupby('day'):
        v = d['volume'].astype(float)
        vwap = (d['close'] * v).cumsum() / v.cumsum()
        dist = d['close'] / vwap - 1.0
        in_pos = False; entry = None
        for i in range(len(d)):
            if not in_pos and dist.iloc[i] <= -thr:
                in_pos = True; entry = d['close'].iloc[i]
            elif in_pos and (dist.iloc[i] >= 0 or i == len(d) - 1):
                exit_px = d['close'].iloc[i]
                r = exit_px / entry - 1.0 - cost_bp / 10000.0
                rows.append(r)
                in_pos = False; entry = None
    return rows

def main():
    ss = syms()
    print(f'loaded {len(ss)} symbols')
    for thr in (0.005, 0.010, 0.015):
        for cost in (6,):
            allr = []
            for s in ss:
                try:
                    allr += backtest(load(s), thr, cost)
                except Exception:
                    pass
            r = pd.Series(allr)
            if len(r) < 50:
                print(f'thr={thr*100:.1f}% cost={cost}bp: too few trades ({len(r)})'); continue
            n = len(r); split = int(n * 0.8)
            oos = r.iloc[split:]
            # date-clustered t via daily mean
            print(f'thr={thr*100:.1f}% cost={cost}bp: n={n} avg={r.mean()*1e4:.1f}bp '
                  f'PF={r[r>0].sum()/-r[r<0].sum():.2f} win={(r>0).mean()*100:.0f}% '
                  f'OOS avg={oos.mean()*1e4:.1f}bp OOS n={len(oos)}')

if __name__ == '__main__':
    main()
