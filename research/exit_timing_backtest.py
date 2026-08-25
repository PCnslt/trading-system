#!/usr/bin/env python3
"""VALIDATE bot/rh_preclose_exit.py — the change shipped to LIVE money on 2026-08-25.

I deployed a 15:50 ET pre-close exit run on reasoning alone ("the backtest exits on the
close of the trigger day, so evaluating at 09:32 next morning sells ~1 session late")
and never tested it. This tests it. If A does not beat B, the cron gets REVERTED.

Same RSI(2) lane as live: entry rsi2<5 AND close>SMA200, filled at the NEXT OPEN.
Exit priority identical to the bot: stop -> time(5) -> revert(close>SMA5 OR rsi2>70).

The variants differ ONLY in WHEN the revert/time exit is executed once it triggers on
the close of day T:
  A_CLOSE_T    exit at day T's CLOSE          <- what the new 15:50 pre-close run does
  B_OPEN_T1    exit at day T+1's OPEN         <- what live did before today (09:32 run)
  C_CLOSE_T1   exit at day T+1's CLOSE        <- a full day later (worst case / control)
A stop exit is unchanged across variants (it fires intraday at the stop price, or at the
open on a gap-through), so any difference is attributable purely to exit TIMING.

Honest metrics only: per-trade expectancy + t-stat. No concatenated equity curve.
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
RSI2_THR, SMA_LONG, MAX_HOLD, STOP_ATR = 5.0, 200, 5, 2.0
PRICE_LO, PRICE_HI = 2.0, 50.0
COSTS = [5.0, 10.0]


def rsi(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50.0)


def atr14(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        df['rsi2'] = rsi(df['close'], 2)
        df['sma200'] = df['close'].rolling(SMA_LONG).mean()
        df['sma5'] = df['close'].rolling(5).mean()
        df['atr'] = atr14(df['high'], df['low'], df['close'])
        return df.dropna()
    except Exception:
        return None


def run(df, variant):
    trades = []
    idx = df.index
    o, h, l, c = (df[k].values for k in ('open', 'high', 'low', 'close'))
    r2, m200, m5, atr = (df[k].values for k in ('rsi2', 'sma200', 'sma5', 'atr'))
    n = len(df)
    i = 1
    while i < n - 2:
        if not (r2[i] < RSI2_THR and c[i] > m200[i]
                and PRICE_LO <= c[i] <= PRICE_HI and atr[i] > 0):
            i += 1
            continue
        e = i + 1
        entry, a = o[e], atr[i]
        if entry <= 0:
            i += 1
            continue
        stop = entry - STOP_ATR * a
        exit_px = reason = None
        j = e
        while j < n:
            # stop is timing-invariant: intraday touch or gap-through at the open
            if o[j] < stop:
                exit_px, reason, jx = o[j], 'gap_stop', j
                break
            if l[j] <= stop:
                exit_px, reason, jx = stop, 'stop', j
                break
            held = j - e
            trig = (held >= MAX_HOLD) or (c[j] > m5[j]) or (r2[j] > 70.0)
            if trig:
                reason = 'time' if held >= MAX_HOLD else 'revert'
                if variant == 'A_CLOSE_T':
                    exit_px, jx = c[j], j
                elif variant == 'B_OPEN_T1':
                    if j + 1 >= n:
                        break
                    exit_px, jx = o[j + 1], j + 1
                else:  # C_CLOSE_T1
                    if j + 1 >= n:
                        break
                    exit_px, jx = c[j + 1], j + 1
                break
            j += 1
        if exit_px is None:
            break
        trades.append({'ret': exit_px / entry - 1.0, 'reason': reason,
                       'hold': jx - e, 'date': idx[e]})
        i = jx + 1
    return trades


def stats(tr, cost, oos_from=None):
    if oos_from:
        tr = [t for t in tr if str(t['date'].date()) >= oos_from]
    if len(tr) < 50:
        return None
    r = np.array([t['ret'] for t in tr]) - 2 * cost / 1e4
    w, lo = r[r > 0], r[r <= 0]
    pf = (w.sum() / -lo.sum()) if lo.sum() < 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 else 0.0
    return {'n': len(r), 'PF': round(pf, 3), 'win%': round(100 * len(w) / len(r), 1),
            'avg_bp': round(r.mean() * 1e4, 1), 't': round(float(t), 2),
            'hold': round(float(np.mean([x['hold'] for x in tr])), 2)}


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
    print(f'  usable {len(data)}\n', flush=True)

    allt = {}
    for v in ('A_CLOSE_T', 'B_OPEN_T1', 'C_CLOSE_T1'):
        t = []
        for df in data.values():
            t += run(df, v)
        allt[v] = t

    out = {}
    for cost in COSTS:
        print(f'--- {cost:.0f} bp per side ---')
        print(f'{"variant":12}{"n":>7}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}{"hold":>6}   '
              f'{"OOS PF":>7}{"OOS avg":>9}{"OOS t":>7}')
        for v in ('A_CLOSE_T', 'B_OPEN_T1', 'C_CLOSE_T1'):
            s = stats(allt[v], cost)
            so = stats(allt[v], cost, a.oos_from)
            out.setdefault(str(cost), {})[v] = {'full': s, 'oos': so}
            if not s:
                continue
            print(f'{v:12}{s["n"]:>7}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.1f}'
                  f'{s["t"]:>7.2f}{s["hold"]:>6.2f}   '
                  f'{(so["PF"] if so else float("nan")):>7.3f}'
                  f'{(so["avg_bp"] if so else float("nan")):>9.1f}'
                  f'{(so["t"] if so else float("nan")):>7.2f}')
        print()
    a_ = out[str(COSTS[0])]['A_CLOSE_T']
    b_ = out[str(COSTS[0])]['B_OPEN_T1']
    d_full = a_['full']['avg_bp'] - b_['full']['avg_bp']
    d_oos = a_['oos']['avg_bp'] - b_['oos']['avg_bp']
    print(f'VERDICT @{COSTS[0]:.0f}bp  A(pre-close) - B(next-open) = '
          f'{d_full:+.1f}bp full / {d_oos:+.1f}bp OOS per trade')
    print('  -> ' + ('KEEP the 15:50 pre-close cron' if d_full > 0 and d_oos > 0
                     else 'REVERT the 15:50 pre-close cron'))
    json.dump(out, open(os.path.join(_ROOT, 'research', 'exit_timing_results.json'), 'w'),
              indent=1, default=str)


if __name__ == '__main__':
    main()
