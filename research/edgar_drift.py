import boto3, io, pandas as pd, numpy as np

s3=boto3.client('s3',region_name='us-east-1'); B='trading-datalake-920641308584'
ev=pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B,Key='research/edgar_8k_timestamped.parquet')['Body'].read()))
# Item 2.02 = earnings results; filter to those, after-hours (>=16:00 ET)
et=ev['acceptance'].dt.tz_convert('America/New_York')
earn=ev[(et.dt.hour>=15)&(ev['items'].str.contains('2.02',na=False))].copy()
earn['day']=et[earn.index].dt.date
print(f'after-hours earnings 8-K (Item 2.02): {len(earn)} events')

def load5(sym):
    o=s3.get_object(Bucket=B,Key='ibkr/equities/5min/'+sym+'.parquet')['Body'].read()
    df=pd.read_parquet(io.BytesIO(o)); df['date']=pd.to_datetime(df['date'])
    return df.set_index('date').tz_localize(None)

# daily open/close per symbol from 5-min
daily={}
for s in ['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX','INTC','MU','PLTR','ORCL','CRM','COST','UNH','LLY','JPM','V']:
    try:
        m5=load5(s)
        daily[s]={'open':m5['open'].resample('D').first(),'close':m5['close'].resample('D').last()}
    except: pass
# market proxy = equal-weight daily open->close
mr={s:d['close']/d['open']-1 for s,d in daily.items()}
mkt=pd.DataFrame(mr).mean(axis=1)

rows=[]
for _,e in earn.iterrows():
    sym=e['ticker']
    if sym not in daily: continue
    d=daily[sym]
    # next trading day after filing day
    fd=pd.Timestamp(e['day'])
    nxt=d['close'].index[d['close'].index>fd]
    if len(nxt)==0: continue
    nd=nxt[0]
    op=d['open'].get(nd); cl=d['close'].get(nd)
    if pd.isna(op) or pd.isna(cl): continue
    prior_idx=d['close'].index[d['close'].index<nd]
    if len(prior_idx)==0: continue
    prev=d['close'].get(prior_idx[-1])
    if pd.isna(prev): continue
    gap=op/prev-1
    intra=cl/op-1
    rows.append({'sym':sym,'gap':gap,'intra':intra,'mkt':mkt.get(nd,np.nan)})
df=pd.DataFrame(rows).dropna()
# residual = intra - market
df['intra_resid']=df['intra']-df['mkt']
print(f'\nmatched next-session events: {len(df)}')
print(f'gap (open vs prior close): mean={df["gap"].mean()*10000:.1f}bp  median={df["gap"].median()*10000:.1f}bp')
print(f'intraday (open->close): mean={df["intra"].mean()*10000:.1f}bp  median={df["intra"].median()*10000:.1f}bp')
print(f'residual (intra - market): mean={df["intra_resid"].mean()*10000:.1f}bp  median={df["intra_resid"].median()*10000:.1f}bp')
# sign test: does the gap direction predict intraday?
print(f'P(intra same sign as gap) = {(np.sign(df["gap"])==np.sign(df["intra"])).mean():.3f}')
