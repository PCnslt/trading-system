#!/usr/bin/env python3
"""Adversarial stress on the two found edges.

1. Bull-put spread: add a per-leg bid/ask cost (the #1 unmodeled cost) and show
   whether PF / win% / ret-on-risk survive a realistic fill.
2. Forward VRP: correct the timing — is VIX_t (implied) actually ABOVE the
   realized vol over the NEXT 21 trading days (forward), not the trailing window.
"""
import math
import numpy as np
import pandas as pd
import yfinance as yf
import boto3, json

def ncdf(x): return 0.5*(1.0+math.erf(x/math.sqrt(2)))
def _d1(S,K,t,s,r): return (math.log(S/K)+(r+0.5*s*s)*t)/(s*math.sqrt(t))
def bs(S,K,t,s,r,kind):
    if t<=0: return max(K-S,0.0) if kind=='put' else max(S-K,0.0)
    d1=_d1(S,K,t,s,r); d2=d1-s*math.sqrt(t)
    return K*math.exp(-r*t)*ncdf(-d2)-S*ncdf(-d1) if kind=='put' else S*ncdf(d1)-K*math.exp(-r*t)*ncdf(d2)
def bsd(S,K,t,s,r,kind):
    if t<=0: return -1.0 if(kind=='put' and S<K) else(1.0 if kind=='call' and S>=K else 0.0)
    return ncdf(_d1(S,K,t,s,r))-1.0 if kind=='put' else ncdf(_d1(S,K,t,s,r))
def ksd(S,t,s,r,target,kind):
    lo,hi=S*0.05,S*4.0
    for _ in range(80):
        m=0.5*(lo+hi); d=bsd(S,m,t,s,r,kind)
        if kind=='put':
            hi=m if -d>target else hi; lo=m if -d<=target else lo
        else:
            lo=m if d>target else lo; hi=m if d<=target else hi
    return 0.5*(lo+hi)

def col(df,n): return df[n].iloc[:,0] if isinstance(df.columns,pd.MultiIndex) else df[n]
spy=col(yf.download('SPY',start='2005-01-01',auto_adjust=False,progress=False),'Close')
spy=spy[~spy.index.duplicated(keep='last')]
s3=boto3.client('s3',region_name='us-east-1')
v=json.loads(s3.get_object(Bucket='trading-datalake-920641308584',Key='macro/VIXCLS.json')['Body'].read())
obs=v.get('observations',v if isinstance(v,list) else [])
vix=pd.Series({pd.to_datetime(o['date']):float(o['value']) for o in obs if o.get('value') not in ('.','',None)}).sort_index()
vix=vix[~vix.index.duplicated(keep='last')]

R=0.02; DTE=21
idx=spy.index.intersection(vix.index).sort_values()
S_=spy.reindex(idx); V_=vix.reindex(idx).ffill()

# ---- 1. bull-put spread with per-leg cost grid ----
print("="*74)
print("BULL-PUT SPREAD (30/15 delta, SPY, monthly) — bid/ask cost stress")
print("="*74)
print(f"{'cost/leg':>8} {'win%':>6} {'PF':>6} {'ret/risk/trade':>15} {'survives?':>10}")
for cost in [0.0, 0.03, 0.05, 0.10, 0.15, 0.20]:
    trades=[]
    for i in range(0, len(idx)-DTE, DTE):
        t0=i; t1=i+DTE
        S=S_.iloc[t0]; sig=V_.iloc[t0]/100.0; tau=DTE/252.0
        if not(S>0 and sig>0): continue
        Ks=ksd(S,tau,sig,R,0.30,'put'); Kl=ksd(S,tau,sig,R,0.15,'put')
        credit=bs(S,Ks,tau,sig,R,'put')-bs(S,Kl,tau,sig,R,'put')
        credit -= 2*cost          # 2 legs, each pays half-spread (cross the bid/ask once)
        width=Ks-Kl; risk=width-credit
        Se=S_.iloc[t1]
        if Se>=Ks: pnl=credit
        elif Se<=Kl: pnl=-risk
        else: pnl=-(Ks-Se)+credit
        trades.append(pnl/risk if risk>0 else 0)
    t=np.array(trades)
    wins=t[t>0].sum(); losses=abs(t[t<=0].sum())
    pf=wins/losses if losses>0 else float('inf')
    wr=(t>0).mean()*100
    survive = 'YES' if pf>=1.2 and t.mean()>0 else ('marginal' if pf>=1.0 else 'NO')
    print(f"{cost:>8.2f} {wr:>6.0f}% {pf:>6.2f} {t.mean()*100:>+14.2f}% {survive:>10}")

# ---- 2. forward VRP (VIX_t vs realized vol over NEXT 21 trading days) ----
print("\n"+"="*74)
print("FORWARD VRP — VIX_t vs realized vol over the NEXT 21 trading days")
print("="*74)
ret=np.log(S_/S_.shift(1))
# clean forward realized vol: std of returns t+1..t+21, annualized
fwd=pd.Series(index=idx, dtype=float)
r=ret.to_numpy()
for t in range(0, len(r)-21):
    fwd.iloc[t]=np.nanstd(r[t+1:t+22])*np.sqrt(252)*100
d=pd.DataFrame({'vix':V_,'fwd_rvol':fwd}).dropna()
d['vrp']=d['vix']-d['fwd_rvol']
print(f"n={len(d)} | VIX mean {d['vix'].mean():.2f} | fwd-21d realized mean {d['fwd_rvol'].mean():.2f}")
print(f"FORWARD VRP mean {d['vrp'].mean():+.2f} vol pts | median {d['vrp'].median():+.2f} | %positive {(d['vrp']>0).mean()*100:.1f}%")
for lbl,m in [('pre-2010',d.index<'2010'),('2010-20',(d.index>='2010')&(d.index<'2020')),('2020+',d.index>='2020')]:
    s=d[m]; print(f"  {lbl:10s}: VRP {s['vrp'].mean():+.2f} vol pts | %pos {(s['vrp']>0).mean()*100:.0f}% | n={len(s)}")
