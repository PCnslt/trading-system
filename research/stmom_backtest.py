#!/usr/bin/env python3
"""Short-Term Momentum (Medhat-Schmeling 2022 RFS) — the flagship cost-survivable
multi-week edge. Backtest on the liquid universe with honest stats.

Rule (long-only): monthly, rank names on prior-month return (skip the most recent 5
days to avoid the 1-week reversal), buy the top quintile, hold ~20 trading days.
Cost 6bp round-trip. Chronological OOS. Date-clustered t-stat.
"""
import io, json, math, os
import boto3
import numpy as np
import pandas as pd

S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'
COST = 6.0  # bp round-trip (buy+sell)
TOP_N = 25  # buy top-25 winners each month


def load_universe():
    with open('research/universe_1500.json') as f:
        raw = json.load(f)
    syms = raw['symbols'] if isinstance(raw, dict) and 'symbols' in raw else raw
    return syms[:400]  # liquid-first; large caps minimize survivorship bias


def daily_bars(sym):
    key = f'ibkr/equities/daily/{sym}.parquet'
    try:
        df = pd.read_parquet(io.BytesIO(S3.get_object(Bucket=BUCKET, Key=key)['Body'].read()))
    except Exception:
        return None
    df = df.sort_values('date').reset_index(drop=True)
    df['date'] = pd.to_datetime(df['date'])
    return df[['date', 'close']].set_index('date')


def date_clustered_t(rets: pd.Series) -> float:
    """t-stat with daily-bar clustering (each DAY is one independent obs)."""
    if len(rets) < 30:
        return float('nan')
    mean = rets.mean()
    se = rets.std(ddof=1) / math.sqrt(len(rets))
    return mean / se if se > 0 else float('nan')


def run():
    univ = load_universe()
    closes = {}
    for s in univ:
        df = daily_bars(s)
        if df is not None and len(df) > 260:
            closes[s] = df['close']
    print(f'loaded {len(closes)} symbols with >=260 bars')

    # build monthly rebalance dates from the union of all dates
    all_idx = sorted(set().union(*[set(c.index) for c in closes.values()]))
    dates = pd.DatetimeIndex(all_idx)
    rebal = dates.to_period('M').drop_duplicates().to_timestamp('M')  # month-ends

    trades = []
    for m in rebal:
        # prior-month return, skipping last 5 days
        signal = {}
        for s, c in closes.items():
            hist = c[c.index < m]
            if len(hist) < 25:
                continue
            # return from m-1 month-start to 5 days before m
            start = hist.index[-25]
            end = hist.index[-6]
            if end <= start:
                continue
            ret = float(hist.loc[end]) / float(hist.loc[start]) - 1.0
            signal[s] = ret
        if not signal:
            continue
        winners = sorted(signal, key=signal.get, reverse=True)[:TOP_N]
        # hold for ~20 trading days from m
        m_pos = dates.get_indexer([m], method='ffill')[0]
        entry_i = m_pos + 1
        exit_i = min(entry_i + 20, len(dates) - 1)
        if exit_i <= entry_i:
            continue
        entry_d = dates[entry_i]
        exit_d = dates[exit_i]
        for s in winners:
            c = closes[s]
            if entry_d in c.index and exit_d in c.index:
                r = float(c.loc[exit_d]) / float(c.loc[entry_d]) - 1.0 - COST / 10000
                trades.append({'date': exit_d, 'sym': s, 'ret': r * 10000})  # bp

    tr = pd.DataFrame(trades)
    if tr.empty:
        print('no trades')
        return
    tr = tr.set_index('date')
    n = len(tr)
    split = tr.index[int(n * 0.8)]
    is_, oos = tr[tr.index < split], tr[tr.index >= split]
    print(f'STMOM long-only top-{TOP_N}: {n} trades | COST {COST}bp RT | OOS from {split.date()}')
    for name, d in [('IS ', is_), ('OOS', oos)]:
        if d.empty:
            continue
        pf = d[d.ret > 0].ret.sum() / -d[d.ret <= 0].ret.sum() if (d.ret <= 0).any() else float('inf')
        # date-cluster: mean daily return
        daily = d.groupby(d.index)['ret'].mean()
        print(f'  {name}: n={len(d)}  avg={d.ret.mean():+.1f}bp  PF={pf:.2f}  '
              f'win={100*(d.ret>0).mean():.0f}%  t_daily={date_clustered_t(daily):+.2f}')


if __name__ == '__main__':
    run()
