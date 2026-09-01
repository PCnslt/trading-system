import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX','NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def load(sym):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=f'ibkr/equities/1min/{sym}/')
    frames=[pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=o['Key'])['Body'].read())) for o in r.get('Contents',[])]
    if not frames: return None
    df=pd.concat(frames).sort_values('ts'); df['ts']=pd.to_datetime(df['ts'],unit='s')
    return df.set_index('ts').sort_index()

def daily_open(df):
    o=df['open'].resample('1D').first(); c=df['close'].resample('1D').last(); v=df['volume'].resample('1D').sum()
    return pd.DataFrame({'open':o,'close':c,'vol':v}).dropna()

events=[]
for sym in SYMS:
    df=load(sym)
    if df is None or len(df)<3000: continue
    d=daily_open(df)
    d['gap']=d['open']/d['close'].shift(1)-1
    d['avol']=d['vol']/d['vol'].rolling(20).mean()
    ev=d[(d['gap'].abs()>=0.02)&(d['avol']>=1.5)]
    for day, r in ev.iterrows():
        intra=df[(df.index.date==day.date())]
        if len(intra)<30: continue
        op=r['open']; direction=np.sign(r['gap'])
        # time to first +2% / -2% move from open (in minutes)
        cum=intra['close']/op-1
        tgt = (cum*direction).abs()
        t2 = tgt[tgt>=0.02]
        min2 = (t2.index[0]-intra.index[0]).total_seconds()/60 if len(t2) else np.nan
        events.append(dict(gap=abs(r['gap']), avol=r['avol'], direction=direction,
                           oc=r['close']/r['open']-1, min_to_2pct=min2))

E=pd.DataFrame(events)
print(f"events: {len(E)}")
print(f"median |open->close|: {E.oc.abs().median()*100:.2f}%")
print(f"P(reach +2% same-day): {E.min_to_2pct.notna().mean():.0%}")
print(f"median minutes to first 2%: {E.min_to_2pct.median():.0f}")
# speed vs gap size and volume
E['big_gap']=E.gap>=0.04; E['big_vol']=E.avol>=2.5
for f in ['big_gap','big_vol']:
    g=E.groupby(f).agg(move=('oc', lambda x: x.abs().median()), speed=('min_to_2pct','median'), reach=('min_to_2pct', lambda x: x.notna().mean()))
    print(f"\n{f}:\n{g.round(3)}")
# direction continuation vs gap size
E['cont']=(E.direction*E.oc)>0
print(f"\ncontinuation rate overall: {E.cont.mean():.0%}")
print(f"continuation rate (gap>=4%): {E[E.big_gap].cont.mean():.0%}  vs (gap<4%): {E[~E.big_gap].cont.mean():.0%}")
