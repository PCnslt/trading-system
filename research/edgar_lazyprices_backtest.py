#!/usr/bin/env python3
"""Lazy Prices textual-CHANGE backtest (small sample).

Loads research/edgar_lazyprices_events.parquet (sim/change per 10-K filing),
joins IBKR daily closes from S3, computes forward returns market-adjusted,
and reports whether the change signal is directional.
"""
import io, os
import numpy as np
import pandas as pd
import boto3
from scipy import stats

BUCKET = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')
EV = os.path.join(os.path.dirname(__file__), 'edgar_lazyprices_events.parquet')
ev = pd.read_parquet(EV)
ev['filing_date'] = pd.to_datetime(ev['filing_date'])

def loadd(sym):
    o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')['Body'].read()
    df = pd.read_parquet(io.BytesIO(o))
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date')

# build equal-weight market daily return index over universe symbols
syms = sorted(ev['ticker'].unique())
rets = {}
for s in syms:
    try:
        d = loadd(s)
        rets[s] = d['close'].pct_change()
    except Exception:
        pass
mkt = pd.DataFrame(rets).mean(axis=1)  # equal-weight daily market return

def fwd_ret(sym, fd, h):
    """Forward close-to-close return over h trading days, entry = close on first
    trading day >= filing date (signal public at that day's close)."""
    try:
        d = loadd(sym)
    except Exception:
        return np.nan, np.nan
    idx = d.index[d.index >= fd]
    if len(idx) < h + 1:
        return np.nan, np.nan
    e = idx[0]
    ex = idx[h]
    r = d['close'].loc[ex] / d['close'].loc[e] - 1
    # market return over same calendar window (trading days of the stock)
    m = (1 + mkt.loc[e:ex]).prod() - 1 if not pd.isna(mkt.loc[e]) else np.nan
    return r, m

horizons = {'1mo': 21, '3mo': 63, '6mo': 126}
out = ev.copy()
for name, h in horizons.items():
    fwd, mkt_adj = [], []
    for _, row in ev.iterrows():
        r, m = fwd_ret(row['ticker'], row['filing_date'], h)
        fwd.append(r)
        mkt_adj.append(r - m if (not pd.isna(r) and not pd.isna(m)) else np.nan)
    out[f'fwd_{name}'] = fwd
    out[f'fwd_{name}_mktadj'] = mkt_adj

out = out.dropna(subset=['fwd_1mo'])
print(f'events with matched forward returns: {len(out)} / {len(ev)}')
print(f'unique tickers: {out.ticker.nunique()}')
print(f'filing date range: {out.filing_date.min().date()} .. {out.filing_date.max().date()}\n')

# ---- correlation: change (high) -> lower forward return? ----
print('Spearman corr(change, fwd_return):')
for name in horizons:
    m = out[['change', f'fwd_{name}_mktadj']].dropna()
    rho, p = stats.spearmanr(m['change'], m[f'fwd_{name}_mktadj'])
    print(f'  {name}: rho={rho:+.3f} (p={p:.3f}, n={len(m)})')

# ---- tercile split on change (1-sim) ----
print('\nTercile split on change (top = biggest textual change):')
for name in horizons:
    col = f'fwd_{name}_mktadj'
    m = out[['change', col]].dropna()
    m = m.sort_values('change')
    k = len(m) // 3
    hi = m.iloc[-k:]   # high change
    lo = m.iloc[:k]    # low change
    ls = hi[col].mean() - lo[col].mean()
    # paper: SHORT high-change, LONG low-change
    strat = lo[col].mean() - hi[col].mean()
    print(f'  {name}: low-change mean={lo[col].mean()*10000:+.1f}bp  '
          f'high-change mean={hi[col].mean()*10000:+.1f}bp  '
          f'long-low/short-high={strat*10000:+.1f}bp  (n={k} each)')

# ---- long-short (low-change long, high-change short) with sign consistency ----
print('\nLong (bottom-change tercile) vs Short (top-change tercile) — market-adj, bp:')
for name in horizons:
    col = f'fwd_{name}_mktadj'
    m = out[['change', 'filing_date', 'ticker', col]].dropna().sort_values('change')
    k = len(m) // 3
    hi = m.iloc[-k:]; lo = m.iloc[:k]
    spread = (lo[col].to_numpy() - hi[col].to_numpy()) * 10000  # positional pairing (sorted by change)
    t = spread.mean() / (spread.std() / np.sqrt(len(spread))) if spread.std() > 0 else np.nan
    # clustered by filing_date (coarse: mean per date then t-stat)
    d_lo = lo['filing_date'].to_numpy(); d_hi = hi['filing_date'].to_numpy()
    dd = pd.DataFrame({'d': d_lo, 'x': spread}).groupby('d')['x'].mean()
    t_cl = dd.mean() / (dd.std()/np.sqrt(len(dd))) if dd.std() > 0 else np.nan
    print(f'  {name}: spread mean={spread.mean():+.1f}bp median={np.median(spread):+.1f}bp '
          f'win={ (spread>0).mean()*100:.0f}%  t={t:+.2f}  t_clust(date)={t_cl:+.2f}  n={len(spread)}')

print('\nRaw (not market-adj) forward returns by tercile:')
for name in horizons:
    col = f'fwd_{name}'
    m = out[['change', col]].dropna().sort_values('change')
    k = len(m)//3
    print(f'  {name}: low-change={m[col].iloc[:k].mean()*10000:+.1f}bp  high-change={m[col].iloc[-k:].mean()*10000:+.1f}bp')
