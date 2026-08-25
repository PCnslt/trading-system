#!/usr/bin/env python3
"""CLOSE-TO-OPEN (buy at close, sell next open) — the owner's pattern B.

WHY RE-TEST: the 2026-08-24 study rejected this as "MOC entry refinement" because it
assumed a market-on-close order and 5-15bp of MOC slippage. But the trade the owner
describes needs NO MOC order: a plain market BUY a few minutes before 16:00 and a plain
market SELL at 09:30 next day are BOTH regular-hours orders, which Robinhood supports.

MEASURED COSTS (2026-08-25, live RH L2 books, $250 clip):
    regular hours mid-session   5.9 bp round-trip
    16:00-16:05 (auction window) 38.8 bp
    pre-market                  50.7 bp
    evening 16:05-20:00         71.3 bp
So cost depends on HOW CLOSE to the bell we transact. We therefore sweep cost from 6 bp
(clean RTH) to 40 bp (transacting into the auction) and report where each variant dies.

Variants tested (all LONG-ONLY, whole-share, sub-$50 = Robinhood-feasible):
  ALL          every name every night (baseline: is there an overnight premium at all?)
  DOWNDAY      buy only if today closed down
  RSI2         buy only if RSI(2) < 5 and close > SMA200  (our live signal, held overnight)
  NEARLOW      buy only if close is in the bottom 25% of today's range (weak close)
  DOWN3        buy only after 3 consecutive down closes
  HIGHVOL      DOWNDAY + today's volume > 1.5x its 20d average

Honest metrics only: per-trade expectancy + t-stat. No compounded equity curve (trades
overlap across symbols with no sizing model, so an equity curve would be meaningless).
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
COSTS_BP = [6.0, 10.0, 15.0, 20.0, 40.0]
PRICE_LO, PRICE_HI = 2.0, 50.0


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
        df['rsi2'] = rsi(df['close'], 2)
        df['sma200'] = df['close'].rolling(200).mean()
        df['vol20'] = df['volume'].rolling(20).mean()
        df['rng_pos'] = (df['close'] - df['low']) / (df['high'] - df['low']).replace(0, np.nan)
        df['dn'] = (df['close'] < df['close'].shift(1)).astype(int)
        df['dn3'] = df['dn'].rolling(3).sum()
        # THE TRADE: buy at close of T, sell at open of T+1
        df['c2o'] = df['open'].shift(-1) / df['close'] - 1.0
        return df.dropna(subset=['sma200', 'c2o'])
    except Exception:
        return None


def masks(df):
    tradeable = (df['close'].between(PRICE_LO, PRICE_HI))
    return {
        'ALL':     tradeable,
        'DOWNDAY': tradeable & (df['dn'] == 1),
        'RSI2':    tradeable & (df['rsi2'] < 5) & (df['close'] > df['sma200']),
        'NEARLOW': tradeable & (df['rng_pos'] < 0.25),
        'DOWN3':   tradeable & (df['dn3'] == 3),
        'HIGHVOL': tradeable & (df['dn'] == 1) & (df['volume'] > 1.5 * df['vol20']),
    }


def stats(r, cost_bp):
    if len(r) < 30:
        return None
    net = r - cost_bp / 1e4
    w, l = net[net > 0], net[net <= 0]
    pf = (w.sum() / -l.sum()) if l.sum() < 0 else float('inf')
    t = net.mean() / (net.std(ddof=1) / np.sqrt(len(net))) if net.std() > 0 else 0.0
    return {'n': len(net), 'PF': round(pf, 3), 'win%': round(100 * len(w) / len(net), 1),
            'avg_bp': round(net.mean() * 1e4, 2), 'med_bp': round(float(np.median(net)) * 1e4, 2),
            't': round(float(t), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=400)
    ap.add_argument('--oos-from', default='2022-01-01')
    a = ap.parse_args()
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols…', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)} symbols\n', flush=True)

    pooled, pooled_is, pooled_oos = {}, {}, {}
    for sym, df in data.items():
        for name, m in masks(df).items():
            r = df.loc[m, 'c2o'].values
            pooled.setdefault(name, []).append(r)
            cut = df.index < a.oos_from
            pooled_is.setdefault(name, []).append(df.loc[m & cut, 'c2o'].values)
            pooled_oos.setdefault(name, []).append(df.loc[m & ~cut, 'c2o'].values)

    print('CLOSE-TO-OPEN (buy 16:00 close, sell 09:30 next open) — LONG ONLY, sub-$50')
    print(f'span {min(d.index[0] for d in data.values()).date()} .. '
          f'{max(d.index[-1] for d in data.values()).date()}   OOS from {a.oos_from}\n')
    for cost in COSTS_BP:
        print(f'--- cost {cost:.0f} bp round-trip ---')
        print(f'{"variant":9}{"n":>8}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"med_bp":>9}{"t":>7}   '
              f'{"OOS PF":>7}{"OOS avg":>9}{"OOS t":>7}')
        for name in ('ALL', 'DOWNDAY', 'NEARLOW', 'DOWN3', 'HIGHVOL', 'RSI2'):
            r = np.concatenate(pooled[name]) if pooled.get(name) else np.array([])
            ro = np.concatenate(pooled_oos[name]) if pooled_oos.get(name) else np.array([])
            s = stats(r, cost)
            so = stats(ro, cost)
            if not s:
                continue
            print(f'{name:9}{s["n"]:>8}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.2f}'
                  f'{s["med_bp"]:>9.2f}{s["t"]:>7.2f}   '
                  f'{(so["PF"] if so else float("nan")):>7.3f}'
                  f'{(so["avg_bp"] if so else float("nan")):>9.2f}'
                  f'{(so["t"] if so else float("nan")):>7.2f}')
        print()
    out = {c: {n: stats(np.concatenate(pooled[n]), c) for n in pooled} for c in COSTS_BP}
    json.dump({'costs': out, 'oos_from': a.oos_from, 'n_symbols': len(data)},
              open(os.path.join(_ROOT, 'research', 'close_to_open_results.json'), 'w'),
              indent=1, default=str)


if __name__ == '__main__':
    main()
