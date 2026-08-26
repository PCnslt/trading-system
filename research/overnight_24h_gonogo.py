#!/usr/bin/env python3
"""OVERNIGHT / 24H-SESSION GO-NO-GO against the MEASURED extended-session cost floor.

WHY: the 2026-08-25 cost study (research/OVERNIGHT_COST_FEASIBILITY.md) measured the
extended-session round-trip on the sub-$50 RH universe at **51.5 bp** on a real $250
clip vs **14.4 bp** regular-hours (3.42x).  The 20:00-04:00 window has NO obtainable
spread/volume data, and RH stops are RTH-ONLY (an overnight position is unstopped).

QUESTION THIS SCRIPT ANSWERS: does ANY overnight-hold edge already in this repo clear
the 51.5 bp extended-session round trip?  We test the three candidate families and
report NET PF after cost at the RTH floor (14.4 bp), the extended floor (51.5 bp) and a
2x-cost stress of each (28.8 / 103 bp), with an IS/OOS split (OOS from 2022-01-01).

Candidate families (all LONG-only, sub-$50 whole-share feasible):
  1. CLOSE-TO-OPEN  (overnight gap capture): buy the close[t], sell the open[t+1].
     Variants ALL / DOWNDAY / NEARLOW / DOWN3 / HIGHVOL / RSI2 (the live signal, held
     overnight).  This is the direct "overnight gap" candidate.
  2. GAP-FADE (Mind-the-Gap): buy a gap-down OPEN above the 200SMA, sell the NEXT open.
     An open-to-open hold — carries the full overnight block + the next session.
  3. BROKEN-ARROW: buy the close of a big down day above a rising 40MA, sell next open.
     The strongest close-to-open edge in the repo (Lane 47, +34 bp OOS at -8%).

Honest fills: round-trip bp is deducted from every trade's return.  No compounded equity
curve — trades overlap across symbols with no sizing model, so per-trade expectancy +
t-stat and PF are the honest metrics (same convention as the repo's close_to_open and
candidate backtests).
"""
from __future__ import annotations
import io, os, sys, json, argparse
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
import boto3
import numpy as np
import pandas as pd
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PRICE_LO, PRICE_HI = 2.0, 50.0
OOS_FROM = '2022-01-01'

# Measured floors (research/OVERNIGHT_COST_FEASIBILITY.md, overnight_cost_floor.json):
#   14.4 bp RTH round trip, 51.5 bp extended round trip (median, $250 clip).
# Plus the cheap-RTH mid-session reference (5.9 bp) and 2x-cost stress of each floor.
COSTS_BP = [6.0, 14.4, 28.8, 51.5, 103.0]


def rsi(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50.0)


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 260:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        pc = df['close'].shift(1)
        df['rsi2'] = rsi(df['close'], 2)
        df['sma200'] = df['close'].rolling(200).mean()
        df['ma40'] = df['close'].rolling(40).mean()
        df['ma40_rising'] = df['ma40'] > df['ma40'].shift(1)
        df['vol20'] = df['volume'].rolling(20).mean()
        df['dv20'] = (df['close'] * df['volume']).rolling(20).mean()
        df['rng_pos'] = (df['close'] - df['low']) / (df['high'] - df['low']).replace(0, np.nan)
        df['dn'] = (df['close'] < pc).astype(int)
        df['dn3'] = df['dn'].rolling(3).sum()
        df['gap'] = df['open'] / pc - 1.0                    # open vs prev close
        df['ret1'] = df['close'] / pc - 1.0                  # close-to-close
        df['c2o'] = df['open'].shift(-1) / df['close'] - 1.0 # close[t] -> open[t+1]
        df['o2o'] = df['open'].shift(-1) / df['open'] - 1.0  # open[t] -> open[t+1]
        return df.dropna(subset=['sma200', 'c2o', 'o2o'])
    except Exception:
        return None


def c2o_masks(df):
    """Family 1: close-to-open variants.  tradeable = in price band."""
    tradeable = df['close'].between(PRICE_LO, PRICE_HI)
    return {
        'C2O_ALL':     tradeable,
        'C2O_DOWNDAY': tradeable & (df['dn'] == 1),
        'C2O_RSI2':    tradeable & (df['rsi2'] < 5) & (df['close'] > df['sma200']),
        'C2O_NEARLOW': tradeable & (df['rng_pos'] < 0.25),
        'C2O_DOWN3':   tradeable & (df['dn3'] == 3),
        'C2O_HIGHVOL': tradeable & (df['dn'] == 1) & (df['volume'] > 1.5 * df['vol20']),
    }


