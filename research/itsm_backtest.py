#!/usr/bin/env python3
"""Market Intraday Momentum backtest (Gao, Han, Li, Zhou 2018 JFE) on SPY.

Rule: if the first half-hour return (prev close -> 10:00) is POSITIVE, go long the
last half-hour (15:30 -> 16:00). Long-only (skip down-mornings). One round-trip/day.
"""
import io, sys, time, os
import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo
from ib_insync import IB, Stock
import boto3

ET = ZoneInfo('America/New_York')
S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'
KEY = 'ibkr/equities/intraday/1min/SPY.parquet'

def fetch_spy():
    ib = IB(); ib.connect('127.0.0.1', 4001, clientId=192, timeout=30, readonly=True)
    c = Stock('SPY', 'SMART', 'USD'); ib.qualifyContracts(c)
    bars = ib.reqHistoricalData(c, endDateTime='', durationStr='2 Y',
                                barSizeSetting='30 mins', whatToShow='TRADES',
                                useRTH=1, formatDate=1)
    ib.disconnect()
    if not bars:
        raise SystemExit('no bars fetched')
    df = pd.DataFrame([{'date': b.date, 'open': b.open, 'high': b.high,
                        'low': b.low, 'close': b.close, 'volume': b.volume} for b in bars])
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    buf = io.BytesIO(); df.to_parquet(buf)
    S3.put_object(Bucket=BUCKET, Key=KEY, Body=buf.getvalue())
    print(f'SPY 30-min fetched+saved: {len(df)} bars, {df.index.min()} -> {df.index.max()}')
    return df

def load_or_fetch():
    try:
        o = S3.get_object(Bucket=BUCKET, Key=KEY)
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) > 5000:
            print(f'loaded cached SPY 30-min: {len(df)} bars')
            return df
    except Exception:
        pass
    return fetch_spy()

def run(df, cost_bp=1.0):
    cost = cost_bp / 1e4
    d = df.copy()
    d['day'] = d.index.date
    day_close = d.groupby('day')['close'].last()
    days = sorted(d['day'].unique())
    rows = []
    for i, day in enumerate(days):
        if i == 0:
            continue
        prev_close = day_close.iloc[i-1]
        m = d[d['day'] == day]
        if len(m) < 10:
            continue
        # 09:30-10:00 bar (first half-hour) close = 10:00 price
        first = m[m.index.time == pd.Timestamp('09:30').time()]
        # 15:30-16:00 bar (last half-hour)
        last = m[m.index.time == pd.Timestamp('15:30').time()]
        if first.empty or last.empty:
            continue
        p10 = first['close'].iloc[-1]
        first_ret = p10 / prev_close - 1
        last_ret = last['close'].iloc[-1] / last['open'].iloc[0] - 1
        rows.append((day, first_ret, last_ret))
    r = pd.DataFrame(rows, columns=['day', 'first_ret', 'last_ret']).set_index('day')
    r['trade'] = (r['first_ret'] > 0)
    r['pnl'] = np.where(r['trade'], r['last_ret'] - 2*cost, 0.0)
    r['always'] = r['last_ret'] - 2*cost
    def tstat(x):
        m = x.mean(); s = x.std(ddof=1)
        return m / (s/np.sqrt(len(x))) if s > 0 and len(x) > 30 else np.nan
    n = len(r)
    nlong = r['trade'].sum()
    pnl = r.loc[r['trade'], 'pnl']
    always = r['always']
    print(f'\n=== Market Intraday Momentum — SPY ({cost_bp}bp/side) ===')
    print(f'days={n}  up-mornings={nlong} ({nlong/n:.0%})  down-mornings skipped={n-nlong}')
    print(f'up-morning days:   last-30 avg {r.loc[r["trade"],"last_ret"].mean()*1e4:+.1f}bp  win {(r.loc[r["trade"],"last_ret"]>0).mean():.0%}')
    print(f'down-morning days: last-30 avg {r.loc[~r["trade"],"last_ret"].mean()*1e4:+.1f}bp  win {(r.loc[~r["trade"],"last_ret"]>0).mean():.0%}')
    print(f'\nLONG-ONLY (up-mornings) net {cost_bp}bp: avg {pnl.mean()*1e4:+.2f}bp/trade  t {tstat(pnl):+.2f}  trades {nlong}')
    print(f'ALWAYS-LONG-30 benchmark net:     avg {always.mean()*1e4:+.2f}bp/trade  t {tstat(always):+.2f}')
    split = r.index[int(n*0.8)]
    oos = pnl.loc[pnl.index >= split]
    print(f'OOS (last 20%): avg {oos.mean()*1e4:+.2f}bp/trade  t {tstat(oos):+.2f}  trades {len(oos)}')

if __name__ == '__main__':
    df = load_or_fetch()
    for c in [0.5, 1.0, 2.0]:
        run(df, c)

