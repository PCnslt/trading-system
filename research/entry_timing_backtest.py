#!/usr/bin/env python3
"""VALIDATE the RSI2 lane's ENTRY timing lag.

Live observation 2026-08-25: 9 entries filled at 10:21 ET (~51 min after the open)
because the 09:32 run takes ~6 min over 485 symbols and started late. The backtest
fills at the NEXT OPEN. This measures what a delayed entry actually costs.

Question: on an RSI2 entry day (rsi2<5 AND close>SMA200), does the price drift UP
after the open (oversold bounce -> a late entry buys higher = costs money) or DOWN
(continued selling -> a late entry buys lower = free money)?

Method (honest):
  * Entry signal + exit rules IDENTICAL to the live RSI2 lane (research/exit_timing_backtest.py):
    entry rsi2<5 AND close>SMA200, filled next session; exit priority stop(2xATR) ->
    time(5) -> revert(close>SMA5 OR rsi2>70), exit at the NEXT open (the B_OPEN_T1
    variant that is what live does).
  * For each entry, the price at open, open+5/+15/+30/+45/+60 min is read from real
    1-min bars. The stop is re-anchored to each entry price (as live would), so the
    full trade is re-simulated per timing variant.
  * Cost = 5 bp / 10 bp per side (round trip = 2x). Drift reported gross and net.

DATA CONSTRAINT (stated plainly, not hidden): the S3 1-min store
`ibkr/equities/1min/<TICKER>/` holds only 16 liquid MEGA-CAP names (2024-09..2026-08).
The live RSI2 sleeve trades sub-$50 small-caps, which have NO 1-min history here.
So the mechanism (first-hour drift of a just-crashed name) is measured on 16 mega-caps,
the only names with 1-min bars. A secondary check on the actual sub-$50 universe uses
Robinhood 5-min RTH bars (36 names, ~11 sessions Aug 2026) — tiny n, reported as a
directional sanity check only, NOT a headline number.
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
load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
MEGA = ["AAPL", "AMD", "AMZN", "AVGO", "GOOG", "GOOGL", "INTC",
        "META", "MSFT", "MU", "NBIS", "NVDA", "PLTR", "SNDK", "SPCX", "TSLA"]
RSI2_THR, SMA_LONG, MAX_HOLD, STOP_ATR = 5.0, 200, 5, 2.0
COSTS = [5.0, 10.0]
DELAYS = [0, 5, 15, 30, 45, 60]   # minutes after the open
CACHE = "/tmp/entry_timing_1min"


def rsi(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50.0)


def atr14(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def load_daily(sym, s3):
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


def signal_days(df):
    """Return list of (signal_day_idx, entry_day_idx) for the RSI2 lane."""
    r2 = df['rsi2'].values
    c = df['close'].values
    m200 = df['sma200'].values
    out = []
    n = len(df)
    for i in range(1, n - 2):
        if r2[i] < RSI2_THR and c[i] > m200[i]:
            out.append((i, i + 1))
    return out


def needed_months(days):
    ms = set()
    for d in days:
        ms.add(f"{d.year:04d}-{d.month:02d}")
    return sorted(ms)


def load_1min(sym, days, s3):
    """Fetch only the month partitions containing entry days."""
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, f"{sym}.pkl")
    frames = []
    for ym in needed_months(days):
        key = f"ibkr/equities/1min/{sym}/{ym}.parquet"
        try:
            o = s3.get_object(Bucket=BUCKET, Key=key)
            frames.append(pd.read_parquet(io.BytesIO(o['Body'].read())))
        except Exception:
            continue
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df['ts'] = pd.to_datetime(df['ts'], unit='s', utc=True).dt.tz_convert('America/New_York')
    df = df.sort_values('ts').drop_duplicates('ts').reset_index(drop=True)
    df['day'] = df['ts'].dt.date
    df = df[df['open'] > 0]
    return df


def intraday_prices(df1m, day, delays):
    """Return {delay_min: price} for the RTH session of `day`."""
    d = df1m[df1m['day'] == day].sort_values('ts')
    if len(d) < 60:          # truncated / holiday session
        return None
    ts = d['ts'].values
    open_px = float(d['open'].iloc[0])
    open_ts = pd.Timestamp(ts[0])
    out = {0: open_px}
    for T in delays[1:]:
        target = open_ts + pd.Timedelta(minutes=T)
        idx = np.searchsorted(ts, target)
        if idx >= len(ts):
            idx = len(ts) - 1
        out[T] = float(d['close'].iloc[idx])
    return out


def simulate_exit(df, e, entry_price, atr_ref):
    """Re-simulate the RSI2 lane trade from entry day e, stop anchored to entry_price.
    Exit variant = B_OPEN_T1 (next open after trigger), matching live. Returns
    (exit_price, exit_day_idx, reason) or None."""
    o = df['open'].values
    l = df['low'].values
    c = df['close'].values
    m5 = df['sma5'].values
    r2 = df['rsi2'].values
    n = len(df)
    stop = entry_price - STOP_ATR * atr_ref
    j = e
    while j < n:
        if o[j] < stop:
            return o[j], j, 'gap_stop'
        if l[j] <= stop:
            return stop, j, 'stop'
        held = j - e
        if held >= MAX_HOLD or c[j] > m5[j] or r2[j] > 70.0:
            if j + 1 >= n:
                return None
            return o[j + 1], j + 1, ('time' if held >= MAX_HOLD else 'revert')
        j += 1
    return None


def stats(trades, cost):
    if len(trades) < 30:
        return None
    r = np.array([t['ret'] for t in trades]) - 2 * cost / 1e4
    w = r[r > 0]
    lo = r[r <= 0]
    pf = (w.sum() / -lo.sum()) if lo.sum() < 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 else 0.0
    return {'n': len(r), 'PF': round(pf, 3), 'win%': round(100 * len(w) / len(r), 1),
            'avg_bp': round(r.mean() * 1e4, 1), 't': round(float(t), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='2025-09-01', help='time split for stability check')
    a = ap.parse_args()
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))

    # ---- per symbol: signals, then 1-min prices on entry days ----
    all_drift = []          # dict per entry: delay -> drift bp vs open
    all_trades = {d: [] for d in DELAYS}   # dict delay -> list of {date, ret, reason}

    for sym in MEGA:
        df = load_daily(sym, s3)
        if df is None:
            print(f'{sym}: no daily data', flush=True)
            continue
        sigs = signal_days(df)
        entry_days = [df.index[e].date() for (_, e) in sigs]
        df1m = load_1min(sym, [pd.Timestamp(d) for d in entry_days], s3)
        if df1m is None:
            print(f'{sym}: no 1-min data', flush=True)
            continue
        got = 0
        for (i, e) in sigs:
            day = df.index[e].date()
            px = intraday_prices(df1m, day, DELAYS)
            if px is None:
                continue
            atr_ref = float(df['atr'].values[i])
            entry_0 = px[0]
            row = {'sym': sym, 'date': str(day), 'open': entry_0}
            for T in DELAYS:
                row[f'px{T}'] = px[T]
            for T in DELAYS:
                ex = simulate_exit(df, e, px[T], atr_ref)
                if ex is None:
                    continue
                exit_px, jx, reason = ex
                ret = exit_px / px[T] - 1.0
                all_trades[T].append({'date': str(day), 'ret': ret, 'reason': reason})
            # drift of entry price vs the open (the pure "cost of a late entry")
            dr = {'sym': sym, 'date': str(day)}
            for T in DELAYS[1:]:
                dr[f'd{T}'] = (px[T] / entry_0 - 1.0) * 1e4
            all_drift.append(dr)
            got += 1
        print(f'{sym}: {len(sigs)} signals, {got} with 1-min entry-day bars', flush=True)

    print(f'\ntotal entries measured: {len(all_drift)}\n', flush=True)

    # ---- drift summary (the headline metric) ----
    print('=' * 78)
    print('ENTRY-PRICE DRIFT vs the OPEN  (bp; >0 means a late entry buys HIGHER = costs)')
    print('=' * 78)
    print(f'{"delay":>7}{"n":>6}{"mean_bp":>10}{"median_bp":>10}{">0 %":>7}')
    for T in DELAYS[1:]:
        v = np.array([x[f'd{T}'] for x in all_drift])
        print(f'{T:>6}m{len(v):>6}{v.mean():>10.2f}{np.median(v):>10.2f}'
              f'{(v > 0).mean() * 100:>7.1f}')
    # per-minute cost (linear fit on means)
    print()
    print('per-minute cost (mean drift at 60m / 60):', end=' ')
    v60 = np.array([x['d60'] for x in all_drift])
    print(f'{v60.mean() / 60:.3f} bp/min')

    # ---- full-trade PF at each entry timing (stop re-anchored) ----
    print()
    for cost in COSTS:
        print(f'--- full trade @ {cost:.0f} bp/side ---')
        print(f'{"delay":>7}{"n":>6}{"PF":>7}{"win%":>7}{"avg_bp":>9}{"t":>7}   '
              f'{"2nd-half PF":>10}{"2nd-half avg":>13}')
        for T in DELAYS:
            tr = all_trades[T]
            s = stats(tr, cost)
            # stability: second half of the window by entry date
            tr2 = [t for t in tr if t['date'] >= a.split]
            s2 = stats(tr2, cost)
            if not s:
                continue
            print(f'{T:>6}m{s["n"]:>6}{s["PF"]:>7.3f}{s["win%"]:>7.1f}{s["avg_bp"]:>9.1f}'
                  f'{s["t"]:>7.2f}   '
                  f'{(s2["PF"] if s2 else float("nan")):>10.3f}'
                  f'{(s2["avg_bp"] if s2 else float("nan")):>13.1f}')
        print()

    # ---- verdict vs the live 51-min delay ----
    d51 = 0.0
    if all_drift:
        # interpolate drift at 51 min between 45 and 60
        d45 = np.mean([x['d45'] for x in all_drift])
        d60 = np.mean([x['d60'] for x in all_drift])
        d51 = d45 + (d60 - d45) * (51 - 45) / (60 - 45)
    print(f'IMPLIED live entry-lag cost @ ~51 min: ~{d51:+.1f} bp/trade (vs open fill)')
    print(f'  n={len(all_drift)} entries, 16 liquid mega-caps, 2024-09..2026-08 '
          f'(proxy for the sub-$50 sleeve — see DATA CONSTRAINT)')

    # persist
    out = {'config': {'universe': '16 mega-caps (1-min)', 'delays_min': DELAYS,
                      'costs_per_side': COSTS, 'split': a.split},
           'n_entries': len(all_drift),
           'drift_bp': {str(T): {
               'mean': round(float(np.mean([x[f'd{T}'] for x in all_drift])), 2),
               'median': round(float(np.median([x[f'd{T}'] for x in all_drift])), 2),
               'pct_positive': round(float((np.array([x[f'd{T}'] for x in all_drift]) > 0).mean() * 100), 1)
           } for T in DELAYS[1:]},
           'trades': {str(cost): {str(T): stats(all_trades[T], cost) for T in DELAYS}
                      for cost in COSTS},
           'implied_51min_cost_bp': round(d51, 2)}
    json.dump(out, open(os.path.join(_ROOT, 'research', 'entry_timing_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/entry_timing_results.json')


if __name__ == '__main__':
    main()
