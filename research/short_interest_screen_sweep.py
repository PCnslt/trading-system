#!/usr/bin/env python3
"""Sensitivity sweep for the short-interest screen: does OOS PF move monotonically
as we exclude more of the most-shorted names? Reuses SI cache + engine."""
from __future__ import annotations
import io, os, sys, json, time
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
import boto3
import numpy as np
import pandas as pd
import stock_mr_engine as E
from short_interest_screen import (
    load_universe, load_bars, load_si, build_screen, snapshot_for,
    rsi2_trades, broken_arrow_trades, stats, oos, BPS)

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
OOS_FROM = pd.Timestamp('2022-01-01')


def apply_screen_frac(trades, keys, pct, si, frac):
    """frac = fraction of names to EXCLUDE by SIR (0 = none)."""
    if frac <= 0:
        return trades
    q = 1.0 - frac
    kept = []
    for t in trades:
        s = snapshot_for(keys, t['entry_date'])
        if s is None or s not in si or t['symbol'] not in si[s]:
            kept.append(t)
            continue
        vals = np.array(list(si[s].values()))
        if len(vals) < 20:
            kept.append(t)
            continue
        thr = float(np.percentile(vals, q * 100))
        if si[s][t['symbol']] >= thr:
            continue
        kept.append(t)
    return kept


def main():
    t0 = time.time()
    syms = load_universe()
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load_bars(x, s3), syms)) if d is not None}
    si = load_si(set(data.keys()))
    keys, pct, si = build_screen(si)

    lanes = {'RSI2': rsi2_trades(data), 'BROKEN_ARROW': broken_arrow_trades(data)}
    cuts = [0.0, 0.05, 0.10, 0.20, 0.30, 0.50]

    print(f'{"lane":>14} {"excl%":>6} {"n_OOS":>7} {"PF_OOS":>8} {"win%":>6} {"avg_bp":>8} {"dPF":>7}')
    for lane, trades in lanes.items():
        base = stats(oos(trades))
        for f in cuts:
            kept = apply_screen_frac(trades, keys, pct, si, f)
            s = stats(oos(kept))
            d = (s['PF'] - base['PF']) if s['n'] else float('nan')
            print(f'{lane:>14} {f*100:>5.0f}% {s["n"]:>7} {s["PF"]:>8.3f} '
                  f'{s["win%"]:>5.1f}% {s["avg_bp"]:>8.1f} {d:>+7.3f}')
        print()

    # correlation: mean OOS return of EXCLUDED (top-SIR) names vs included
    print('=== expectancy of EXCLUDED (most-shorted) names vs KEPT, OOS ===')
    for lane, trades in lanes.items():
        base = oos(trades)
        for f in [0.10, 0.20]:
            excl = [t for t in base if _is_top(t, keys, pct, si, f)]
            kept = [t for t in base if not _is_top(t, keys, pct, si, f)]
            se = stats(excl); sk = stats(kept)
            print(f'{lane} excl-top-{f*100:.0f}%:  EXCLUDED n={se["n"]} avg={se["avg_bp"]}bp  '
                  f'KEPT n={sk["n"]} avg={sk["avg_bp"]}bp')
    print(f'\ndone {time.time()-t0:.0f}s')


def _is_top(t, keys, pct, si, frac):
    s = snapshot_for(keys, t['entry_date'])
    if s is None or s not in si or t['symbol'] not in si[s]:
        return False
    vals = np.array(list(si[s].values()))
    if len(vals) < 20:
        return False
    thr = float(np.percentile(vals, (1 - frac) * 100))
    return si[s][t['symbol']] >= thr


if __name__ == '__main__':
    main()
