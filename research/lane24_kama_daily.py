#!/usr/bin/env python3
"""LANE 24 — KAMA crossover, RE-TESTED on DAILY bars (2-3 day swing horizon).

Registry verdict was NO-GO "wrong horizon" (whipsaws at 5-min: pooled PF 0.82 @0t
/ 0.70 @3t, OOS 0.68, 7,697 trades of churn). Kaufman's adaptive MA is a DAILY
trend instrument, so this re-runs it on daily bars with a 2-3 day hold — matching
the owner's 1/2/3-day swing directive.

KAMA is IDENTICAL to the intraday test (imported from intraday_validate.kama:
ER n=10, fast=2, slow=30) — only the bar timeframe changes.

Strategy:
  - Entry (long): close crosses ABOVE KAMA (prev close <= prev KAMA).
  - Entry (short): close crosses BELOW KAMA (both-dir instruments only).
  - Exit: opposite crossover, OR time stop (hold 2 / 3 trading days), whichever
    first. A pure-crossover variant (hold=inf) is reported for reference.
  - One position at a time; entry at signal-bar close; force-close at end of data.

Cost model (per directive "equities cost model @5-10bps"): slippage+cost in basis
points per round-trip. bps in {0, 5, 10} applied as a fractional return haircut per
trade (5bps = 0.0005, 10bps = 0.0010). P&L is FRACTIONAL return (exit/entry-1)*side,
so pooling across price scales is meaningful.

Walk-forward 60/40 by entry date (assign trades to folds, do NOT re-run on sliced
data). OOS = last 40% of entry dates.

Instruments:
  - Index futures continuous (S3 yf/futures): ES=F, NQ=F, YM=F, RTY=F  (both-dir).
  - Index ETFs (yfinance, split+div adjusted): SPY, QQQ, DIA, IWM  (long-only primary
    + both-dir reference).

Metrics: n, win%, PF, net (sum of fractional returns, %), maxDD (% of equity curve),
Sharpe (daily). Drawdown-first read per owner objective.

READ-ONLY: S3 get_object + yfinance. No IBKR, no DynamoDB, no orders.
"""
import argparse
import json
import os
import sys
import numpy as np
import pandas as pd
import boto3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intraday_validate import kama as _kama  # identical KAMA to intraday test

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

FUTURES = ['ES=F', 'NQ=F', 'YM=F', 'RTY=F']
ETFS = ['SPY', 'QQQ', 'DIA', 'IWM']
BPS_LEVELS = [0, 5, 10]
HOLDS = [('cross', None), ('2d', 2), ('3d', 3)]


# ---------------- data loaders ----------------
def load_futures(sym):
    """Load continuous futures daily from S3 yf/futures -> DataFrame."""
    s3 = boto3.client('s3', region_name=AWS_REGION)
    key = f'yf/futures/{sym}.json'
    o = s3.get_object(Bucket=S3_BUCKET, Key=key)
    d = json.loads(o['Body'].read())
    rows = []
    for b in d['daily']:
        rows.append((b['ts'], b['open'], b['high'], b['low'], b['close']))
    df = pd.DataFrame(rows, columns=['ts', 'open', 'high', 'low', 'close'])
    df['ts'] = pd.to_datetime(df['ts'], utc=True)
    df = df.dropna(subset=['close']).sort_values('ts')
    df = df[df['close'] > 0].reset_index(drop=True)
    df['day'] = df['ts'].dt.date
    return df


def load_etf(sym):
    """Load index ETF daily (split+div adjusted) via yfinance."""
    import yfinance as yf
    df = yf.Ticker(sym).history(period='max', auto_adjust=True, actions=False)
    df = df[['Open', 'High', 'Low', 'Close']].dropna().reset_index()
    df.columns = ['ts', 'open', 'high', 'low', 'close']
    df['ts'] = pd.to_datetime(df['ts'], utc=True)
    df = df[df['close'] > 0].reset_index(drop=True)
    df['day'] = df['ts'].dt.date
    return df


