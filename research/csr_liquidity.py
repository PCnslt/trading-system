import boto3, io, pandas as pd, numpy as np, re

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
r=s3.list_objects_v2(Bucket=BUCKET, Prefix='ibkr/equities/daily/', MaxKeys=400)
keys=[o['Key'] for o in r.get('Contents',[]) if o['Key'].endswith('.parquet')]
def is_common(s): return not re.search(r'[-.][WURPS]A?B?$|[-.]U$|PR[ABCDEFG]?$|[-.]WS$|[-.]WT$', s)
syms=sorted(set(k.split('/')[-1].replace('.parquet','') for k in keys))
syms=[s for s in syms if is_common(s)]

closes={}; dvol={}
for s in syms:
    try:
        b=s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{s}.parquet')['Body'].read()
        d=pd.read_parquet(io.BytesIO(b)).sort_index(); d.columns=[c.lower() for c in d.columns]
        closes[s]=d['close']; dvol[s]=(d['close']*d['volume']).mean()  # avg dollar volume
    except Exception: pass
px=pd.DataFrame(closes).sort_index()
past5=px/px.shift(5)-1.0; fwd=px.shift(-5)/px-1.0; rank=past5.rank(axis=1,pct=True)

def run(mask_fn, label):
    cols=[c for c in px.columns if mask_fn(c)]
    rk=rank[cols]
    rows=[]
    for d in px.index[::5]:
        lo=rk.loc[d][rk.loc[d]<=0.1].index
        if len(lo)<3: continue
        rows.append(fwd.loc[d,lo].mean())
    lr=pd.Series(rows).dropna()
    t=lr.mean()/(lr.std()/np.sqrt(len(lr)))
    print(f'{label:40s}: n={len(lr):4d} net(50bp)={lr.mean()*1e4-50:+.1f}bp t={t:.2f}')

run(lambda c: True, 'ALL common stocks (398)')
run(lambda c: px[c].iloc[-1]>=5, 'price >= $5')
run(lambda c: px[c].iloc[-1]>=10, 'price >= $10')
run(lambda c: dvol[c]>=2e6, 'avg dollar vol >= $2M/day')
run(lambda c: dvol[c]>=10e6, 'avg dollar vol >= $10M/day')
run(lambda c: dvol[c]>=50e6, 'avg dollar vol >= $50M/day (large-cap)')
run(lambda c: (px[c].iloc[-1]>=10) and (dvol[c]>=10e6), 'price>=10 AND dollar vol>=10M')
