import boto3, io, pandas as pd, numpy as np
from math import erf, sqrt
def ncdf(x): return 0.5*(1+erf(x/sqrt(2)))

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX','NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def bs(S,K,T,r,iv,cp=1):
    if T<=0 or iv<=0: return max(0,(S-K)*cp)
    d1=(np.log(S/K)+(r+0.5*iv*iv)*T)/(iv*np.sqrt(T)); d2=d1-iv*np.sqrt(T)
    return cp*(S*ncdf(cp*d1)-K*np.exp(-r*T)*ncdf(cp*d2))

def bs_delta(S,K,T,r,iv,cp=1):
    if T<=0 or iv<=0: return 1.0 if cp*S>=cp*K else 0.0
    d1=(np.log(S/K)+(r+0.5*iv*iv)*T)/(iv*np.sqrt(T))
    return cp*ncdf(cp*d1)

def find_K(S,T,r,iv,delta,cp=1):
    lo,hi=S*0.3,S*3.0
    for _ in range(80):
        mid=(lo+hi)/2
        d=bs_delta(S,mid,T,r,iv,cp)
        if d>delta:
            if cp==1: lo=mid
            else: hi=mid
        else:
            if cp==1: hi=mid
            else: lo=mid
    return (lo+hi)/2

def load(sym):
    r=s3.list_objects_v2(Bucket=BUCKET,Prefix=f'ibkr/equities/1min/{sym}/')
    fr=[pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET,Key=o['Key'])['Body'].read())) for o in r.get('Contents',[])]
    if not fr: return None
    df=pd.concat(fr).sort_values('ts'); df['ts']=pd.to_datetime(df['ts'],unit='s')
    return df.set_index('ts').sort_index()

def collect_paths(confirm=0.005):
    paths=[]
    for sym in SYMS:
        df=load(sym)
        if df is None or len(df)<3000: continue
        o=df['open'].resample('1D').first(); c=df['close'].resample('1D').last(); v=df['volume'].resample('1D').sum()
        d=pd.DataFrame({'open':o,'close':c,'vol':v}).dropna()
        d['gap']=d['open']/d['close'].shift(1)-1; d['avol']=d['vol']/d['vol'].rolling(20).mean()
        ev=d[(d['gap'].abs()>=0.02)&(d['avol']>=1.5)]
        for day,r in ev.iterrows():
            intra=df[df.index.date==day.date()]
            if len(intra)<30: continue
            op=r['open']; sgn=np.sign(r['gap'])
            cum=intra['close']/op-1
            long_ix=cum[cum*sgn>=confirm]
            if len(long_ix)==0: continue
            t0=long_ix.index[0]; ep=intra.loc[t0,'close']
            sub=intra[intra.index>=t0]['close']
            paths.append(dict(sym=sym, ep=ep, sgn=sgn, path=sub, day=day, gap=abs(r['gap']), avol=r['avol']))
    return paths

def sim_option(paths, delta, DTE, iv, spread_frac=0.03, stop=0.005, tgt=0.02, cp=1):
    r=0.0; T=DTE/252.0; rows=[]
    for p in paths:
        S0=p['ep']; sgn=p['sgn']
        K=find_K(S0,T,r,iv,delta,cp)
        prem=bs(S0,K,T,r,iv,cp)
        entry=prem*(1+spread_frac)  # ask
        sub=p['path']; S=S0
        exited=False; pnl=0; hold=0
        for t,px in sub.items():
            S=px; hold+=1
            ret=(S/S0-1)*sgn  # in gap direction
            if ret>=tgt: pnl=bs(S,K,T-hold/(252*390),r,iv,cp)*(1-spread_frac)-entry; exited=True; break
            if ret<=-stop: pnl=bs(S,K,T-hold/(252*390),r,iv,cp)*(1-spread_frac)-entry; exited=True; break
        if not exited: pnl=bs(S,K,T-hold/(252*390),r,iv,cp)*(1-spread_frac)-entry
        rows.append(dict(pnl=pnl, prem=prem, win=int(pnl>0)))
    return pd.DataFrame(rows)

paths=collect_paths(0.005)
print(f"paths: {len(paths)}")

print("\n=== LONG CALL — expectancy % of premium, win%, PF (IV=60%, spread=3%) ===")
for delta in [0.3,0.5,0.7,0.9]:
    row=[]
    for dte in [1,7,21,45]:
        T=sim_option(paths,delta,dte,0.60)
        if len(T)==0: row.append("  -  "); continue
        exp=T.pnl.mean()/T.prem.mean()*100
        wr=T.win.mean()*100
        pf=T[T.pnl>0].pnl.sum()/abs(T[T.pnl<0].pnl.sum()) if (T.pnl<0).any() else 99
        row.append(f"{exp:+.0f}%/{wr:.0f}%/{pf:.1f}")
    print(f"delta {delta}: "+" | ".join(row)+"   (DTE 1/7/21/45)")

print("\n=== IV SENSITIVITY (delta 0.7, DTE 7) ===")
for iv in [0.4,0.6,0.8]:
    T=sim_option(paths,0.7,7,iv)
    exp=T.pnl.mean()/T.prem.mean()*100; wr=T.win.mean()*100
    print(f"IV={iv*100:.0f}%: expectancy {exp:+.0f}% win {wr:.0f}%")

print("\n=== SPREAD SENSITIVITY (delta 0.7, DTE 7, IV 60%) ===")
for sf in [0.01,0.03,0.06]:
    T=sim_option(paths,0.7,7,0.60,sf)
    exp=T.pnl.mean()/T.prem.mean()*100
    print(f"spread {sf*100:.0f}%: expectancy {exp:+.0f}%")
