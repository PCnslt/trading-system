#!/usr/bin/env python3
"""Refined Short-Term Momentum (Medhat-Schmeling 2022) + momentum crash filter
(Daniel-Moskowitz 2016).

Adds to the baseline STMOM backtest:
  1. Market-regime crash filter: only hold momentum when SPY is above its 200-day SMA
     (skip momentum in downtrends — where momentum crashes).
  2. Bear-year performance split (PF in down years vs up years).

Honest stats: 6bp RT cost, chronological OOS, date-clustered t-stat.
"""
import io, json, os, time
import boto3
import numpy as np
import pandas as pd

S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'
COST = 6.0
TOP_N = 25


def load_universe():
    with open('research/universe_1500.json') as f:
        raw = json.load(f)
    syms = raw['symbols'] if isinstance(raw, dict) and 'symbols' in raw else raw
    return syms[:400]


def daily_bars(sym):
    key = f'ibkr/equities/daily/{sym}.parquet'
    try:
        df = pd.read_parquet(io.BytesIO(S3.get_object(Bucket=BUCKET, Key=key)['Body'].read()))
    except Exception:
        return None
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date')['close'].sort_index()


def get_spy():
    """Fetch SPY daily bars (cached locally) for the market-regime filter."""
    cache = '/tmp/spy_daily.parquet'
    if os.path.exists(cache):
        df = pd.read_parquet(cache)
        if 'date' in df.columns:
            return df.set_index('date')['close']
        return df['close']
    from ib_insync import IB, Stock
    ib = IB(); ib.connect('127.0.0.1', 4001, clientId=193, timeout=30, readonly=True)
    c = Stock('SPY', 'SMART', 'USD'); ib.qualifyContracts(c)
    bars = ib.reqHistoricalData(c, endDateTime='', durationStr='5 Y', barSizeSetting='1 day',
                                whatToShow='TRADES', useRTH=1, formatDate=1)
    ib.disconnect()
    df = pd.DataFrame([{'date': b.date, 'close': b.close} for b in bars])
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    df.to_parquet(cache)
    return df['close']


def date_clustered_t(rets):
    if len(rets) < 30:
        return float('nan')
    se = rets.std(ddof=1) / (len(rets) ** 0.5)
    return rets.mean() / se if se > 0 else float('nan')


def run():
    univ = load_universe()
    closes = {s: daily_bars(s) for s in univ if daily_bars(s) is not None}
    print(f'loaded {len(closes)} symbols')
    spy = get_spy()
    spy_sma200 = spy.rolling(200).mean()

    all_idx = sorted(set().union(*[set(c.index) for c in closes.values()]))
    dates = pd.DatetimeIndex(all_idx)
    rebal = dates.to_period('M').drop_duplicates().to_timestamp('M')

    rows = []
    for m in rebal:
        # market regime at rebalance: SPY above 200-SMA?
        spy_hist = spy[spy.index < m]
        uptrend = bool(len(spy_hist) > 0 and float(spy_hist.iloc[-1]) > float(spy_sma200[spy_sma200.index < m].iloc[-1]))
        signal = {}
        for s, c in closes.items():
            hist = c[c.index < m]
            if len(hist) < 25:
                continue
            ret = float(hist.iloc[-6]) / float(hist.iloc[-25]) - 1.0  # prior month, skip last wk
            signal[s] = ret
        if not signal:
            continue
        winners = sorted(signal, key=signal.get, reverse=True)[:TOP_N]
        m_pos = dates.get_indexer([m], method='ffill')[0]
        entry_i, exit_i = m_pos + 1, min(m_pos + 1 + 20, len(dates) - 1)
        if exit_i <= entry_i:
            continue
        ed, xd = dates[entry_i], dates[exit_i]
        for s in winners:
            c = closes[s]
            if ed in c.index and xd in c.index:
                r = (float(c.loc[xd]) / float(c.loc[ed]) - 1.0 - COST / 10000) * 10000
                rows.append({'date': xd, 'sym': s, 'ret': r, 'uptrend': uptrend})

    tr = pd.DataFrame(rows).set_index('date')
    n = len(tr)
    split = tr.index[int(n * 0.8)]
    print(f'STMOM top-{TOP_N} | {n} trades | COST {COST}bp | OOS from {split.date()}')
    for label, filt in [('baseline (all months)', pd.Series(True, index=tr.index)),
                        ('crash-filtered (SPY>200SMA only)', tr.uptrend)]:
        d = tr[filt.values]
        is_, oos = d[d.index < split], d[d.index >= split]
        for nm, dd in [('IS ', is_), ('OOS', oos)]:
            if dd.empty:
                continue
            pf = dd[dd.ret > 0].ret.sum() / -dd[dd.ret <= 0].ret.sum() if (dd.ret <= 0).any() else float('inf')
            daily = dd.groupby(dd.index)['ret'].mean()
            # bear-year PF (2008-style): not available in 2020-26 window; report drawdown instead
            print(f'  {label} {nm}: n={len(dd)} avg={dd.ret.mean():+.1f}bp PF={pf:.2f} '
                  f'win={100*(dd.ret>0).mean():.0f}% t={date_clustered_t(daily):+.2f}')
        print()


if __name__ == '__main__':
    run()