# ---------------- daily engine (no EOD flatten) ----------------
def run_daily(c, k, direction, hold_days):
    """Bar-by-bar KAMA crossover on daily bars.

    direction: 'both' (long+short) or 'long' (long-only).
    hold_days: None -> pure crossover; int -> time stop after N bars.
    Returns list of trades {side, entry_i, exit_i, entry_px, exit_px, entry_day, reason}.
    """
    n = len(c)
    trades = []
    pos = 0
    entry_i = entry_px = None
    for i in range(n):
        if pos == 0:
            if i < 1 or np.isnan(k[i]) or np.isnan(k[i - 1]):
                continue
            long_x = c[i] > k[i] and c[i - 1] <= k[i - 1]
            short_x = c[i] < k[i] and c[i - 1] >= k[i - 1]
            if long_x:
                pos, entry_i, entry_px = 1, i, c[i]
            elif short_x and direction == 'both':
                pos, entry_i, entry_px = -1, i, c[i]
        else:
            exit_px = reason = None
            if hold_days is not None and (i - entry_i) >= hold_days:
                exit_px, reason = c[i], 'time'
            else:
                if pos == 1 and c[i] < k[i] and not np.isnan(k[i]):
                    exit_px, reason = c[i], 'cross'
                elif pos == -1 and c[i] > k[i] and not np.isnan(k[i]):
                    exit_px, reason = c[i], 'cross'
            if exit_px is not None:
                trades.append(dict(side=pos, entry_i=entry_i, exit_i=i,
                                   entry_px=float(entry_px), exit_px=float(exit_px),
                                   entry_day=None, reason=reason))
                pos, entry_i, entry_px = 0, None, None
    if pos != 0:  # force-close open position at end of data
        trades.append(dict(side=pos, entry_i=entry_i, exit_i=n - 1,
                           entry_px=float(entry_px), exit_px=float(c[n - 1]),
                           entry_day=None, reason='end'))
    return trades


# ---------------- metrics ----------------
def frac_return(t, bps_rt):
    """Fractional return per trade, net of round-trip bps."""
    if t['entry_px'] == 0:
        return 0.0
    gross = (t['exit_px'] / t['entry_px'] - 1.0) * t['side']
    return gross - bps_rt / 10000.0


def summarize(fracs, days=None):
    """Metrics from per-trade fractional returns + the EXIT-day of each trade.

    `days` must be the exit date of each trade (list aligned to fracs).
    Builds a CHRONOLOGICAL daily equity curve over the full day range (zero-fill
    no-trade days), then maxDD + Sharpe from that curve. (Previous version
    sorted daily returns BY VALUE -> corrupt maxDD; fixed 2026-08-18.)
    """
    if len(fracs) == 0:
        return dict(n=0, win=0.0, pf=0.0, net=0.0, maxdd=0.0, sharpe=0.0)
    a = np.asarray(fracs, dtype=float)
    wins = a[a > 0].sum()
    losses = abs(a[a <= 0].sum())
    pf = float(wins / losses) if losses > 0 else float('inf')
    if days is None:
        return dict(n=len(a), win=100.0 * (a > 0).mean(), pf=pf,
                    net=float(a.sum()) * 100.0, maxdd=0.0, sharpe=0.0)
    # chronological daily curve over full range (zero-fill)
    all_days = sorted(set(days))
    daily = {d: 0.0 for d in all_days}
    for d, f in zip(days, a):
        daily[d] = daily.get(d, 0.0) + f
    eq = np.cumsum([daily[d] for d in all_days])
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    maxdd = float(dd.min()) * 100.0          # absolute, % of notional (sum-of-returns conv.)
    # relative maxDD (drawdown / prior peak) — the meaningful drawdown for a
    # sum-of-returns curve that can go below -100%
    rel = np.where(peak > 0, dd / peak, 0.0)
    rel_maxdd = float(rel.min()) * 100.0
    dv = np.array([daily[d] for d in all_days])
    mu, sd = dv.mean(), dv.std(ddof=1)
    sharpe = float(mu / sd * np.sqrt(252)) if sd > 0 else 0.0
    return dict(n=len(a), win=100.0 * (a > 0).mean(), pf=pf,
                net=float(a.sum()) * 100.0, maxdd=maxdd,
                rel_maxdd=rel_maxdd, sharpe=sharpe)


