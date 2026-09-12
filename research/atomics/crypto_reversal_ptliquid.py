#!/usr/bin/env python3
"""Crypto reversal with POINT-IN-TIME liquidity filter (removes lookahead).

The naive liquid filter used TODAY's volume (lookahead). Here we rank coins by
trailing 30d quote volume ON EACH DATE, so the liquid set is point-in-time.
Also reports turnover to sanity-check tradability.
"""
import io
import numpy as np
import pandas as pd
import boto3
from concurrent.futures import ThreadPoolExecutor

BUCKET = 'trading-datalake-920641308584'
REGION = 'us-east-1'
ONE_SIDE_BP = 10.0
MIN_DAYS = 365
TRAILING_VOL = 30
TOP_LIQUID = 30


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


def load():
    keys = [k for k in list_keys('crypto/klines/1d/') if k.endswith('.parquet')]
    print(f'downloading {len(keys)} files...')
    with ThreadPoolExecutor(max_workers=16) as ex:
        frames = list(ex.map(download, keys))
    by_sym = {}
    for k, df in zip(keys, frames):
        if df is None or df.empty:
            continue
        sym = k.split('/')[3]
        by_sym.setdefault(sym, []).append(df[['ts', 'close', 'quote_volume']])
    close, vol = {}, {}
    for sym, parts in by_sym.items():
        d = pd.concat(parts).drop_duplicates(subset=['ts']).sort_values('ts')
        d = d.set_index('ts')
        if len(d) >= MIN_DAYS:
            close[sym] = d['close']
            vol[sym] = d['quote_volume']
    return pd.DataFrame(close).sort_index(), pd.DataFrame(vol).sort_index()


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
    print(f'{name:40s} n={n:5d} mean={r.mean()*1e4:6.2f}bp/d t={t:5.2f} '
          f'ann={ann*100:7.1f}% PF={pf:4.2f} win={wins*100:4.1f}% maxDD={mdd*100:6.1f}%')


def main():
    px, qv = load()
    print(f'panel: {px.shape[1]} symbols x {px.shape[0]} days')
    ret = px.pct_change()

    # point-in-time liquidity: trailing 30d quote volume, top-N each date
    trvol = qv.rolling(TRAILING_VOL).sum()
    liq_rank = trvol.rank(axis=1, ascending=False, method='first')
    liquid = (liq_rank <= TOP_LIQUID).astype(float)  # 1 if in top-N that date

    stats(ret.mean(axis=1), 'B&H equal-weight ALL (gross)')

    for lb in [7, 14, 28]:
        mom = px.pct_change(lb)
        rank = mom.rank(axis=1, ascending=True, method='first')  # 1 = biggest loser
        for K in [5, 10]:
            hold = ((rank <= K) & (liquid > 0)).astype(float)
            denom = hold.sum(axis=1).replace(0, np.nan)
            w = hold.div(denom, axis=0).shift(1)
            strat = (w * ret).sum(axis=1)
            turn = w.diff().abs().sum(axis=1)
            net = strat - turn * ONE_SIDE_BP / 1e4
            stats(net, f'REVERSAL {lb}d bottom{K}, pt-liquid top{TOP_LIQUID} (net)')


if __name__ == '__main__':
    main()
