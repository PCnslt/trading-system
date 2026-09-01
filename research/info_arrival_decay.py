import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX','NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def load(sym):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=f'ibkr/equities/1min/{sym}/')
    frames=[]
    for o in r.get('Contents', []):
        b=s3.get_object(Bucket=BUCKET, Key=o['Key'])['Body'].read()
        frames.append(pd.read_parquet(io.BytesIO(b)))
    if not frames: return None
    df=pd.concat(frames).sort_values('ts')
    df['ts']=pd.to_datetime(df['ts'], unit='s')
    df=df.set_index('ts').sort_index()
    return df

def daily(df):
    # resample 1-min to daily open/high/low/close/volume
    o=df['open'].resample('1D').first(); c=df['close'].resample('1D').last()
    v=df['volume'].resample('1D').sum()
    d=pd.DataFrame({'open':o,'close':c,'vol':v}).dropna()
    return d

gaps=[]; cont=[]; rev=[]
for sym in SYMS:
    df=load(sym)
    if df is None or len(df)<2000: continue
    d=daily(df)
    d['gap']=d['open']/d['close'].shift(1)-1
    d['oc']=d['close']/d['open']-1
    d['avol']=d['vol']/d['vol'].rolling(20).mean()
    # info arrival: |gap|>=2% and abnormal volume
    ev=d[(d['gap'].abs()>=0.02)&(d['avol']>=1.5)]
    # signal: gap direction; measure open->close (continuation if same sign, reversal if opposite)
    for _,r in ev.iterrows():
        g=r['gap']
        if g>0:
            (cont if r['oc']>0 else rev).append(r['oc'])
        else:
            (cont if r['oc']<0 else rev).append(r['oc'])

print(f"info-arrival events (|gap|>=2%, vol>=1.5x): {len(cont)+len(rev)}")
print(f"  gap CONTINUATION: {len(cont)} ({len(cont)/(len(cont)+len(rev)):.0%}), mean open->close {np.mean(cont)*100:.2f}%")
print(f"  gap REVERSAL:     {len(rev)} ({len(rev)/(len(cont)+len(rev)):.0%}), mean open->close {np.mean(rev)*100:.2f}%")
allr = cont+rev
print(f"  P(|open->close| > 1%): {np.mean([abs(x)>0.01 for x in allr]):.0%}")
print(f"  P(|open->close| > 2%): {np.mean([abs(x)>0.02 for x in allr]):.0%}")
print(f"  mean |open->close|: {np.mean([abs(x) for x in allr])*100:.2f}%")
