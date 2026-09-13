#!/usr/bin/env python3
"""Volatility Risk Premium (VRP) measurement — the documented options SELL-side edge.

Quantifies implied vol (VIX) vs subsequent realized vol on SPY. A persistently positive
VRP is the economic basis for cash-secured puts / covered calls / short-vol — the one
options family with a documented positive expectancy (Bakshi-Kapadia 2003 RFS,
Coval-Shumway 2001 JF, Carr-Wu 2009 RFS).

Honest, testable, directly relevant to a Level-2 (CSP / covered call) account.
"""
import numpy as np, pandas as pd
import yfinance as yf

spy = yf.download('SPY', start='2000-01-01', auto_adjust=False, progress=False)['Close']
vix = yf.download('^VIX', start='2000-01-01', auto_adjust=False, progress=False)['Close']
spy = spy[~spy.index.duplicated(keep='last')]
vix = vix[~vix.index.duplicated(keep='last')]

# realized 30-day vol: std of daily log returns over trailing 21 trading days, annualized
ret = np.log(spy / spy.shift(1))
rvol21 = ret.rolling(21).std() * np.sqrt(252) * 100   # in vol points (annualized %)

df = pd.DataFrame({'vix': vix, 'rvol': rvol21}).dropna()
df['vrp'] = df['vix'] - df['rvol']                    # implied - realized (vol points)

print(f"sample: {df.index.min().date()} .. {df.index.max().date()}, n={len(df)} trading days")
print(f"\n{'metric':28s} {'value':>12s}")
print('-' * 42)
print(f"{'VIX (implied 30d vol) mean':28s} {df['vix'].mean():>10.2f} vol pts")
print(f"{'realized 30d vol mean':28s} {df['rvol'].mean():>10.2f} vol pts")
print(f"{'VRP mean (implied-realized)':28s} {df['vrp'].mean():>+10.2f} vol pts")
print(f"{'VRP median':28s} {df['vrp'].median():>+10.2f} vol pts")
print(f"{'% of days VIX > realized':28s} {(df['vrp']>0).mean()*100:>9.1f}%")

# variance premium (more precise)
vvix = (df['vix']/100)**2          # implied variance (30d)
rv = (df['rvol']/100)**2           # realized variance (trailing 21d)
df['vvarp'] = vvix - rv
print(f"{'variance premium mean':28s} {df['vvarp'].mean():>+10.5f}")
print(f"{'variance premium (annualized % of spot vol^2)':28s}")

# by regime: pre-2010 vs post-2010, and high vs low VIX
for label, mask in [('2000-2010', df.index < '2010-01-01'),
                    ('2010-2020', (df.index >= '2010-01-01') & (df.index < '2020-01-01')),
                    ('2020-2026', df.index >= '2020-01-01')]:
    s = df[mask]
    print(f"  {label:12s}: VRP mean {s['vrp'].mean():+.2f} vol pts | %pos {(s['vrp']>0).mean()*100:.0f}% | n={len(s)}")

# what a seller actually banks per 30d (the tradable premium, bp of notional is the vol spread)
print('\nVRP by VIX regime (where the premium concentrates):')
for lo, hi in [(0,15),(15,20),(20,30),(30,100)]:
    s = df[(df['vix']>=lo)&(df['vix']<hi)]
    if len(s) < 20: continue
    print(f"  VIX {lo}-{hi:>3}: VRP mean {s['vrp'].mean():+5.2f} vol pts | %pos {(s['vrp']>0).mean()*100:4.0f}% | n={len(s)}")
