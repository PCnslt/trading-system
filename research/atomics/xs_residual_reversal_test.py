#!/usr/bin/env python3
"""Cross-sectional residual mean-reversion (the prompt's construction) — honest test.

Prompt: regress asset returns vs market (rolling OLS beta), extract residual epsilon,
rolling 20-period Z-score, long Z<=-2 / short Z>=+2, market-neutral. Cost 5bp.
We test the CORE question on the 40-name 5-min lake (resampled to 15-min):
does an extreme idiosyncratic residual Z-score predict REVERSION next bar / next hour,
net of cost, and does it BEAT a shuffled-symbol placebo?

Construction used here (beta=1 market-relative residual — the OLS-beta refinement
does not change the sign, see ledger):  resid_i,t = r_i,t - r_mkt,t (equal-weight),
z_i,t = (resid_i,t - mean_20) / std_20  per asset over the trailing 20 bars.
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

# resample to 15-min per symbol
def resample15(g):
    g = g.set_index('date')
    r = g.resample('15min').agg({'open': 'first', 'high': 'max', 'low': 'min',
                                 'close': 'last', 'volume': 'sum'}).dropna(subset=['close'])
    return r
prices = {}
for sym, g in df.groupby('symbol'):
    prices[sym] = resample15(g)['close']
close = pd.DataFrame(prices).sort_index()
ret = close.pct_change()

# market = equal-weight mean return across the cross-section
mkt = ret.mean(axis=1)

# residual = asset return - market return
resid = ret.sub(mkt, axis=0)

# rolling 20-bar z-score per asset
mean20 = resid.rolling(20).mean()
std20 = resid.rolling(20).std()
z = (resid - mean20) / std20

# forward returns (next 15-min bar, and next 1-hour = 4 bars)
fwd1 = close.shift(-1) / close - 1.0
fwd4 = close.shift(-4) / close - 1.0

COST = 0.0005  # 5bp per side -> charge 5bp once (entry); market-neutral round-trip ~10bp

def collect(fwd, zz, lo=-2.0, hi=2.0):
    long_mask = zz <= lo
    short_mask = zz >= hi
    L = fwd[long_mask].values
    S = fwd[short_mask].values
    return L, S

for horizon, fwd in [('15min', fwd1), ('1hour', fwd4)]:
    L, S = collect(fwd, z)
    L = L[~np.isnan(L)]; S = S[~np.isnan(S)]
    ls = np.concatenate([L, -S])  # long-short (long low-z, short high-z)
    def st(v):
        v = v - COST
        return (len(v), v.mean()*1e4, (v>0).mean()*100,
                (v[v>0].sum()/abs(v[v<=0].sum()) if (v<=0).any() else float('inf')),
                v.mean()/(v.std(ddof=1)/np.sqrt(len(v))) if len(v)>1 else 0)
    nL,mL,wL,pfL,tL = st(L); nS,mS,wS,pfS,tS = st(S); nLS,mLS,wLS,pfLS,tLS = st(ls)
    print(f'[{horizon}]  LONG(z<=-2) n={nL} net={mL:+5.1f}bp win={wL:.0f}% PF={pfL:.2f} t={tL:+.1f}  |  '
          f'SHORT(z>=+2) n={nS} net={mS:+5.1f}bp PF={pfS:.2f} t={tS:+.1f}  |  '
          f'LONG-SHORT n={nLS} net={mLS:+5.1f}bp PF={pfLS:.2f} t={tLS:+.1f}')

# --- placebo: shuffle symbol identities across the cross-section ---
rng = np.random.default_rng(0)
ret_shuf = ret.copy()
# shuffle columns (symbols) independently per row -> destroys cross-sectional identity
arr = ret_shuf.values.copy()
for i in range(arr.shape[0]):
    rng.shuffle(arr[i])
ret_shuf = pd.DataFrame(arr, index=ret.index, columns=ret.columns)
mkt_shuf = ret_shuf.mean(axis=1)
resid_shuf = ret_shuf.sub(mkt_shuf, axis=0)
z_shuf = (resid_shuf - resid_shuf.rolling(20).mean()) / resid_shuf.rolling(20).std()

print('\n=== PLACEBO (symbol identities shuffled) — 1-hour horizon ===')
L, S = collect(fwd4, z_shuf)
L = L[~np.isnan(L)]; S = S[~np.isnan(S)]
ls = np.concatenate([L, -S])
v = ls - COST
print(f'LONG-SHORT placebo: n={len(v)} net={v.mean()*1e4:+5.1f}bp PF={v[v>0].sum()/abs(v[v<=0].sum()):.2f} '
      f't={v.mean()/(v.std(ddof=1)/np.sqrt(len(v))):+.1f}')
