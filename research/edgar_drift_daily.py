import boto3, io, pandas as pd, numpy as np

s3=boto3.client('s3',region_name='us-east-1'); B='trading-datalake-920641308584'
ev=pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B,Key='research/edgar_8k_timestamped.parquet')['Body'].read()))
et=ev['acceptance'].dt.tz_convert('America/New_York')
earn=ev[(et.dt.hour>=15)&(ev['items'].str.contains('2.02',na=False))].copy()
earn['day']=et[earn.index].dt.date
print(f'after-hours earnings 8-K events: {len(earn)}')

def loadd(sym):
    o=s3.get_object(Bucket=B,Key='ibkr/equities/daily/'+sym+'.parquet')['Body'].read()
    df=pd.read_parquet(io.BytesIO(o)); df['date']=pd.to_datetime(df['date'])
    return df.set_index('date').tz_localize(None)

# build market proxy from a broad set of daily stocks
import subprocess
# use the 400 daily symbols as market proxy
r=s3.list_objects_v2(Bucket=B,Prefix='ibkr/equities/daily/',MaxKeys=500)
syms=sorted(set(o['Key'].split('/')[-1].replace('.parquet','') for o in r.get('Contents',[]) if o['Key'].endswith('.parquet')))
# filter to common stocks (no warrants/units)
import re
syms=[s for s in syms if re.match(r'^[A-Z]{1,5}$',s)]
# market = equal-weight daily open->close of a sample
mr={}
for s in syms[:150]:
    try:
        d=loadd(s)
        mr[s]=d['close']/d['open']-1
    except: pass
mkt=pd.DataFrame(mr).mean(axis=1)

rows=[]
for _,e in earn.iterrows():
    sym=e['ticker']
    try: d=loadd(sym)
    except: continue
    fd=pd.Timestamp(e['day'])
    nxt=d['close'].index[d['close'].index>fd]
    if len(nxt)==0: continue
    nd=nxt[0]
    op=d['open'].get(nd); cl=d['close'].get(nd)
    prior_idx=d['close'].index[d['close'].index<nd]
    if pd.isna(op) or pd.isna(cl) or len(prior_idx)==0: continue
    prev=d['close'].get(prior_idx[-1])
    if pd.isna(prev): continue
    gap=op/prev-1; intra=cl/op-1
    rows.append({'sym':sym,'gap':gap,'intra':intra,'mkt':mkt.get(nd,np.nan),'day':nd})
df=pd.DataFrame(rows).dropna()
df['intra_resid']=df['intra']-df['mkt']
df['gap_resid']=df['gap']-df['mkt']
print(f'\nmatched events: {len(df)}')
print(f'gap mean={df["gap"].mean()*10000:.0f}bp median={df["gap"].median()*10000:.0f}bp')
print(f'intraday mean={df["intra"].mean()*10000:.0f}bp median={df["intra"].median()*10000:.0f}bp')
print(f'intra residual (market-adj) mean={df["intra_resid"].mean()*10000:.0f}bp median={df["intra_resid"].median()*10000:.0f}bp')
# clustered t-stat by day
daily_mean=df.groupby('day')['intra_resid'].mean()
t=daily_mean.mean()/(daily_mean.std()/np.sqrt(len(daily_mean)))
print(f'clustered (by day) t-stat = {t:.2f}  (n_days={len(daily_mean)})')
# sign: does gap direction predict intraday?
print(f'P(intra same sign as gap) = {(np.sign(df["gap"])==np.sign(df["intra"])).mean():.3f}')
