import boto3, io, pandas as pd, numpy as np, re

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
r=s3.list_objects_v2(Bucket=BUCKET, Prefix='ibkr/equities/daily/', MaxKeys=400)
keys=[o['Key'] for o in r.get('Contents',[]) if o['Key'].endswith('.parquet')]
def is_common(s): return not re.search(r'[-.][WURPS]A?B?$|[-.]U$|PR[ABCDEFG]?$|[-.]WS$|[-.]WT$', s)
syms=sorted(set(k.split('/')[-1].replace('.parquet','') for k in keys))
syms=[s for s in syms if is_common(s)]
COST=0.0005

closes={}
for s in syms:
    try:
        b=s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{s}.parquet')['Body'].read()
        d=pd.read_parquet(io.BytesIO(b)).sort_index(); d.columns=[c.lower() for c in d.columns]
        closes[s]=d['close']
    except Exception: pass
px=pd.DataFrame(closes).sort_index()
ret=px.pct_change()
# weekly (5-day) cross-sectional reversal, long-only bottom decile, rebalanced every 5 days
past5=px/px.shift(5)-1.0          # prior 5-day return (causal at close t)
fwd=px.shift(-5)/px-1.0           # forward 5-day return (label)
rank=past5.rank(axis=1, pct=True)  # cross-sectional rank each day
# long bottom decile, rebalance every 5 days to avoid overlap
rebal_days=px.index[::5]
rows=[]
for d in rebal_days:
    r=rank.loc[d]; lo=r[r<=0.1].index
    if len(lo)<3: continue
    f=fwd.loc[d, lo]
    rows.append(f.mean())
lr=pd.Series(rows).dropna()
exp=lr.mean()-COST
print(f'cross-sectional reversal (bottom decile, 5d hold):')
print(f'  n={len(lr)} rebalance dates, mean forward={lr.mean()*1e4:+.2f}bp, net={exp*1e4:+.2f}bp, PF={lr[lr>0].sum()/-lr[lr<0].sum():.2f}')
split=int(len(lr)*0.7)
print(f'  train: {lr[:split].mean()*1e4:+.2f}bp | OOS: {lr[split:].mean()*1e4:+.2f}bp')
t=lr.mean()/(lr.std()/np.sqrt(len(lr)))
print(f'  t-stat (rebalance-date): {t:.2f}')
