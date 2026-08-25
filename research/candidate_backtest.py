#!/usr/bin/env python3
"""Backtest the two top RH-feasible candidates from the 2026-08-25 edge research.

Sources: research/edge-research-20260825/PRACTITIONER_CODE_CANDIDATES.md

#1 MIND-THE-GAP (Quantitativo, https://www.quantitativo.com/p/mind-the-gap)
   universe : US stocks whose OPEN is above the 200-day SMA
   entry    : at the OPEN, if the open gapped DOWN vs prev close by more than a threshold
              (author deliberately withheld the threshold -> we SWEEP it here)
   cap      : max N names/day; if more qualify, take the LEAST VOLATILE
   exit     : the NEXT OPEN
   reported : 22.9%/yr, Sharpe 1.66, 55.6% win, +0.11%/trade NET of 10bp, 2010-2024
   decay    : author says pre-2010 was materially better and excluded it

#2 BROKEN-ARROW (Alvarez, buy the -15% close, exit next open)
   setup    : Close > 40-day MA AND 40-day MA rising
   trigger  : yesterday was a setup AND today closes down >= X% (15/20/25 tested)
   entry    : that day's CLOSE (~15:55)
   exit     : the NEXT OPEN
   reported : top-1000 +0.77%/trade 56% win (412 trades); S&P500 +0.66%/60%

Both are LONG-ONLY, need no stop, and execute only inside regular hours -> the cheap
5.9bp lane. Costs swept because our measured cost differs by time of day:
  09:30-09:45 sell leg  : being measured by cron 478789a67115 (not yet in)
  15:45-16:00 buy leg   : 1.9bp half-spread MEASURED 2026-08-25
  mid-session           : 3.6/3.1bp half
Honest metrics only: per-trade expectancy + t-stat, IS/OOS split. Portfolio-level
compounding is reported ONLY for Mind-the-Gap, where the daily N-name cap makes a
non-overlapping equal-weight portfolio well defined.
"""
from __future__ import annotations
import io, os, sys, json, argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
import boto3
import numpy as np
import pandas as pd
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PRICE_LO, PRICE_HI = 2.0, 50.0          # Robinhood whole-share reality at ~$105/position
OOS_FROM = '2022-01-01'


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        pc = df['close'].shift(1)
        df['gap'] = df['open'] / pc - 1.0                      # open vs prev close
        df['sma200'] = df['close'].rolling(200).mean()
        df['ma40'] = df['close'].rolling(40).mean()
        df['ma40_rising'] = df['ma40'] > df['ma40'].shift(1)
        df['ret1'] = df['close'] / pc - 1.0                    # today's close-to-close
        df['vol20'] = df['close'].pct_change().rolling(20).std()
        df['dollar_vol'] = (df['close'] * df['volume']).rolling(20).mean()
        df['o2o'] = df['open'].shift(-1) / df['open'] - 1.0    # open -> next open
        df['c2o'] = df['open'].shift(-1) / df['close'] - 1.0   # close -> next open
        return df
    except Exception:
        return None


def stats(r, cost_bp):
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 30:
        return None
    net = r - cost_bp / 1e4
    w, l = net[net > 0], net[net <= 0]
    pf = (w.sum() / -l.sum()) if l.sum() < 0 else float('inf')
    t = net.mean() / (net.std(ddof=1) / np.sqrt(len(net))) if net.std() > 0 else 0.0
    return {'n': len(net), 'PF': round(pf, 3), 'win%': round(100 * len(w) / len(net), 1),
            'avg_bp': round(net.mean() * 1e4, 1), 't': round(float(t), 2)}


