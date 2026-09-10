#!/usr/bin/env python3
"""Crypto momentum scan on existing daily history (crypto-hist/<sym>/daily.json).

Tests the documented crypto-specific momentum effect (Liu-Tsyvinski): short
lookback time-series momentum (3/7/14/28d) + cross-sectional momentum, with
HONEST Binance.US spot costs (0.1%/side = 10bp per turnover unit).

Read-only research. No orders.
"""
import json
import numpy as np
import pandas as pd
import boto3

BUCKET = 'trading-datalake-920641308584'
REGION = 'us-east-1'
ONE_SIDE_BP = 10.0  # 0.1% Binance.US spot fee per side


def load_panel():
    s3 = boto3.client('s3', region_name=REGION)
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix='crypto-hist/')
    keys = [o['Key'] for o in resp.get('Contents', []) if o['Key'].endswith('daily.json')]
    panel = {}
    for k in keys:
        sym = k.split('/')[1]
        try:
            data = json.loads(s3.get_object(Bucket=BUCKET, Key=k)['Body'].read())
            df = pd.DataFrame(data['bars'])
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            panel[sym] = df['close']
        except Exception as e:
            print(f'{sym}: skip {e!r}')
    px = pd.DataFrame(panel).sort_index().ffill()
    return px


def stats(r, name):
    r = r.dropna()
    if len(r) < 30:
        print(f'{name}: insufficient data ({len(r)})')
        return
    n = len(r)
    mean = r.mean()
    std = r.std()
    t = mean / (std / np.sqrt(n)) if std > 0 else 0.0
    ann = (1 + r).prod() ** (365 / n) - 1  # daily -> annualized (crypto trades 365d)
    cump = (1 + r).cumprod()
    mdd = (cump / cump.cummax() - 1).min()
    wins = (r > 0).mean()
    pf = r[r > 0].sum() / abs(r[r < 0].sum()) if r[r < 0].sum() != 0 else np.inf
    print(f'{name:34s} n={n:5d} mean={mean*1e4:6.2f}bp/d t={t:5.2f} '
          f'ann={ann*100:6.1f}% PF={pf:4.2f} win={wins*100:4.1f}% maxDD={mdd*100:6.1f}%')


def main():
    px = load_panel()
    print(f'symbols={px.shape[1]} days={px.shape[0]} range={px.index[0].date()}..{px.index[-1].date()}')
    ret = px.pct_change()

    # ---- benchmark: equal-weight buy & hold (long-only, gross) ----
    bnh = ret.mean(axis=1)
    stats(bnh, 'benchmark: equal-weight B&H (gross)')

    # ---- time-series momentum (long/short) ----
    for lb in [3, 7, 14, 28]:
        sig = np.sign(px.pct_change(lb))       # signal @ close t
        pos = sig.shift(1)                      # held during day t (set @ close t-1)
        strat = (pos * ret).mean(axis=1)        # equal-weight across symbols
        turn = pos.diff().abs().mean(axis=1)    # turnover in position units
        net = strat - turn * ONE_SIDE_BP / 1e4
        stats(net, f'TS-mom {lb}d long/short (net {ONE_SIDE_BP:.0f}bp/side)')

    # ---- time-series momentum (long/flat, long-only) ----
    for lb in [3, 7, 14, 28]:
        sig = (px.pct_change(lb) > 0).astype(float)   # long if past return > 0
        pos = sig.shift(1)
        strat = (pos * ret).mean(axis=1)
        turn = pos.diff().abs().mean(axis=1)
        net = strat - turn * ONE_SIDE_BP / 1e4
        stats(net, f'TS-mom {lb}d long/flat (net)')

    # ---- cross-sectional momentum (long top-K, equal weight, rebalance daily) ----
    for lb in [7, 14, 28]:
        for K in [3, 5]:
            mom = px.pct_change(lb)
            rank = mom.rank(axis=1, ascending=False, method='first')
            hold = (rank <= K).astype(float)
            # equal weight the held set; positions set @ close t, earn day t+1
            w = hold.div(hold.sum(axis=1), axis=0).shift(1)
            strat = (w * ret).sum(axis=1)
            turn = w.diff().abs().sum(axis=1)
            net = strat - turn * ONE_SIDE_BP / 1e4
            stats(net, f'XS-mom {lb}d top{K} long (net)')

    # ---- per-symbol time-series 7d long/short (which coins drive it?) ----
    print('\nper-symbol TS-mom 7d long/short (net):')
    sig = np.sign(px.pct_change(7))
    pos = sig.shift(1)
    strat = pos * ret
    turn = pos.diff().abs()
    for c in px.columns:
        net = strat[c] - turn[c] * ONE_SIDE_BP / 1e4
        net = net.dropna()
        if len(net) < 30:
            continue
        t = net.mean() / (net.std() / np.sqrt(len(net))) if net.std() > 0 else 0
        print(f'  {c:10s} n={len(net):5d} mean={net.mean()*1e4:6.2f}bp/d t={t:5.2f}')


if __name__ == '__main__':
    main()
