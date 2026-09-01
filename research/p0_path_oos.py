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
        op=r['open']; sgn=np.sign(r['gap']); cum=intra['close']/op-1
        fh=cum[cum.abs()>=0.005]
        fhd = np.sign(fh.iloc[0])*sgn if len(fh) else 0
        hit_up=cum[cum>=0.02]; hit_dn=cum[cum<=-0.02]
        fu=(hit_up.index[0]-intra.index[0]).total_seconds()/60 if len(hit_up) else np.nan
        fd=(hit_dn.index[0]-intra.index[0]).total_seconds()/60 if len(hit_dn) else np.nan
        if sgn>0: win=(not np.isnan(fu)) and (np.isnan(fd) or fu<fd)
        else: win=(not np.isnan(fd)) and (np.isnan(fu) or fd<fu)
        adv=(cum*sgn).min() if len(fh) else np.nan
        rows.append(dict(day=day, win=win, fhd=fhd, adv=adv))

E=pd.DataFrame(rows).sort_values('day')
cut = E.day.quantile(0.7)
TR, TE = E[E.day<=cut], E[E.day>cut]
print(f"total {len(E)}  |  train {len(TR)} (<= {cut.date()})  |  test {len(TE)}")
for name, S in [('TRAIN',TR),('TEST',TE)]:
    w = S[S.fhd==1]; a = S[S.fhd==-1]
    print(f"\n{name}:")
    print(f"  first 0.5% WITH gap:    n={len(w)}  P(win)={w.win.mean():.1%}")
    print(f"  first 0.5% AGAINST gap: n={len(a)}  P(win)={a.win.mean():.1%}")
    print(f"  spread (with - against): {w.win.mean()-a.win.mean():.1%}")
    # early exit signal OOS
    print(f"  P(win|adv<0.5%)={S[S.adv>-0.005].win.mean():.1%}  vs  P(win|adv>=0.5%)={S[S.adv<=-0.005].win.mean():.1%}")
