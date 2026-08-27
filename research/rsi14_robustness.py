#!/usr/bin/env python3
"""RSI reversal ROBUSTNESS — the only survivor of the 20-strategy eval.

Tests whether "buy RSI(period)<threshold, enter next open, exit same-day close" is a
real edge or a lucky threshold. Sweeps:
  period   : 10 / 14 / 20
  threshold: 15 / 20 / 25 / 30
  exit     : SAME_CLOSE (flat by close, matches owner's rule) and NEXT_OPEN (1 overnight)
  cost     : 5 / 10 / 15 bp per side
Reports full + OOS (>=2022) PF/avg/t. Only OOS t matters (in-sample is a mirage).
"""
from __future__ import annotations
import io, os, sys, json
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/trading-system/.env')

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
MIN_DV = 5e6
OOS_FROM = '2022-01-01'


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + up/dn.replace(0, np.nan))).fillna(50.0)


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open','high','low','close','volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        df['dv'] = (df['close']*df['volume']).rolling(20).mean()
        return df
    except Exception:
        return None


def run(df, period, thr, exit_mode, cost_bp):
    o = df['open'].values; c = df['close'].values; dv = df['dv'].values
    sig = (rsi(df['close'], period) < thr).values
    idx = df.index; n = len(df)
    trades = []; i = 1
    while i < n - 1:
        if not (sig[i] and dv[i] >= MIN_DV and o[i+1] > 0):
            i += 1; continue
        if exit_mode == 'SAME_CLOSE':
            ret = c[i+1]/o[i+1] - 1.0
        else:  # NEXT_OPEN: hold overnight, exit at i+2 open
            if i+2 >= n:
                break
            ret = o[i+2]/o[i+1] - 1.0
        trades.append({'ret': ret - 2*cost_bp/1e4, 'date': idx[i+1]})
        i += 2
    return trades


def stats(tr, oos=False):
    if oos:
        tr = [t for t in tr if str(t['date'].date()) >= OOS_FROM]
    if len(tr) < 50:
        return None
    r = np.array([t['ret'] for t in tr])
    w, lo = r[r > 0], r[r <= 0]
    pf = (w.sum()/-lo.sum()) if lo.sum() < 0 else float('inf')
    t = r.mean()/(r.std(ddof=1)/np.sqrt(len(r))) if r.std() > 0 else 0.0
    return {'n': len(r), 'PF': round(pf,3), 'win%': round(100*len(w)/len(r),1),
            'avg_bp': round(r.mean()*1e4,1), 't': round(float(t),2)}


def main():
    syms = list(dict.fromkeys(json.load(
        open('/home/ubuntu/trading-system/research/universe_1500.json'))['symbols']))
    s3 = boto3.client('s3', region_name='us-east-1')
    print('loading…', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'usable {len(data)}\n', flush=True)

    print('=== RSI reversal: SAME-DAY-CLOSE exit @5bp (OOS from 2022) ===')
    print(f'{"period":>6}{"thr":>4}{"OOS n":>7}{"OOS PF":>8}{"OOS avg":>9}{"OOS t":>7}')
    best = []
    for period in (10, 14, 20):
        for thr in (15, 20, 25, 30):
            tr = []
            for df in data.values():
                tr += run(df, period, thr, 'SAME_CLOSE', 5.0)
            so = stats(tr, True)
            if so:
                best.append((so['t'], period, thr, so))
                print(f'{period:>6}{thr:>4}{so["n"]:>7}{so["PF"]:>8.3f}{so["avg_bp"]:>9.1f}{so["t"]:>7.2f}')

    print('\n=== cost stress on the best config ===')
    best.sort(reverse=True)
    _, bp, bt, _ = best[0]
    print(f'best = RSI({bp}) < {bt}; cost sweep:')
    print(f'{"cost_bp":>7}{"OOS PF":>8}{"OOS avg":>9}{"OOS t":>7}')
    for cost in (5.0, 10.0, 15.0):
        tr = []
        for df in data.values():
            tr += run(df, bp, bt, 'SAME_CLOSE', cost)
        so = stats(tr, True)
        if so:
            print(f'{cost:>7.0f}{so["PF"]:>8.3f}{so["avg_bp"]:>9.1f}{so["t"]:>7.2f}')

    print('\n=== same config, NEXT-OPEN exit (1 overnight hold) @5bp ===')
    tr = []
    for df in data.values():
        tr += run(df, bp, bt, 'NEXT_OPEN', 5.0)
    so = stats(tr, True)
    if so:
        print(f'OOS n={so["n"]}  PF={so["PF"]}  avg={so["avg_bp"]}bp  t={so["t"]}')


if __name__ == '__main__':
    main()
