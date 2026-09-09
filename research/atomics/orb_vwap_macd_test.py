#!/usr/bin/env python3
"""ORB + VWAP + MACD intraday momentum — honest backtest.

The prompt's exact rules on the 40-name 5-min lake (S3 ibkr/equities/5min/):
  LONG:  close > OR_High (first 5m candle high)  AND close > session VWAP
         AND MACD(12,26,9) line > signal AND hist > 0 AND hist expanding.
  SHORT: close < OR_Low AND close < VWAP AND MACD line < signal
         AND hist < 0 AND hist falling.
Entry at the breakout-bar close; measure forward return to the END OF DAY
(15:45 ET) net of 6bp round-trip (our measured cost). Reports long-only,
short-only, long-short, and a same-day random-entry baseline.
"""
import io
import numpy as np
import pandas as pd
import boto3

s3 = boto3.client('s3', region_name='us-east-1')
B = 'trading-datalake-920641308584'
P5 = 'ibkr/equities/5min/'

keys = [o['Key'] for o in s3.list_objects_v2(Bucket=B, Prefix=P5).get('Contents', [])
        if o['Key'].endswith('.parquet')]
frames = []
for k in keys:
    sym = k.split('/')[-1][:-8]
    d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=k)['Body'].read()))
    d['symbol'] = sym
    frames.append(d)
df = pd.concat(frames, ignore_index=True)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
df['day'] = df['date'].dt.date
print(f'loaded {len(df)} bars, {df["symbol"].nunique()} symbols, {df["day"].nunique()} days')

COST = 0.0006  # 6bp round-trip
longs, shorts = [], []

for sym, g in df.groupby('symbol'):
    g = g.sort_values('date')
    close = g['close'].astype(float)
    high = g['high'].astype(float)
    low = g['low'].astype(float)
    vol = g['volume'].astype(float)
    avg = g['average'].astype(float)  # bar VWAP (used for session VWAP)
    # MACD 12/26/9
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    hist_rising = hist > hist.shift(1)
    hist_falling = hist < hist.shift(1)

    for day, idx in g.groupby('day').groups.items():
        if len(idx) < 3:
            continue
        i0 = idx[0]
        or_high = high.loc[i0]
        or_low = low.loc[i0]
        # session cumulative VWAP
        pv = (avg * vol).loc[idx].cumsum()
        cv = vol.loc[idx].cumsum()
        vwap = (pv / cv.replace(0, np.nan)).ffill()

        for i in idx[1:]:
            c = close.loc[i]
            # last bar of the session -> no forward
            if i == idx[-1]:
                continue
            eod = close.loc[idx[-1]]
            if eod <= 0:
                continue
            fwd = eod / c - 1.0
            # LONG (all 4)
            if (c > or_high and c > vwap.loc[i]
                    and macd.loc[i] > signal.loc[i]
                    and hist.loc[i] > 0 and hist_rising.loc[i]):
                longs.append(fwd)
            # SHORT (all 4)
            if (c < or_low and c < vwap.loc[i]
                    and macd.loc[i] < signal.loc[i]
                    and hist.loc[i] < 0 and hist_falling.loc[i]):
                shorts.append(fwd)

# random same-day baseline: average forward-to-EOD across ALL bars (drift)
all_fwd = []
for sym, g in df.groupby('symbol'):
    g = g.sort_values('date')
    close = g['close'].astype(float)
    for day, idx in g.groupby('day').groups.items():
        if len(idx) < 3:
            continue
        eod = close.loc[idx[-1]]
        for i in idx[1:-1]:
            if close.loc[i] > 0 and eod > 0:
                all_fwd.append(eod / close.loc[i] - 1.0)


def stat(name, v):
    v = np.array(v)
    if len(v) == 0:
        print(f'{name:<22} n=0')
        return
    net = v - COST
    wins = net[net > 0].sum()
    losses = abs(net[net <= 0].sum())
    pf = wins / losses if losses > 0 else float('inf')
    t = net.mean() / (net.std(ddof=1) / np.sqrt(len(net))) if len(net) > 1 else 0
    print(f'{name:<22} n={len(v):>5}  net={net.mean()*1e4:+6.1f}bp  win={100*(net>0).mean():4.1f}%  PF={pf:5.2f}  t={t:+.2f}')


print('\n=== ORB+VWAP+MACD (entry->EOD, net 6bp RT) ===')
stat('LONG', longs)
stat('SHORT', shorts)
stat('LONG+SHORT', longs + [-x for x in shorts])
stat('baseline (all bars)', all_fwd)
