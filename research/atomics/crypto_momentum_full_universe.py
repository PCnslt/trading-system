#!/usr/bin/env python3
"""Re-run crypto momentum on the FULL Binance.US universe (202 symbols, 1d).

Reads crypto/klines/1d/<sym>/<yyyymm>.parquet (full backfill), filters to symbols
with >=365 days, and re-tests TS + cross-sectional momentum with honest costs.
This addresses the 13-symbol survivorship concern.
"""
import io
import json
import numpy as np
import pandas as pd
import boto3
from concurrent.futures import ThreadPoolExecutor

BUCKET = 'trading-datalake-920641308584'
REGION = 'us-east-1'
ONE_SIDE_BP = 10.0
MIN_DAYS = 365


def list_keys(prefix):
    s3 = boto3.client('s3', region_name=REGION)
    keys, token = [], None
    while True:
        kw = {'Bucket': BUCKET, 'Prefix': prefix}
        if token:
            kw['ContinuationToken'] = token
        r = s3.list_objects_v2(**kw)
        keys += [o['Key'] for o in r.get('Contents', [])]
        if r.get('IsTruncated'):
            token = r.get('NextContinuationToken')
        else:
            break
    return keys


def download(key):
    s3 = boto3.client('s3', region_name=REGION)
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        return pd.read_parquet(io.BytesIO(obj['Body'].read()))
    except Exception:
        return None


def load_daily_panel(min_days=MIN_DAYS):
    keys = [k for k in list_keys('crypto/klines/1d/') if k.endswith('.parquet')]
    syms = sorted(set(k.split('/')[3] for k in keys))
    print(f'downloading {len(keys)} daily parquet files for {len(syms)} symbols...')
    with ThreadPoolExecutor(max_workers=16) as ex:
        frames = list(ex.map(download, keys))
    by_sym = {}
    for k, df in zip(keys, frames):
        if df is None or df.empty or 'ts' not in df:
            continue
        sym = k.split('/')[3]
        by_sym.setdefault(sym, []).append(df[['ts', 'close']])
    panel = {}
    for sym, parts in by_sym.items():
        d = pd.concat(parts).drop_duplicates(subset=['ts']).sort_values('ts')
        d = d.set_index('ts')['close']
        if len(d) >= min_days:
            panel[sym] = d
    px = pd.DataFrame(panel).sort_index().ffill()
    return px


def stats(r, name):
    r = r.dropna()
    if len(r) < 60:
        print(f'{name}: insufficient ({len(r)})')
        return
    n = len(r)
    t = r.mean() / (r.std() / np.sqrt(n)) if r.std() > 0 else 0.0
    ann = (1 + r).prod() ** (365 / n) - 1
    cump = (1 + r).cumprod()
    mdd = (cump / cump.cummax() - 1).min()
    wins = (r > 0).mean()
    pf = r[r > 0].sum() / abs(r[r < 0].sum()) if r[r < 0].sum() != 0 else np.inf
    print(f'{name:36s} n={n:5d} mean={r.mean()*1e4:6.2f}bp/d t={t:5.2f} '
          f'ann={ann*100:6.1f}% PF={pf:4.2f} win={wins*100:4.1f}% maxDD={mdd*100:6.1f}%')


def main():
    px = load_daily_panel()
    print(f'panel: {px.shape[1]} symbols x {px.shape[0]} days '
          f'({px.index[0].date()}..{px.index[-1].date()})')
    ret = px.pct_change()

    stats(ret.mean(axis=1), 'benchmark: equal-weight B&H (gross)')

    for lb in [7, 14, 28]:
        sig = (px.pct_change(lb) > 0).astype(float)
        pos = sig.shift(1)
        strat = (pos * ret).mean(axis=1)
        turn = pos.diff().abs().mean(axis=1)
        net = strat - turn * ONE_SIDE_BP / 1e4
        stats(net, f'TS-mom {lb}d long/flat (net)')

    for lb in [7, 14, 28]:
        sig = np.sign(px.pct_change(lb))
        pos = sig.shift(1)
        strat = (pos * ret).mean(axis=1)
        turn = pos.diff().abs().mean(axis=1)
        net = strat - turn * ONE_SIDE_BP / 1e4
        stats(net, f'TS-mom {lb}d long/short (net)')

    for lb in [14, 28]:
        for K in [5, 10]:
            mom = px.pct_change(lb)
            rank = mom.rank(axis=1, ascending=False, method='first')
            hold = (rank <= K).astype(float)
            w = hold.div(hold.sum(axis=1), axis=0).shift(1)
            strat = (w * ret).sum(axis=1)
            turn = w.diff().abs().sum(axis=1)
            net = strat - turn * ONE_SIDE_BP / 1e4
            stats(net, f'XS-mom {lb}d top{K} long (net)')


if __name__ == '__main__':
    main()
