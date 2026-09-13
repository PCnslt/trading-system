import boto3, io, pandas as pd, numpy as np, re

# SUPERSEDED by research/atomics/full_universe_strategies.py (monthly, 6,551 names,
# split-neutralized + sub-$1 floor + listing-warmup gated). Kept as the weekly
# (5-day) cross-sectional reversal diagnostic. Defects fixed 2026-09-09:
#   1) split/reverse-split gaps now neutralized (single-day |ret|>40% zeroed before
#      cumprod adjusted close) -- was computing past5/fwd on raw split-unadjusted closes;
#   2) sub-$1 names excluded at each rebalance (penny bounce artifact);
#   3) listing-warmup gated (has_data at t and t+5 for the forward label).

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
r=s3.list_objects_v2(Bucket=BUCKET, Prefix='ibkr/equities/daily/', MaxKeys=400)
keys=[o['Key'] for o in r.get('Contents',[]) if o['Key'].endswith('.parquet')]
def is_common(s): return not re.search(r'[-.][WURPS]A?B?$|[-.]U$|PR[ABCDEFG]?$|[-.]WS$|[-.]WT$', s)
syms=sorted(set(k.split('/')[-1].replace('.parquet','') for k in keys))
syms=[s for s in syms if is_common(s)]
COST=0.0005
SPLIT=0.40
MIN_PRICE=1.0

closes={}
for s in syms:
    try:
        b=s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{s}.parquet')['Body'].read()
        d=pd.read_parquet(io.BytesIO(b)); d.columns=[c.lower() for c in d.columns]
        d['date']=pd.to_datetime(d['date'])
        d=d.dropna(subset=['close']); d=d[d['close']>0]
        d=d.set_index('date').sort_index()[['close']]
        closes[s]=d['close']
    except Exception: pass
px=pd.DataFrame(closes).sort_index()
Cv=np.array(px.to_numpy(np.float64), copy=True); Cv[Cv<=0]=np.nan
has_data=~np.isnan(Cv)
# split-neutralized adjusted close (cumprod of clipped daily returns)
R=Cv[1:]/Cv[:-1]-1.0
R=np.where(np.abs(R)>SPLIT, 0.0, R)
R=np.where(np.isnan(R), 0.0, R)
adj=np.empty(Cv.shape); adj[0]=1.0; adj[1:]=np.cumprod(1.0+R, axis=0)
adj=pd.DataFrame(adj, index=px.index, columns=px.columns)
raw=pd.DataFrame(np.where(has_data, Cv, np.nan), index=px.index, columns=px.columns)

# weekly (5-day) cross-sectional reversal, long-only bottom decile, rebalanced every 5 days
past5=adj/adj.shift(5)-1.0          # prior 5-day return (causal at close t, split-neutralized)
fwd=adj.shift(-5)/adj-1.0           # forward 5-day return (label)
hd5=raw.shift(-5).notna()           # has_data at t+5 (listing-warmup gate on the label)
rank=past5.rank(axis=1, pct=True)   # cross-sectional rank each day
# long bottom decile, rebalance every 5 days to avoid overlap
rebal_days=px.index[::5]
rows=[]
for d in rebal_days:
    r=rank.loc[d]
    floor=(raw.loc[d]>=MIN_PRICE)
    gate=(raw.loc[d].notna()) & hd5.loc[d]
    valid=floor & gate & r.notna()
    lo=r[valid & (r<=0.1)].index
    if len(lo)<3: continue
    f=fwd.loc[d, lo]
    rows.append(f.mean())
lr=pd.Series(rows).dropna()
exp=lr.mean()-COST
print(f'cross-sectional reversal (bottom decile, 5d hold, split-neutralized + >=$1 + warmup-gated):')
print(f'  n={len(lr)} rebalance dates, mean forward={lr.mean()*1e4:+.2f}bp, net={exp*1e4:+.2f}bp, PF={lr[lr>0].sum()/-lr[lr<0].sum():.2f}')
split=int(len(lr)*0.7)
print(f'  train: {lr[:split].mean()*1e4:+.2f}bp | OOS: {lr[split:].mean()*1e4:+.2f}bp')
t=lr.mean()/(lr.std()/np.sqrt(len(lr)))
print(f'  t-stat (rebalance-date): {t:.2f}')
