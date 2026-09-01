import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX','NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def load(sym):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=f'ibkr/equities/1min/{sym}/')
    frames=[pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=o['Key'])['Body'].read())) for o in r.get('Contents',[])]
    if not frames: return None
    df=pd.concat(frames).sort_values('ts'); df['ts']=pd.to_datetime(df['ts'],unit='s')
    return df.set_index('ts').sort_index()

rows=[]
for sym in SYMS:
    df=load(sym)
    if df is None or len(df)<3000: continue
    o=df['open'].resample('1D').first(); c=df['close'].resample('1D').last(); v=df['volume'].resample('1D').sum()
    d=pd.DataFrame({'open':o,'close':c,'vol':v}).dropna()
    d['gap']=d['open']/d['close'].shift(1)-1
    d['avol']=d['vol']/d['vol'].rolling(20).mean()
    ev=d[(d['gap'].abs()>=0.02)&(d['avol']>=1.5)]
    for day, r in ev.iterrows():
        intra=df[(df.index.date==day.date())]
        if len(intra)<30: continue
        op=r['open']; sgn=np.sign(r['gap'])
        cum=intra['close']/op-1
        # signed first passage: does price hit +2% or -2% first?
        hit_up = cum[cum>=0.02]
        hit_dn = cum[cum<=-0.02]
        first_up = (hit_up.index[0]-intra.index[0]).total_seconds()/60 if len(hit_up) else np.nan
        first_dn = (hit_dn.index[0]-intra.index[0]).total_seconds()/60 if len(hit_dn) else np.nan
        # max adverse excursion vs gap direction before hitting the gap-direction target
        if sgn>0:
            tgt_min = first_up; mae = cum.min() if first_up and not np.isnan(first_up) else np.nan
            win = (not np.isnan(first_up)) and (np.isnan(first_dn) or first_up<first_dn)
        else:
            tgt_min = first_dn; mae = cum.max() if first_dn and not np.isnan(first_dn) else np.nan
            win = (not np.isnan(first_dn)) and (np.isnan(first_up) or first_dn<first_up)
        rows.append(dict(sgn=sgn, win=win, tgt_min=tgt_min, mae=mae, gap=abs(r['gap']), avol=r['avol']))

E=pd.DataFrame(rows)
print(f"events: {len(E)}")
print(f"P(gap-direction target hit FIRST): {E.win.mean():.0%}")
print(f"P(opposite target hit first): {(~E.win).mean():.0%}")
print(f"median time to gap-direction target: {E.tgt_min.median():.0f} min")
print(f"median max adverse excursion (vs gap dir, winners): {E[E.win].mae.median()*100:.2f}%")
print(f"median max adverse excursion (losers): {E[~E.win].mae.median()*100:.2f}%")
# condition on volume
g=E.groupby(E.avol>=2.5).agg(win=('win','mean'), tgt=('tgt_min','median'), mae=('mae','median'))
print("\nby volume shock (>=2.5x vs <2.5x):"); print(g.round(3))
