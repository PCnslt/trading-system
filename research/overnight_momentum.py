#!/usr/bin/env python3
"""Overnight momentum — buy at close, sell next open (shortest hold that survives costs).

Signal: rank names on trailing 20-day return; buy top-N at the close; sell next open.
Daily rebalance = many trades. Cost 4bp RT (close+open auctions are the two cheapest
venues). Honest stats: chronological OOS, date-clustered t-stat.
"""
import io, json
import boto3
import pandas as pd

S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'
COST = 4.0
TOP_N = 25
LOOKBACK = 20


def load_universe():
    with open('research/universe_1500.json') as f:
        raw = json.load(f)
    return (raw['symbols'] if isinstance(raw, dict) else raw)[:400]


def daily_bars(sym):
    try:
        df = pd.read_parquet(io.BytesIO(S3.get_object(
            Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')['Body'].read()))
    except Exception:
        return None
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    if len(df) < 260:
        return None
    df = df.copy()
    df['ret20'] = df['close'] / df['close'].shift(LOOKBACK) - 1.0
    df['next_open'] = df['open'].shift(-1)
    return df


def date_clustered_t(rets):
    if len(rets) < 30:
        return float('nan')
    se = rets.std(ddof=1) / (len(rets) ** 0.5)
    return rets.mean() / se if se > 0 else float('nan')


def run():
    univ = load_universe()
    bars = {s: d for s in univ if (d := daily_bars(s)) is not None}
    print(f'loaded {len(bars)} symbols')

    all_idx = sorted(set().union(*[set(d.index) for d in bars.values()]))
    dates = pd.DatetimeIndex(all_idx)

    rows = []
    for d in dates[LOOKBACK + 1:-1]:
        signal = {}
        for s, df in bars.items():
            v = df['ret20'].get(d)
            if pd.notna(v) and d in df.index and df['next_open'].get(d) == df['next_open'].get(d):
                signal[s] = v
        if len(signal) < TOP_N:
            continue
        winners = sorted(signal, key=signal.get, reverse=True)[:TOP_N]
        for s in winners:
            df = bars[s]
            entry = float(df.loc[d, 'close'])
            exit_ = float(df['next_open'].get(d))
            if pd.isna(exit_) or entry <= 0:
                continue
            r = (exit_ / entry - 1.0 - COST / 10000) * 10000
            rows.append({'date': d + pd.Timedelta(days=1), 'ret': r})

    tr = pd.DataFrame(rows).set_index('date')
    n = len(tr)
    split = tr.index[int(n * 0.8)]
    oos = tr[tr.index >= split]
    daily = oos.groupby(oos.index)['ret'].mean()
    pf = oos[oos.ret > 0].ret.sum() / -oos[oos.ret <= 0].ret.sum() if (oos.ret <= 0).any() else float('inf')
    print(f'overnight momentum top-{TOP_N}: {n} trades | OOS from {split.date()}')
    print(f'  OOS: n={len(oos)} avg={oos.ret.mean():+.1f}bp PF={pf:.2f} '
          f'win={100*(oos.ret>0).mean():.0f}% t={date_clustered_t(daily):+.2f}  '
          f'(trades/day={len(oos)/max(1,(oos.index[-1]-oos.index[0]).days/365*252):.0f})')


if __name__ == '__main__':
    run()
