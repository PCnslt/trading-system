#!/usr/bin/env python3
"""Llorente–Michaely–Saar–Wang 2002 volume-return interaction classifier (queue strat-20260831-2).

Paper: "Dynamic Volume-Return Relation of Individual Stocks", RFS 15(4):1005-1047.
Per-stock time-series regression:  R_t = C0 + C1*R_{t-1} + C2*(V_{t-1}*R_{t-1}) + eps
  V = detrended log volume (log volume minus trailing 252d mean).
  C2 > 0 => informed/speculative trading  => a high-volume move CONTINUES (momentum).
  C2 < 0 => hedging-driven               => the move REVERSES (fade).

Long-only translation (what a $700 no-short account can trade):
  * Continuation leg: high-C2 names, high-volume UP day   -> LONG next open, hold 1/3/5d.
  * Fade leg:         low-C2  names, high-volume DOWN day -> LONG next open, hold 1/3/5d.
  Compare each to its unconditional counterpart (all up / all down moves) to measure the
  classifier's ADDED value, and run the directional sanity check (high-C2 up must
  continue MORE than low-C2 up; low-C2 down must bounce MORE than high-C2 down).

Universe: bot.live_equities.STOCKS (190 liquid large-caps, ~20y) — the same liquid
universe rvol_backtest.py used for the cross-sectional RVOL test. No $2-50 price filter
(this is a cross-sectional classifier test, not the RH whole-share reality).
Honest fills: 5 bps/side primary, 10 bps/side 2x stress. IS/OOS split 2022-01-01.
"""
from __future__ import annotations

import io, os, sys, json, argparse
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

from bot.live_equities import STOCKS

load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
OOS_FROM = '2022-01-01'
WIN = 504          # rolling regression window (2y)
STEP = 21          # re-estimate C2 monthly (it is a slow structural property)
MOVE = 0.02        # directional move threshold
RVOL_MOVE = 1.5    # "high volume" on the move day
COSTS = (0.0005, 0.0010)
HORIZONS = (1, 3, 5)


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < WIN + 252:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        return df
    except Exception:
        return None


def estimate_c2(df):
    """Rolling per-stock C2 (the V_{t-1}*R_{t-1} coefficient), monthly re-estimation."""
    ret = df['close'].pct_change()
    logvol = np.log(df['volume'].clip(lower=1.0))
    V = logvol - logvol.rolling(252).mean()
    X1 = ret.shift(1)
    X2 = (V.shift(1) * ret.shift(1))
    Y = ret
    n = len(df)
    c2 = pd.Series(np.nan, index=df.index)
    ends = list(range(WIN - 1, n, STEP))
    for end in ends:
        s = end - WIN + 1
        yy = Y.iloc[s:end + 1].values
        x1 = X1.iloc[s:end + 1].values
        x2 = X2.iloc[s:end + 1].values
        mask = np.isfinite(yy) & np.isfinite(x1) & np.isfinite(x2)
        if mask.sum() < 50:
            continue
        X = np.column_stack([np.ones(mask.sum()), x1[mask], x2[mask]])
        try:
            beta, *_ = np.linalg.lstsq(X, yy[mask], rcond=None)
        except Exception:
            continue
        c2.iloc[end] = beta[2]
    return c2.ffill()


def build_signal_frame(df, c2):
    """Return a frame indexed by ENTRY day t with move/rvol/c2 as of t-1 and fwd returns."""
    ret = df['close'].pct_change()
    rvol = df['volume'] / df['volume'].rolling(20).mean().shift(1)
    f = pd.DataFrame(index=df.index)
    f['move'] = ret.shift(1)          # yesterday's move (ret[t-1])
    f['rvol_move'] = rvol.shift(1)    # yesterday's relative volume
    f['c2'] = c2.shift(1)             # C2 known as of yesterday (<= t-1)
    f['entry'] = df['open']
    for H in HORIZONS:
        f[f'fwd{H}'] = df['close'].shift(-H) / df['open'] - 1.0
    f = f[f['move'].notna() & f['rvol_move'].notna()]
    return f


def stats(rets):
    r = np.asarray([x for x in rets if x == x and np.isfinite(x)], dtype=float)
    if len(r) == 0:
        return None
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    pf = w / l if l > 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 and len(r) > 1 else 0.0
    return {'n': int(len(r)), 'pf': round(pf, 3), 'win': round(float((r > 0).mean()), 3),
            'avg_bp': round(float(r.mean() * 1e4), 1), 't': round(float(t), 2)}