def walk_forward(trades):
    """Split by entry date (60/40). trades must carry entry_day already."""
    if not trades:
        return [], []
    days = sorted({t['entry_day'] for t in trades})
    cut = days[int(len(days) * 0.6)]
    train = [t for t in trades if t['entry_day'] < cut]
    oos = [t for t in trades if t['entry_day'] >= cut]
    return train, oos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'lane24_kama_daily_results.json')

    results = {'lane': 24, 'strategy': 'KAMA crossover (daily, 2-3 day hold)',
               'kama': dict(er_n=10, fast=2, slow=30),
               'cost_model': 'bps round-trip (equities model)',
               'bps_levels': BPS_LEVELS, 'holds': [h[0] for h in HOLDS],
               'walk_forward': '60/40 by entry date', 'instruments': {}}

    instruments = []
    for sym in FUTURES:
        instruments.append((sym, 'futures', 'both'))
    for sym in ETFS:
        instruments.append((sym, 'etf', 'long'))
        instruments.append((sym, 'etf', 'both'))

    for sym, kind, direction in instruments:
        print(f'\n=== {sym} ({kind}, {direction}) ===', flush=True)
        try:
            df = load_futures(sym) if kind == 'futures' else load_etf(sym)
        except Exception as e:
            print(f'  LOAD ERROR {sym}: {e}', flush=True)
            results['instruments'][f'{sym}:{direction}'] = dict(error=str(e))
            continue
        if len(df) < 60:
            print(f'  too few bars ({len(df)})', flush=True)
            results['instruments'][f'{sym}:{direction}'] = dict(n_bars=len(df), error='thin')
            continue
        c = df['close'].to_numpy(dtype=float)
        k = _kama(c)
        entry_days = list(df['day'])
        print(f'  {len(df)} daily bars {df["day"].iloc[0]} -> {df["day"].iloc[-1]}', flush=True)

        inst = {'kind': kind, 'direction': direction, 'n_bars': len(df),
                'start': str(df['day'].iloc[0]), 'end': str(df['day'].iloc[-1]),
                'holds': {}}
        for hname, hold in HOLDS:
            trades = run_daily(c, k, direction, hold)
            for t in trades:
                t['entry_day'] = entry_days[t['entry_i']]
                t['exit_day'] = entry_days[t['exit_i']]
            train, oos = walk_forward(trades)
            hrow = {}
            for bps in BPS_LEVELS:
                f_all = [frac_return(t, bps) for t in trades]
                f_tr = [frac_return(t, bps) for t in train]
                f_oo = [frac_return(t, bps) for t in oos]
                hrow[f'bps{bps}'] = dict(
                    full=summarize(f_all, [t['exit_day'] for t in trades]),
                    train=summarize(f_tr, [t['exit_day'] for t in train]),
                    oos=summarize(f_oo, [t['exit_day'] for t in oos]))
            inst['holds'][hname] = hrow
            # headline print @5bps (realistic) and @10bps
            for bps in (5, 10):
                r = hrow[f'bps{bps}']
                o = r['oos']; tr = r['train']
                print(f'  [{hname:5s}] bps{bps}: n={o["n"]:4d}  IS PF={tr["pf"]:5.2f}  '
                      f'OOS PF={o["pf"]:5.2f}  net={o["net"]:8.2f}%  maxDD={o["maxdd"]:7.2f}%  '
                      f'relDD={o.get("rel_maxdd",0):7.2f}%  win={o["win"]:5.1f}%', flush=True)
        results['instruments'][f'{sym}:{direction}'] = inst

    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
