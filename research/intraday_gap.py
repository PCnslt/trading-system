import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
P5='ibkr/equities/5min/'; PD='ibkr/equities/daily/'

def load5(sym):
    o=s3.get_object(Bucket=BUCKET,Key=P5+sym+'.parquet')['Body'].read()
    return pd.read_parquet(io.BytesIO(o))

def loadd(sym):
    o=s3.get_object(Bucket=BUCKET,Key=PD+sym+'.parquet')['Body'].read()
    return pd.read_parquet(io.BytesIO(o))

SYMS=['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD']
rows=[]
for sym in SYMS:
    try:
        m5=load5(sym); d=loadd(sym)
    except Exception as e:
        continue
    m5['date']=pd.to_datetime(m5['date']); m5=m5.set_index('date'); m5.index=m5.index.tz_localize(None)
    d['date']=pd.to_datetime(d['date']); d=d.set_index('date'); d.index=d.index.tz_localize(None)
    # gap = open vs prior close
    op=m5['open'].resample('D').first()
    cl=d['close']
    prev_close=cl.shift(1)
    gap=op/prev_close-1
    # intraday return open->close (using m5 close at day end)
    m5close=m5['close'].resample('D').last()
    intra=m5close/op-1
    f=pd.DataFrame({'gap':gap,'intra':intra,'prev_close':prev_close}).dropna()
    rows.append(f)
df=pd.concat(rows)

# bins of gap: >2%, 1-2%, 0-1%, -1-0%, -1--2%, <-2%
bins=[-99,-0.02,-0.01,0,0.01,0.02,99]
df['gbin']=pd.cut(df['gap'],bins,labels=['<-2%','-2..-1%','-1..0%','0..1%','1..2%','>2%'])
g=df.groupby('gbin',observed=True)['intra'].agg(['mean','count'])
g['mean']=g['mean']*10000
print('GAP -> INTRADAY (open->close) return in bp:')
print(g.round(1))
# gap continuation vs reversal: sign correlation
df['gap_dir']=np.sign(df['gap']); df['intra_dir']=np.sign(df['intra'])
cont=(df['gap_dir']==df['intra_dir']).mean()
print(f'\nP(intraday same direction as gap) = {cont:.3f}  (n={len(df)})')