def fmt(s):
    if not s or s['n'] == 0:
        return '       n/a'
    return (f"n={s['n']:>6} PF={s['pf']:>6.3f} win={s['win']*100:>5.1f}% "
            f"avg={s['avg_bp']:>7.1f}bp t={s['t']:>5.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    syms = list(STOCKS)
    if a.limit:
        syms = syms[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols…', flush=True)
    with ThreadPoolExecutor(max_workers=24) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}   {min(d.index[0] for d in data.values()).date()}'
          f' .. {max(d.index[-1] for d in data.values()).date()}\n', flush=True)

    # estimate C2 per stock and build signal frames
    print('estimating rolling C2 per stock (2y window, monthly re-estimate)…', flush=True)
    frames = {}
    c2_stats = []
    for sym, df in data.items():
        c2 = estimate_c2(df)
        frames[sym] = build_signal_frame(df, c2)
        vals = c2.dropna()
        c2_stats.append((sym, float((vals > 0).mean()), float(vals.median())))
    pos = [s for s, p, m in c2_stats if p >= 0.5]
    print(f'  C2 sign distribution: {len(pos)}/{len(c2_stats)} names majority C2>0 '
          f'(median of per-stock median C2 = '
          f'{np.median([m for _, _, m in c2_stats]):+.4f})\n', flush=True)

    allf = pd.concat(frames.values())
    allf['is_oos'] = np.where(allf.index < pd.Timestamp(OOS_FROM), 'IS', 'OOS')
    up = allf[(allf['move'] >= MOVE) & (allf['rvol_move'] >= RVOL_MOVE)]
    dn = allf[(allf['move'] <= -MOVE) & (allf['rvol_move'] >= RVOL_MOVE)]
    up_hi = up[up['c2'] > 0]
    up_lo = up[up['c2'] < 0]
    dn_hi = dn[dn['c2'] > 0]
    dn_lo = dn[dn['c2'] < 0]

    out = {'universe_n': len(data), 'c2_majority_positive': len(pos),
           'c2_median_of_medians': float(np.median([m for _, _, m in c2_stats]))}

    print('=' * 92)
    print('DIRECTIONAL SANITY CHECK (gross, forward H-day return, bp) — does C2 sort correctly?')
    print('=' * 92)
    for H in HORIZONS:
        def m(r):
            return r[f'fwd{H}'].mean() * 1e4 if len(r) else float('nan')
        print(f'  H={H}d  UP-moves:  high-C2 {m(up_hi):+7.1f}bp (n={len(up_hi):>5})  '
              f'low-C2 {m(up_lo):+7.1f}bp (n={len(up_lo):>5})  -> continuation if hi>lo')
        print(f'         DOWN-moves: high-C2 {m(dn_hi):+7.1f}bp (n={len(dn_hi):>5})  '
              f'low-C2 {m(dn_lo):+7.1f}bp (n={len(dn_lo):>5})  -> reversal   if lo>hi')

    print('\n' + '=' * 92)
    print('TRADEABLE LONG-ONLY LEGS (net of cost, next-open entry -> close exit)')
    print('=' * 92)
    for bps in COSTS:
        print(f'\n  @{bps*1e4:.0f}bps/side:')
        for H in HORIZONS:
            def net(sub):
                return (sub[f'fwd{H}'] + 1) * (1 - bps) / (1 + bps) - 1.0
            for lbl, sub, is_cont in (('MOMENTUM high-C2 up-move', up_hi, True),
                                      ('FADE      low-C2 down-move', dn_lo, False)):
                r = net(sub).values
                isr = net(sub[sub['is_oos'] == 'IS']).values
                oor = net(sub[sub['is_oos'] == 'OOS']).values
                out[f'{lbl.split()[0].lower()}_H{H}_{bps}'] = {'all': stats(r), 'is': stats(isr), 'oos': stats(oor)}
            # unconditional comparison
            r_up = net(up).values
            r_dn = net(dn).values
            out[f'uncond_up_H{H}_{bps}'] = {'all': stats(r_up),
                                            'is': stats(net(up[up['is_oos'] == 'IS']).values),
                                            'oos': stats(net(up[up['is_oos'] == 'OOS']).values)}
            out[f'uncond_dn_H{H}_{bps}'] = {'all': stats(r_dn),
                                            'is': stats(net(dn[dn['is_oos'] == 'IS']).values),
                                            'oos': stats(net(dn[dn['is_oos'] == 'OOS']).values)}
            print(f'    H={H}d  momentum(hi-C2 up)  {fmt(out[f"momentum_H{H}_{bps}"]["all"])}   '
                  f'IS {fmt(out[f"momentum_H{H}_{bps}"]["is"])}   OOS {fmt(out[f"momentum_H{H}_{bps}"]["oos"])}')
            print(f'    H={H}d  fade(lo-C2 down)    {fmt(out[f"fade_H{H}_{bps}"]["all"])}   '
                  f'IS {fmt(out[f"fade_H{H}_{bps}"]["is"])}   OOS {fmt(out[f"fade_H{H}_{bps}"]["oos"])}')
            print(f'    H={H}d  unconditional up    {fmt(out[f"uncond_up_H{H}_{bps}"]["all"])}   '
                  f'OOS {fmt(out[f"uncond_up_H{H}_{bps}"]["oos"])}')
            print(f'    H={H}d  unconditional down  {fmt(out[f"uncond_dn_H{H}_{bps}"]["all"])}   '
                  f'OOS {fmt(out[f"uncond_dn_H{H}_{bps}"]["oos"])}')

    json.dump(out, open(os.path.join(_ROOT, 'research', 'llorente_interaction_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/llorente_interaction_results.json')


if __name__ == '__main__':
    main()
