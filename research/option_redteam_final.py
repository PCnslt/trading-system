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
        mid=(lo+hi)/2; d=bs_delta(S,mid,T,r,iv,cp)
        if d>delta: lo=mid if cp==1 else lo; hi=hi if cp==1 else mid
        else: hi=mid if cp==1 else hi; lo=lo if cp==1 else mid
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
            li=cum[cum*sgn>=confirm]
            if len(li)==0: continue
            t0=li.index[0]; ep=intra.loc[t0,'close']
            paths.append(dict(ep=ep, sgn=sgn, path=intra[intra.index>=t0]['close']))
    return paths

def sim(paths, struct, iv=0.6, sf=0.03, stop=0.005, tgt=0.02):
    r=0.0; rows=[]
    for p in paths:
        S0=p['ep']; sgn=p['sgn']
        if struct['type']=='call':
            K=find_K(S0,struct['T'],r,iv,struct['d']); entry=bs(S0,K,struct['T'],r,iv)*(1+sf); prem=bs(S0,K,struct['T'],r,iv)
            def val(S,t): return bs(S,K,struct['T']-t/(252*390),r,iv)
        elif struct['type']=='spread':
            K1=find_K(S0,struct['T'],r,iv,struct['d1']); K2=find_K(S0,struct['T'],r,iv,struct['d2'])
            c1=bs(S0,K1,struct['T'],r,iv); c2=bs(S0,K2,struct['T'],r,iv)
            prem=c1-c2; entry=prem*(1+sf*2)  # pay spread on both legs (conservative)
            def val(S,t): return bs(S,K1,struct['T']-t/(252*390),r,iv)-bs(S,K2,struct['T']-t/(252*390),r,iv)
        S=S0; pnl=0; hold=0; ex=False
        for t,px in p['path'].items():
            S=px; hold+=1; ret=(S/S0-1)*sgn
            if ret>=tgt: pnl=val(S,hold)*(1-sf)-entry; ex=True; break
            if ret<=-stop: pnl=val(S,hold)*(1-sf)-entry; ex=True; break
        if not ex: pnl=val(S,hold)*(1-sf)-entry
        rows.append(dict(pnl=pnl, prem=prem, win=int(pnl>0)))
    return pd.DataFrame(rows)

def rep(T,label):
    if len(T)==0: print(f"{label}: none"); return
    exp=T.pnl.mean()/T.prem.mean()*100; wr=T.win.mean()*100
    pf=T[T.pnl>0].pnl.sum()/abs(T[T.pnl<0].pnl.sum()) if (T.pnl<0).any() else 99
    print(f"{label}: exp={exp:+.1f}% win={wr:.0f}% PF={pf:.2f}")

paths=collect_paths(0.005)
print(f"paths={len(paths)}")

print("\n=== DEEP ITM CALLS (IV 60%, spread 3%) ===")
for d in [0.8,0.9,0.95]:
    for dte in [1,7,21]:
        rep(sim(paths,{'type':'call','d':d,'T':dte/252}), f"delta {d} DTE {dte}")

print("\n=== DEBIT SPREADS (buy d0.7, sell d0.3/d0.4/d0.5) ===")
for d2 in [0.3,0.5]:
    for dte in [1,7]:
        rep(sim(paths,{'type':'spread','d1':0.7,'d2':d2,'T':dte/252}), f"0.7/{-d2} DTE {dte}")

print("\n=== BREAK-EVEN SPREAD (0.7d call, DTE 7) — binary search ===")
lo,hi=0.0,0.10
for _ in range(12):
    mid=(lo+hi)/2; T=sim(paths,{'type':'call','d':0.7,'T':7/252},0.6,mid)
    e=T.pnl.mean()/T.prem.mean()
    if e>0: lo=mid
    else: hi=mid
print(f"break-even spread ~ {(lo+hi)/2*100:.2f}% of mid (expectancy crosses zero)")

print("\n=== COMPONENT BREAKDOWN (0.7d call DTE 7, spread 3%) ===")
# delta contribution vs spread cost
T=sim(paths,{'type':'call','d':0.7,'T':7/252},0.6,0.0)  # zero spread = pure delta+theta
T2=sim(paths,{'type':'call','d':0.7,'T':7/252},0.6,0.03)
print(f"no-spread expectancy: {T.pnl.mean()/T.prem.mean()*100:+.1f}%")
print(f"with 3% spread:       {T2.pnl.mean()/T2.prem.mean()*100:+.1f}%")
print(f"=> spread consumes ~{T.pnl.mean()/T.prem.mean()*100 - T2.pnl.mean()/T2.prem.mean()*100:.1f}% of premium")