def gap_fade_returns(df, thresh):
    m = ((df['gap'] <= -thresh) & (df['open'] > df['sma200'])
         & df['close'].between(PRICE_LO, PRICE_HI) & (df['dv20'] > 5e6))
    return df.loc[m, 'o2o']


def broken_arrow_returns(df, drop):
    setup = (df['close'].shift(1) > df['ma40'].shift(1)) & df['ma40_rising'].shift(1)
    m = (setup & (df['ret1'] <= -drop) & df['close'].between(PRICE_LO, PRICE_HI)
         & (df['dv20'] > 5e6))
    return df.loc[m, 'c2o']


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
            'avg_bp': round(net.mean() * 1e4, 2), 't': round(float(t), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=400)
    ap.add_argument('--oos-from', default=OOS_FROM)
    a = ap.parse_args()
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols…', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)} symbols   OOS from {a.oos_from}\n', flush=True)

    # ---- collect raw returns per candidate (IS and OOS pooled) ----
    # key -> (is_returns_list, oos_returns_list) as python lists of floats
    pooled = {}

    def add(key, series):
        if len(series) == 0:
            return
        cut = series.index < a.oos_from
        pooled.setdefault(key, [[], []])
        pooled[key][0] += list(series[cut].values)
        pooled[key][1] += list(series[~cut].values)

    for sym, df in data.items():
        for name, m in c2o_masks(df).items():
            add(name, df.loc[m, 'c2o'])
        for th in (0.01, 0.03, 0.04, 0.07):
            add(f'GAPFADE_{-int(th*100)}', gap_fade_returns(df, th))
        for drop in (0.05, 0.08, 0.10):
            add(f'BROKENARROW_{-int(drop*100)}', broken_arrow_returns(df, drop))

    # ---- report ----
    span = f'{min(d.index[0] for d in data.values()).date()} .. {max(d.index[-1] for d in data.values()).date()}'
    print(f'OVERNIGHT / 24H GO-NO-GO vs measured cost floor   span {span}\n')
    print('costs (bp round-trip): 6.0 = cheap RTH · 14.4 = RTH floor · 28.8 = 2x RTH · '
          '51.5 = EXTENDED floor · 103 = 2x extended\n')
    out = {}
    for cost in COSTS_BP:
        print(f'--- cost {cost:.1f} bp round-trip ---')
        print(f'{"candidate":18}{"n":>8}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}   '
              f'{"OOS n":>7}{"OOS PF":>7}{"OOS avg":>9}{"OOS t":>7}')
        rows = {}
        for key in sorted(pooled):
            isr = np.array(pooled[key][0]); oor = np.array(pooled[key][1])
            s = stats(isr, cost); so = stats(oor, cost)
            if s is None and so is None:
                continue
            print(f'{key:18}{(s["n"] if s else 0):>8}'
                  f'{(s["PF"] if s else float("nan")):>7.3f}'
                  f'{(s["win%"] if s else float("nan")):>7.1f}'
                  f'{(s["avg_bp"] if s else float("nan")):>9.2f}'
                  f'{(s["t"] if s else float("nan")):>7.2f}   '
                  f'{(so["n"] if so else 0):>7}'
                  f'{(so["PF"] if so else float("nan")):>7.3f}'
                  f'{(so["avg_bp"] if so else float("nan")):>9.2f}'
                  f'{(so["t"] if so else float("nan")):>7.2f}')
            rows[key] = {'is': s, 'oos': so}
        out[cost] = rows
        print()

    json.dump({'costs': out, 'oos_from': a.oos_from, 'n_symbols': len(data),
               'cost_floor_rth_bp': 14.4, 'cost_floor_extended_bp': 51.5},
              open(os.path.join(_ROOT, 'research', 'overnight_24h_gonogo_results.json'), 'w'),
              indent=1, default=str)
    print('wrote research/overnight_24h_gonogo_results.json')


if __name__ == '__main__':
    main()
