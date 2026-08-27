#!/usr/bin/env python3
"""Trailing stop / trailing take-profit on STOCH (the winning strategy), full universe.

The trailing family was REJECTED for RSI(2) on the sub-$50 universe (trail-1ATR OOS
t=-5.41). But the owner is right that this does NOT automatically transfer to STOCH —
different strategy, different win distribution (STOCH win% 61%, long right tail).
This tests it properly: fixed 2xATR vs chandelier trailing stop vs a trailing
take-profit that locks in gains above a threshold.

STOCH entry: %K(14) crosses above %D(3) from oversold (<20), fill at next open.
Full universe (no price cap), 5bp/side, stop 2xATR base, time 5, revert exit fallback.
"""
from __future__ import annotations
import io, os, sys, json, argparse
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
MIN_DV = 5e6
MAX_HOLD, COST_BP = 5, 5.0
OOS_FROM = '2022-01-01'


def atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def stoch_signal(df):
    c, h, l = df['close'], df['high'], df['low']
    ll = l.rolling(14).min(); hh = h.rolling(14).max()
    k = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    d = k.rolling(3).mean()
    return (k > d) & (k.shift(1) <= d.shift(1)) & (k.shift(1) < 20)


def run(df, variant):
    """variant: FIXED | TRAIL_1ATR | TRAIL_2ATR | TRAIL_TP_1ATR | TRAIL_TP_2ATR"""
    sig = stoch_signal(df)
    df = df.assign(sig=sig)
    o = df['open'].values; h = df['high'].values; l = df['low'].values
    c = df['close'].values; a14 = atr(df['high'], df['low'], df['close']).values
    dv = (df['close'] * df['volume']).rolling(20).mean().values
    m5 = df['close'].rolling(5).mean().values
    r2 = (lambda x: (100 - 100 / (1 + (x.diff().clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
        / (-x.diff().clip(upper=0)).ewm(alpha=0.5, adjust=False).mean().replace(0, np.nan)))).fillna(50))(df['close'])
    r2 = r2.values
    sg = sig.values
    idx = df.index
    n = len(df)
    trades = []
    i = 1
    while i < n - 2:
        if not (sg[i] and dv[i] >= MIN_DV and a14[i] > 0):
            i += 1
            continue
        e = i + 1
        entry, a = o[e], a14[i]
        if entry <= 0 or np.isnan(entry):
            i += 1
            continue
        stop = entry - 2.0 * a
        peak = entry
        trail_hi = entry - 1e9
        tp_price = None
        exit_px = reason = None
        j = e
        while j < n:
            peak = max(peak, h[j])
            held = j - e
            # gap / stop
            if o[j] < stop:
                exit_px, reason, jx = o[j], 'gap_stop', j
                break
            if l[j] <= stop:
                exit_px, reason, jx = stop, 'stop', j
                break
            # variant logic
            hit = False
            if variant == 'TRAIL_1ATR':
                trail_hi = max(trail_hi, peak - 1.0 * a)
                hit = l[j] <= trail_hi
                px = trail_hi
            elif variant == 'TRAIL_2ATR':
                trail_hi = max(trail_hi, peak - 2.0 * a)
                hit = l[j] <= trail_hi
                px = trail_hi
            elif variant.startswith('TRAIL_TP_'):
                k = 1.0 if variant.endswith('1ATR') else 2.0
                # trailing take-profit: only engage once profit >= k*ATR
                if peak >= entry + k * a:
                    trail_hi = max(trail_hi, peak - k * a)
                    hit = l[j] <= trail_hi and trail_hi > entry
                    px = trail_hi
            if hit:
                exit_px, reason, jx = px, ('trail' if 'TP' not in variant else 'trail_tp'), j
                break
            if held >= MAX_HOLD:
                exit_px, reason, jx = c[j], 'time', j
                break
            if c[j] > m5[j] or r2[j] > 70.0:
                exit_px, reason, jx = c[j], 'revert', j
                break
            j += 1
        if exit_px is None:
            break
        trades.append({'ret': exit_px / entry - 1.0 - 2 * COST_BP / 1e4,
                       'hold': jx - e, 'date': idx[e], 'reason': reason})
        i = jx + 1
    return trades


def stats(tr, oos=False):
    if oos:
        tr = [t for t in tr if str(t['date'].date()) >= OOS_FROM]
    if len(tr) < 50:
        return None
    r = np.array([t['ret'] for t in tr])
    w, lo = r[r > 0], r[r <= 0]
    pf = (w.sum() / -lo.sum()) if lo.sum() < 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 else 0.0
    from collections import Counter
    return {'n': len(r), 'PF': round(pf, 3), 'win%': round(100 * len(w) / len(r), 1),
            'avg_bp': round(r.mean() * 1e4, 1), 't': round(float(t), 2),
            'hold': round(float(np.mean([x['hold'] for x in tr])), 2),
            'reasons': dict(Counter(x['reason'] for x in tr).most_common(4))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=1459)
    a = ap.parse_args()
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'research', 'universe_1500.json')))['symbols']))[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)}…', flush=True)
    data = {}
    for sym in syms:
        try:
            o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
            df = pd.read_parquet(io.BytesIO(o['Body'].read()))
            if len(df) < 300:
                continue
            df.index = pd.to_datetime(df['date'].astype(str))
            data[sym] = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        except Exception:
            pass
    print(f'  usable {len(data)}\n', flush=True)

    VAR = ['FIXED', 'TRAIL_1ATR', 'TRAIL_2ATR', 'TRAIL_TP_1ATR', 'TRAIL_TP_2ATR']
    out = {}
    print(f'STOCH trailing-family sweep @{COST_BP:.0f}bp, full universe, OOS from {OOS_FROM}\n')
    print(f'{"variant":15}{"n":>8}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}{"hold":>6}   '
          f'{"OOS PF":>7}{"OOS avg":>9}{"OOS t":>7}')
    for v in VAR:
        trades = []
        for df in data.values():
            trades += run(df, v)
        s, so = stats(trades), stats(trades, True)
        out[v] = {'full': s, 'oos': so}
        if s:
            print(f'{v:15}{s["n"]:>8}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.1f}'
                  f'{s["t"]:>7.2f}{s["hold"]:>6.2f}   '
                  f'{(so["PF"] if so else float("nan")):>7.3f}'
                  f'{(so["avg_bp"] if so else float("nan")):>9.1f}'
                  f'{(so["t"] if so else float("nan")):>7.2f}')
    print('\nexit-reason mix (FIXED):', out['FIXED']['full'].get('reasons'))
    print('exit-reason mix (TRAIL_TP_1ATR):', out['TRAIL_TP_1ATR']['full'].get('reasons'))
    json.dump(out, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     'research', 'stoch_trailing_results.json'), 'w'),
              indent=1, default=str)


if __name__ == '__main__':
    main()
