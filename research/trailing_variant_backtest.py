#!/usr/bin/env python3
"""Backtest: fixed 2xATR stop vs naive trailing vs SMART armed-ratchet trailing.

The prior verdict ("trailing is WORSE than fixed 2xATR", PF 1.269 vs 1.319 @5bps)
killed bot/rh_trailing.py. Before enabling bot/rh_trailing_smart.py on live money
we re-run that comparison and add the armed-ratchet variant, on the SAME data the
live lane now uses (IBKR broker bars, s3 ibkr/equities/daily).

Strategy = the live RSI(2) lane:
  entry  : RSI(2) < 5 AND close > SMA200   -> fill at NEXT open
  exits  : stop (intraday low <= stop, gap-through at open) -> time stop 5 sessions
           -> revert (close > SMA5 OR RSI(2) > 70), priority in that order
Stop-management variants:
  FIXED  : stop = entry - 2*ATR, never moved                      (current live)
  NAIVE  : stop = max(prev, peak - 2*ATR) from day 1              (the disabled bot)
  SMART  : untouched until profit >= 1*ATR -> breakeven+5bp;
           profit >= 2*ATR -> peak - 2*ATR; ratchet-only-up       (the new bot)

Costs applied per side in bps (default 5). Honest metrics only.
"""
from __future__ import annotations
import io, os, sys, json, argparse
import datetime as dt
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
ARM_ATR, TRAIL_START_ATR, TRAIL_ATR, FEE_BP = 1.0, 2.0, 2.0, 5.0


def rsi(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def atr14(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


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
        df['sma200'] = df['close'].rolling(SMA_LONG).mean()
        df['sma5'] = df['close'].rolling(5).mean()
        df['atr'] = atr14(df['high'], df['low'], df['close'])
        return df.dropna()
    except Exception:
        return None


def run_variant(df, variant, price_max=50.0):
    """Yield closed trades for one symbol under one stop-management variant."""
    trades = []
    i, n = 1, len(df)
    idx = df.index
    o, h, l, c = (df[k].values for k in ('open', 'high', 'low', 'close'))
    r2, m200, m5, atr = (df[k].values for k in ('rsi2', 'sma200', 'sma5', 'atr'))
    while i < n - 1:
        if not (r2[i] < RSI2_THR and c[i] > m200[i] and 2.0 <= c[i] <= price_max
                and atr[i] > 0):
            i += 1
            continue
        e = i + 1                      # fill at next open
        entry, a = o[e], atr[i]
        if entry <= 0:
            i += 1
            continue
        stop = entry - STOP_ATR * a
        peak = entry
        exit_px = exit_reason = None
        j = e
        while j < n:
            peak = max(peak, h[j])
            # --- stop management (applies from the day AFTER entry) ---
            if j > e:
                if variant == 'NAIVE':
                    stop = max(stop, peak - TRAIL_ATR * a)
                elif variant == 'SMART':
                    prof = peak - entry
                    if prof >= TRAIL_START_ATR * a:
                        stop = max(stop, peak - TRAIL_ATR * a)
                    elif prof >= ARM_ATR * a:
                        stop = max(stop, entry * (1 + FEE_BP / 1e4))
            # --- exits, live priority: stop -> time -> revert ---
            if o[j] < stop:
                exit_px, exit_reason = o[j], 'gap_stop'
                break
            if l[j] <= stop:
                exit_px, exit_reason = stop, 'stop'
                break
            held = j - e
            if held >= MAX_HOLD:
                exit_px, exit_reason = c[j], 'time'
                break
            if c[j] > m5[j] or r2[j] > 70.0:
                exit_px, exit_reason = c[j], 'revert'
                break
            j += 1
        if exit_px is None:
            break
        gross = exit_px / entry - 1.0
        net = gross - 2 * FEE_BP / 1e4
        trades.append({'entry_date': idx[e], 'exit_date': idx[min(j, n - 1)],
                       'ret': net, 'reason': exit_reason, 'hold': j - e})
        i = j + 1
    return trades


def stats(trades):
    """Per-trade expectancy metrics ONLY.

    NOTE: an equity curve / maxDD from concatenating trades across symbols is
    meaningless here (trades overlap in time and there is no position sizing), so
    those numbers are deliberately NOT reported — comparing variants on PF,
    average net return per trade and its t-stat is the honest comparison.
    """
    if not trades:
        return {}
    r = np.array([t['ret'] for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    pf = (wins.sum() / -losses.sum()) if losses.sum() < 0 else float('inf')
    tstat = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else 0.0
    from collections import Counter
    return {'n': len(r), 'PF': round(pf, 3), 'win%': round(100 * len(wins) / len(r), 1),
            'avg_ret_bp': round(r.mean() * 1e4, 1),
            'med_ret_bp': round(float(np.median(r)) * 1e4, 1),
            't_stat': round(float(tstat), 2),
            'avg_hold': round(np.mean([t['hold'] for t in trades]), 2),
            'reasons': dict(Counter(t['reason'] for t in trades).most_common())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=250)
    a = ap.parse_args()
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))[:a.limit]
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols from the IBKR archive…', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable: {len(data)} symbols  '
          f'({min(d.index[0] for d in data.values()).date()} .. '
          f'{max(d.index[-1] for d in data.values()).date()})\n', flush=True)

    out = {}
    for v in ('FIXED', 'NAIVE', 'SMART'):
        allt = []
        for d in data.values():
            allt += run_variant(d, v)
        out[v] = stats(allt)
    keys = ['n', 'PF', 'win%', 'avg_ret_bp', 'med_ret_bp', 't_stat', 'avg_hold']
    print(f'{"variant":8}' + ''.join(f'{k:>12}' for k in keys))
    for v, s in out.items():
        print(f'{v:8}' + ''.join(f'{str(s.get(k, "-")):>12}' for k in keys))
    print()
    for v, s in out.items():
        print(f'{v:8} exits: {s.get("reasons")}')
    base = out['FIXED']['PF']
    print(f'\nvs FIXED baseline PF {base}:')
    for v in ('NAIVE', 'SMART'):
        d = out[v]['PF'] - base
        print(f'  {v:6} PF {out[v]["PF"]:.3f}  ({d:+.3f})  '
              f'avg_ret {out[v]["avg_ret_bp"]:+.1f}bp vs {base and out["FIXED"]["avg_ret_bp"]:+.1f}bp'
              f'  -> {"BETTER" if d > 0 else "WORSE/EQUAL"}')
    json.dump(out, open(os.path.join(_ROOT, 'research', 'trailing_variant_backtest.json'), 'w'),
              indent=1, default=str)


if __name__ == '__main__':
    main()
