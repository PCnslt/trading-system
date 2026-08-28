#!/usr/bin/env python3
"""Gap-and-go backtest on real 1-min bars (the intraday data just finished backfilling).

Strategy (#1 from the owner's 20-list, and the catalyst/momentum lane we're building):
  signal: gap-up >= 3% vs prior close AND high relative opening volume
  enter:  at the open (first 1-min bar)
  exit:   same-day close (flat by close), or a trailing stop, or sell-into-strength

Universe: the ~168 liquid symbols with 6 months of 1-min bars in S3.
Costs: 5 bp/side base, stress at 10 bp (the open sell leg is the expensive one, ~12bp
measured). OOS split: last 25% of the sample.
"""
from __future__ import annotations
import io, json
import numpy as np
import pandas as pd
import boto3

S3 = boto3.client('s3', region_name='us-east-1')
B = 'trading-datalake-920641308584'
GAP_MIN = 0.03          # 3% gap-up
RVOL_MIN = 1.5          # relative opening volume
OPEN_MIN = 15           # first-N minutes for relative-volume calc


def load_intraday(sym):
    """Return a DataFrame of 1-min bars with a per-day grouping, or None."""
    keys = []
    cont = None
    while True:
        kw = dict(Bucket=B, Prefix=f'ibkr/equities/intraday/1min/{sym}/')
        if cont:
            kw['ContinuationToken'] = cont
        r = S3.list_objects_v2(**kw)
        keys += [o['Key'] for o in r.get('Contents', [])]
        if r.get('IsTruncated'):
            cont = r['NextContinuationToken']
        else:
            break
    if not keys:
        return None
    frames = []
    for k in keys:
        o = S3.get_object(Bucket=B, Key=k)
        frames.append(pd.read_parquet(io.BytesIO(o['Body'].read())))
    df = pd.concat(frames).sort_values('date')
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date')
    df = df[~df.index.duplicated(keep='last')]
    return df


def simulate(sym, df, exit_mode, cost):
    """Return list of trade returns (in bp) for one symbol + exit mode."""
    df = df.copy()
    df['day'] = df.index.normalize()
    days = df['day'].unique()
    # prior close + rolling avg opening volume per day
    day_close = df.groupby('day')['close'].last()
    day_open = df.groupby('day')['open'].first()
    opvol = df.groupby('day')['volume'].apply(lambda s: s.head(OPEN_MIN).sum())
    opvol_avg = opvol.rolling(20, min_periods=10).mean().shift(1)

    trades = []
    for i, d in enumerate(days):
        if i == 0:
            continue
        prev_close = day_close.iloc[i - 1]
        ddf = df[df['day'] == d]
        if len(ddf) < OPEN_MIN or prev_close <= 0:
            continue
        opn = ddf['open'].iloc[0]
        gap = opn / prev_close - 1.0
        rvol = opvol.iloc[i] / opvol_avg.iloc[i] if opvol_avg.iloc[i] and opvol_avg.iloc[i] > 0 else 0.0
        if gap < GAP_MIN or rvol < RVOL_MIN:
            continue
        entry = opn
        if exit_mode == 'close':
            exit_px = ddf['close'].iloc[-1]
        elif exit_mode == 'nextopen':
            # exit at the NEXT session's OPEN (fix 2026-08-28: was next day's CLOSE)
            exit_px = day_open.iloc[i + 1] if i + 1 < len(days) else ddf['close'].iloc[-1]
        elif exit_mode == 'trail':
            # trail 1 ATR(14, on 1-min) from entry peak
            atr = (ddf['high'] - ddf['low']).rolling(14).mean().iloc[-1]
            exit_px = None
            peak = entry
            stop = entry - 2 * atr if atr and atr > 0 else entry * 0.98
            for _, r in ddf.iterrows():
                peak = max(peak, r['high'])
                if r['low'] <= stop:
                    exit_px = stop
                    break
                # ratchet up 1 ATR once in profit
                stop = max(stop, peak - 2 * atr) if atr and atr > 0 else stop
            if exit_px is None:
                exit_px = ddf['close'].iloc[-1]
        else:
            raise ValueError(exit_mode)
        if exit_px and entry > 0:
            ret = exit_px / entry - 1.0 - 2 * cost
            trades.append(ret * 1e4)  # bp
    return trades


def summarize(tr, label):
    if not tr:
        return f'{label:8s} n=0'
    t = np.array(tr)
    n = len(t)
    win = (t > 0).mean()
    pf = t[t > 0].sum() / abs(t[t < 0].sum()) if (t < 0).sum() != 0 else float('inf')
    tstat = t.mean() / (t.std(ddof=1) / np.sqrt(n)) if n > 2 else 0
    return (f'{label:8s} n={n:5d} win={win*100:4.0f}% PF={pf:.2f} '
            f'avg={t.mean():+.1f}bp t={tstat:+.2f}')


def main():
    # discover symbols
    r = S3.list_objects_v2(Bucket=B, Prefix='ibkr/equities/intraday/1min/', MaxKeys=5000)
    syms = sorted({o['Key'].split('/')[4] for o in r.get('Contents', [])})
    print(f'universe: {len(syms)} symbols with 1-min bars')

    for cost in (0.0005, 0.0010):
        print(f'\n=== cost {cost*1e4:.0f}bp/side ===')
        for mode in ('close', 'nextopen', 'trail'):
            all_tr = []
            for sym in syms:
                df = load_intraday(sym)
                if df is None:
                    continue
                all_tr += simulate(sym, df, mode, cost)
            t = np.array(all_tr)
            n = len(t)
            split = int(n * 0.75)
            ins, oos = t[:split], t[split:]
            def s(x):
                if len(x) == 0:
                    return 'n/a'
                w = (x > 0).mean()
                pf = x[x > 0].sum() / abs(x[x < 0].sum()) if (x < 0).sum() else float('inf')
                ts = x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 else 0
                return f'n={len(x)} win={w*100:.0f}% PF={pf:.2f} avg={x.mean():+.1f}bp t={ts:+.2f}'
            print(f'  {mode:8s} FULL {s(t)}')
            print(f'           IS   {s(ins)}')
            print(f'           OOS  {s(oos)}')


if __name__ == '__main__':
    main()
