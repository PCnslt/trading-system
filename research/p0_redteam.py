import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX','NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def load(sym):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=f'ibkr/equities/1min/{sym}/')
    frames=[pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=o['Key'])['Body'].read())) for o in r.get('Contents',[])]
    if not frames: return None
    df=pd.concat(frames).sort_values('ts'); df['ts']=pd.to_datetime(df['ts'],unit='s')
    return df.set_index('ts').sort_index()

def collect(thr=0.005):
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
            fh = cum[cum.abs()>=thr]
            if len(fh)==0: continue
            fhd = np.sign(fh.iloc[0])*sgn  # +1 with gap, -1 against
            t_first = (fh.index[0]-intra.index[0]).total_seconds()/60
            hit_up=cum[cum>=0.02]; hit_dn=cum[cum<=-0.02]
            fu=(hit_up.index[0]-intra.index[0]).total_seconds()/60 if len(hit_up) else np.nan
            fd=(hit_dn.index[0]-intra.index[0]).total_seconds()/60 if len(hit_dn) else np.nan
            if sgn>0: win=(not np.isnan(fu)) and (np.isnan(fd) or fu<fd)
            else: win=(not np.isnan(fd)) and (np.isnan(fu) or fd<fu)
            adv=(cum*sgn).min()
            rows.append(dict(sym=sym, sgn=sgn, win=int(win), fhd=fhd, adv=adv,
                             gap=abs(r['gap'])*100, avol=r['avol'], hod=day.hour,
                             t_first=t_first, d=day))
    A=pd.DataFrame(rows); A['dt']=pd.to_datetime(A['d']); A=A.sort_values('dt').reset_index(drop=True)
    return A

A=collect(0.005)
print(f"events: {len(A)}")

# 1. WALK-FORWARD (3 folds)
print("\n=== WALK-FORWARD (3 date folds) ===")
n=len(A); c1,c2=int(n*0.5),int(n*0.75)
for i,f in enumerate([A.iloc[:c1], A.iloc[c1:c2], A.iloc[c2:]]):
    wg=f[f.fhd==1]; ag=f[f.fhd==-1]
    print(f"fold{i} N={len(f)}: with-gap win={wg.win.mean()*100:.1f}% (n={len(wg)}) | against win={ag.win.mean()*100:.1f}% (n={len(ag)})")

# 2. PLACEBOS
print("\n=== PLACEBOS ===")
sh=A.copy(); sh['win']=sh['win'].sample(frac=1,random_state=0).values
print(f"shuffle-win: with-gap={sh[sh.fhd==1].win.mean()*100:.1f}% (expect ~50)")
sh2=A.copy(); sh2['fhd']=sh2['fhd'].sample(frac=1,random_state=1).values
print(f"shuffle-fhd: with-gap win={sh2[sh2.fhd==1].win.mean()*100:.1f}% (expect ~base)")

# 3. THRESHOLD GRID
print("\n=== THRESHOLD GRID (win% with-gap vs against) ===")
for thr in [0.0025,0.005,0.0075,0.01]:
    B=collect(thr)
    wg=B[B.fhd==1]; ag=B[B.fhd==-1]
    print(f"thr={thr*100:.2f}%: with-gap {wg.win.mean()*100:.1f}% (n={len(wg)}) | against {ag.win.mean()*100:.1f}% (n={len(ag)}) | events={len(B)}")

# 4. SURVIVORSHIP per symbol
print("\n=== PER-SYMBOL (with-gap win%, sorted by n) ===")
g=A[A.fhd==1].groupby('sym').agg(n=('win','size'), win=('win','mean'))
print(g.sort_values('n',ascending=False).to_string())

# 5. GAP + VOLUME BINS
print("\n=== GAP BINS (with-gap win%) ===")
A['gb']=pd.cut(A.gap,[2,3,4,5,99],labels=['2-3','3-4','4-5','5+'])
for b,grp in A.groupby('gb',observed=True):
    wg=grp[grp.fhd==1]
    print(f"gap {b}: with-gap win={wg.win.mean()*100:.1f}% (n={len(wg)})")
print("=== VOLUME BINS ===")
A['vb']=pd.cut(A.avol,[1.5,2,2.5,4,99],labels=['1.5-2','2-2.5','2.5-4','4+'])
for b,grp in A.groupby('vb',observed=True):
    wg=grp[grp.fhd==1]
    print(f"vol {b}: with-gap win={wg.win.mean()*100:.1f}% (n={len(wg)})")

# 6. INFO VELOCITY: confirmation speed vs win
print("\n=== CONFIRMATION SPEED (with-gap win% by time-to-0.5%) ===")
A['vb2']=pd.cut(A.t_first,[0,1,3,5,10,999],labels=['<1m','1-3m','3-5m','5-10m','10m+'])
for b,grp in A.groupby('vb2',observed=True):
    wg=grp[grp.fhd==1]
    print(f"t_first {b}: with-gap win={wg.win.mean()*100:.1f}% (n={len(wg)})")
