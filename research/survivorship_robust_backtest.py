#!/usr/bin/env python3
"""Survivorship-ROBUST re-validation of the core edges.

Fixes the three honesty bugs from the 2026-08-28 audit:
  1. SURVIVORSHIP — test on the TOP-N liquid names only (large caps rarely delist, so
     the universe is ~point-in-time clean). Small-caps are where the dead-name bias lives.
  2. COST — 10bp/side (not 5bp) to reflect the measured 12bp open-leg reality.
  3. t-STAT — date-CLUSTERED (bars grouped by signal date), not per-trade, so 10k trades
     on the same day don't fake significance.
"""
import io, json, os, sys
import numpy as np
import pandas as pd
import boto3

S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'
COST = float(os.getenv('BT_COST_BP', '10')) / 1e4  # 10bp/side

def load_universe(path):
    with open(path) as f:
        raw = json.load(f)
    if isinstance(raw, dict) and 'symbols' in raw:
        return raw['symbols']
    if isinstance(raw, list):
        return raw
    return list(raw.keys())

def load_daily(sym):
    key = f'ibkr/equities/daily/{sym}.parquet'
    try:
        o = S3.get_object(Bucket=BUCKET, Key=key)
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        df['date'] = pd.to_datetime(df['date'])
        return df.set_index('date').sort_index()
    except Exception:
        return None

def rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, min_periods=n).mean()
    rs = up / dn
    return (100 - 100/(1+rs)).fillna(50.0)

def clustered_t(ret_by_date):
    """t-stat where each DATE is one observation (mean of that day's trades)."""
    means = ret_by_date.groupby(ret_by_date.index).mean()
    if len(means) < 30 or means.std() == 0:
        return np.nan, len(means)
    return float(means.mean() / (means.std()/np.sqrt(len(means)))), len(means)

def run(univ, n_top, exit_mode='nextclose'):
    syms = univ[:n_top]
    rows = []
    for sym in syms:
        df = load_daily(sym)
        if df is None or len(df) < 260:
            continue
        c = df['close']
        df = df.assign(r=rsi(c, 14), sma200=c.rolling(200).mean())
        sig = df[(df['r'] < 25) & (c > df['sma200'])]
        for i in sig.index:
            j = df.index.get_loc(i)
            if j + 1 >= len(df):
                continue
            e = df.iloc[j+1]
            entry = e['open']
            if exit_mode == 'nextclose':
                exit_px = e['close']
            else:
                exit_px = e['open']
            ret = exit_px/entry - 1 - 2*COST
            rows.append((i.date(), sym, ret, entry, exit_px))
    d = pd.DataFrame(rows, columns=['date', 'sym', 'ret', 'entry', 'exit'])
    if d.empty:
        return None
    d = d.set_index('date')
    # chronological OOS: last 20% of DATES held out
    dates = sorted(d.index.unique())
    split = dates[int(len(dates)*0.8)]
    is_tr = d.index < split
    oos = d[~is_tr]
    def summ(x):
        if x.empty:
            return (0, 0, np.nan, np.nan, 0)
        wins = (x['ret'] > 0).mean()
        avg = x['ret'].mean()*1e4
        t, nd = clustered_t(x['ret'])
        pf = x[x['ret']>0]['ret'].sum() / -x[x['ret']<0]['ret'].sum() if (x['ret']<0).any() else np.inf
        return (pf, wins, avg, t, len(x))
    return summ(d[is_tr]), summ(oos), len(d)

if __name__ == '__main__':
    univ = load_universe('research/universe_1500.json')
    print(f'universe loaded: {len(univ)} names (liquid-first)')
    print(f'COST = {COST*1e4:.0f}bp/side | t-stat date-clustered | OOS = last 20% of dates')
    for n in [100, 300, 500]:
        r = run(univ, n)
        if not r:
            continue
        (is_pf, is_w, is_avg, is_t, is_n), (oo_pf, oo_w, oo_avg, oo_t, oo_n), tot = r
        print(f'\nRSI(14)<25  exit=next-close  top-{n} liquid names  (n={tot})')
        print(f'  IS : PF {is_pf:.3f}  win {is_w:.1%}  {is_avg:+.1f}bp  t {is_t:+.2f}  ({is_n})')
        print(f'  OOS: PF {oo_pf:.3f}  win {oo_w:.1%}  {oo_avg:+.1f}bp  t {oo_t:+.2f}  ({oo_n})')