def mind_the_gap(data, thresh, cap, cost_bp):
    """Daily N-name cap, least-volatile first -> non-overlapping equal-weight portfolio."""
    by_day = defaultdict(list)
    for sym, df in data.items():
        m = ((df['gap'] <= -thresh) & (df['open'] > df['sma200'])
             & df['close'].between(PRICE_LO, PRICE_HI) & df['o2o'].notna()
             & (df['dollar_vol'] > 5e6))
        sub = df.loc[m, ['o2o', 'vol20']]
        for d, row in sub.iterrows():
            if not np.isnan(row['vol20']):
                by_day[d].append((row['vol20'], row['o2o']))
    trades, day_rets = [], {}
    for d, rows in by_day.items():
        rows.sort(key=lambda x: x[0])          # LEAST volatile first
        picked = [r for _, r in rows[:cap]]
        trades += picked
        day_rets[d] = float(np.mean(picked)) - cost_bp / 1e4
    return trades, day_rets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=400)
    a = ap.parse_args()
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols…', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}   span {min(d.index[0] for d in data.values()).date()}'
          f' .. {max(d.index[-1] for d in data.values()).date()}\n', flush=True)
    out = {}

    print('=' * 74)
    print('#1 MIND-THE-GAP  (buy gap-down open above 200SMA, sell NEXT open)')
    print('=' * 74)
    print('threshold sweep (the author withheld his) — cap 7 names/day, cost 6bp\n')
    print(f'{"gap<=":>7}{"trades":>8}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}   '
          f'{"days":>6}{"day_avg_bp":>11}{"OOS PF":>8}{"OOS avg":>9}{"OOS t":>7}')
    for th in (0.01, 0.02, 0.03, 0.04, 0.05, 0.07):
        tr, dr = mind_the_gap(data, th, 7, 6.0)
        s = stats(tr, 6.0)
        if not s:
            continue
        oos = [v for d, v in dr.items() if str(d.date()) >= OOS_FROM]
        so = stats([x + 6.0 / 1e4 for x in oos], 6.0)
        dv = np.mean(list(dr.values())) * 1e4 if dr else float('nan')
        print(f'{-th*100:>6.0f}%{s["n"]:>8}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.1f}'
              f'{s["t"]:>7.2f}   {len(dr):>6}{dv:>11.1f}'
              f'{(so["PF"] if so else float("nan")):>8.3f}'
              f'{(so["avg_bp"] if so else float("nan")):>9.1f}'
              f'{(so["t"] if so else float("nan")):>7.2f}')
        out[f'mtg_{th}'] = {'all': s, 'oos_days': so}

    print('\ncost sensitivity at the best-looking threshold (3%, cap 7):')
    print(f'{"cost_bp":>8}{"PF":>7}{"avg_bp":>9}{"t":>7}')
    for c in (6.0, 10.0, 15.0, 20.0):
        tr, _ = mind_the_gap(data, 0.03, 7, c)
        s = stats(tr, c)
        if s:
            print(f'{c:>8.0f}{s["PF"]:>7.3f}{s["avg_bp"]:>9.1f}{s["t"]:>7.2f}')

    print('\n' + '=' * 74)
    print('#2 BROKEN-ARROW  (buy close of a big down day above rising 40MA, sell NEXT open)')
    print('=' * 74)
    print(f'{"drop":>6}{"trades":>8}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}   '
          f'{"OOS n":>6}{"OOS avg":>9}{"OOS t":>7}')
    for drop in (0.05, 0.08, 0.10, 0.15, 0.20):
        rets, oos = [], []
        for sym, df in data.items():
            setup = (df['close'].shift(1) > df['ma40'].shift(1)) & df['ma40_rising'].shift(1)
            m = (setup & (df['ret1'] <= -drop) & df['close'].between(PRICE_LO, PRICE_HI)
                 & df['c2o'].notna() & (df['dollar_vol'] > 5e6))
            sub = df.loc[m, 'c2o']
            rets += list(sub.values)
            oos += list(sub[sub.index >= OOS_FROM].values)
        s = stats(rets, 6.0)
        so = stats(oos, 6.0)
        if not s:
            continue
        print(f'{-drop*100:>5.0f}%{s["n"]:>8}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.1f}'
              f'{s["t"]:>7.2f}   {(so["n"] if so else 0):>6}'
              f'{(so["avg_bp"] if so else float("nan")):>9.1f}'
              f'{(so["t"] if so else float("nan")):>7.2f}')
        out[f'ba_{drop}'] = {'all': s, 'oos': so}

    json.dump(out, open(os.path.join(_ROOT, 'research', 'candidate_backtest_results.json'), 'w'),
              indent=1, default=str)
    print('\nnote: MTG day_avg_bp is the equal-weight PORTFOLIO return per trading day '
          '(non-overlapping); per-trade columns pool all picks.')


if __name__ == '__main__':
    main()
