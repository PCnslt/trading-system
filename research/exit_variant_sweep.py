#!/usr/bin/env python3
"""EXIT-RULE SWEEP for the RSI(2) lane — is the reversion exit actually optimal?

The live exit is: stop(2xATR) -> time(5) -> revert(close>SMA5 OR rsi2>70).
There is NO take-profit target. This sweeps exit variants to find out whether that
is right, or whether a fixed profit target / trailing / ATR-multiple exit does better.

Same entry for every variant: rsi2<5 AND close>SMA200, filled at next open, sub-$50.
Variants differ ONLY in the exit rule (stop is identical 2xATR across all):

  REVERT       close>SMA5 OR rsi2>70                                   (current live)
  TP_1ATR      take profit at +1.0*ATR  (else fall through to revert)
  TP_2ATR      take profit at +2.0*ATR
  TP_3ATR      take profit at +3.0*ATR
  TP_2PCT      take profit at +2.0%
  TP_3PCT      take profit at +3.0%
  TP_5PCT      take profit at +5.0%
  TRAIL_1ATR   chandelier trail peak-1.0*ATR (tighten-only) after entry
  TRAIL_2ATR   chandelier trail peak-2.0*ATR after entry

TP variants use INTRADAY high >= target to lock the exit (realistic for a resting
limit); TRAIL variants use the bar low <= trail. All TP/TRAIL exits still fire the
revert/time fallback if the target never hits. Honest per-trade stats + OOS split.
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
OOS_FROM = '2022-01-01'
COST = 5.0  # bp per side


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
        peak = entry
        trail = entry - 1e9
        exit_px = reason = None
        j = e
        while j < n:
            peak = max(peak, h[j])
            held = j - e
            # ---- exit checks in the strategy's priority: stop -> target -> time -> revert
            if o[j] < stop:
                exit_px, reason, jx = o[j], 'gap_stop', j
                break
            if l[j] <= stop:
                exit_px, reason, jx = stop, 'stop', j
                break
            # ---- variant-specific target / trail
            hit = False
            if variant.startswith('TP_1ATR'):
                hit = h[j] >= entry + 1.0 * a
                px = entry + 1.0 * a
            elif variant.startswith('TP_2ATR'):
                hit = h[j] >= entry + 2.0 * a
                px = entry + 2.0 * a
            elif variant.startswith('TP_3ATR'):
                hit = h[j] >= entry + 3.0 * a
                px = entry + 3.0 * a
            elif variant.startswith('TP_2PCT'):
                hit = h[j] >= entry * 1.02
                px = entry * 1.02
            elif variant.startswith('TP_3PCT'):
                hit = h[j] >= entry * 1.03
                px = entry * 1.03
            elif variant.startswith('TP_5PCT'):
                hit = h[j] >= entry * 1.05
                px = entry * 1.05
            elif variant.startswith('TRAIL_'):
                k = 1.0 if variant.endswith('1ATR') else 2.0
                trail = max(trail, peak - k * a)
                hit = l[j] <= trail and trail > entry
                px = trail
            if hit:
                exit_px, reason, jx = px, ('target' if 'TP_' in variant else 'trail'), j
                break
            if held >= MAX_HOLD:
                exit_px, reason, jx = c[j], 'time', j
                break
            if (c[j] > m5[j]) or (r2[j] > 70.0):
                exit_px, reason, jx = c[j], 'revert', j
                break
            j += 1
        if exit_px is None:
            break
        trades.append({'ret': exit_px / entry - 1.0, 'reason': reason,
                       'hold': jx - e, 'date': idx[e]})
        i = jx + 1
    return trades


def stats(tr, oos=False):
    if oos:
        tr = [t for t in tr if str(t['date'].date()) >= OOS_FROM]
    if len(tr) < 50:
        return None
    r = np.array([t['ret'] for t in tr]) - 2 * COST / 1e4
    w, lo = r[r > 0], r[r <= 0]
    pf = (w.sum() / -lo.sum()) if lo.sum() < 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 else 0.0
    return {'n': len(r), 'PF': round(pf, 3), 'win%': round(100 * len(w) / len(r), 1),
            'avg_bp': round(r.mean() * 1e4, 1), 't': round(float(t), 2),
            'hold': round(float(np.mean([x['hold'] for x in tr])), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=400)
    a = ap.parse_args()
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)}…', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}\n', flush=True)

    VAR = ['REVERT', 'TP_1ATR', 'TP_2ATR', 'TP_3ATR', 'TP_2PCT', 'TP_3PCT',
           'TP_5PCT', 'TRAIL_1ATR', 'TRAIL_2ATR']
    out = {}
    print(f'EXIT-VARIANT SWEEP @{COST:.0f}bp/side  (same entries, same 2xATR stop)\n')
    print(f'{"variant":12}{"n":>7}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}{"hold":>6}   '
          f'{"OOS PF":>7}{"OOS avg":>9}{"OOS t":>7}')
    for v in VAR:
        t = []
        for df in data.values():
            t += run(df, v)
        s, so = stats(t), stats(t, True)
        out[v] = {'full': s, 'oos': so}
        if s:
            print(f'{v:12}{s["n"]:>7}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.1f}'
                  f'{s["t"]:>7.2f}{s["hold"]:>6.2f}   '
                  f'{(so["PF"] if so else float("nan")):>7.3f}'
                  f'{(so["avg_bp"] if so else float("nan")):>9.1f}'
                  f'{(so["t"] if so else float("nan")):>7.2f}')
    json.dump(out, open(os.path.join(_ROOT, 'research', 'exit_variant_sweep.json'), 'w'),
              indent=1, default=str)


if __name__ == '__main__':
    main()
