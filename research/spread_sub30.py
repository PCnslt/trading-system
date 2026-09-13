#!/usr/bin/env python3
"""Bull-put spread on sub-$30 liquid names — does the SPY edge transfer to names
a $2.3k account can actually collateralize?

IV = realized 30d vol (CONSERVATIVE: omits the VRP, so real premiums are higher).
Delta 30/15, ~30 DTE, bid/ask cost 0.05/leg, fee 0.65/leg. Defined risk capped.
"""
import math
import numpy as np
import pandas as pd
import yfinance as yf

SYMBOLS = ['F', 'T', 'INTC', 'PFE', 'WBA', 'KHC']
COST = 0.05          # per-leg bid/ask
DTE = 21
R = 0.02

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
            if -d>target: hi=m
            else: lo=m
        else:
            if d>target: lo=m
            else: hi=m
    return 0.5*(lo+hi)

def col(df,n): return df[n].iloc[:,0] if isinstance(df.columns,pd.MultiIndex) else df[n]

print(f"{'sym':>6} {'price':>7} {'vol':>6} {'n':>4} {'win%':>6} {'PF':>6} {'ret/risk':>9} {'avgK':>6} {'width':>6}")
print('-'*64)
for sym in SYMBOLS:
    try:
        px = col(yf.download(sym, start='2016-01-01', auto_adjust=False, progress=False), 'Close')
    except Exception as e:
        print(f'{sym:>6} download failed {str(e)[:40]}'); continue
    px = px[~px.index.duplicated(keep='last')].dropna()
    if len(px) < 500:
        print(f'{sym:>6} insufficient data ({len(px)})'); continue
    ret = np.log(px/px.shift(1))
    vol = (ret.rolling(21).std()*math.sqrt(252)).clip(0.15, 1.5)
    trades=[]
    for i in range(60, len(px)-DTE, DTE):
        S = px.iloc[i]; sig = vol.iloc[i]
        if not (S>0 and sig>0 and S < 30): continue
        tau = DTE/252.0
        Ks = ksd(S,tau,sig,R,0.30,'put'); Kl = ksd(S,tau,sig,R,0.15,'put')
        credit = bs(S,Ks,tau,sig,R,'put')-bs(S,Kl,tau,sig,R,'put') - 2*COST
        width = Ks-Kl; risk = width-credit
        if risk <= 0: continue
        Se = px.iloc[i+DTE]
        if Se>=Ks: pnl=credit
        elif Se<=Kl: pnl=-risk
        else: pnl=-(Ks-Se)+credit
        trades.append((pnl/risk, Ks, width))
    if not trades:
        print(f'{sym:>6} no trades'); continue
    t=np.array([x[0] for x in trades])
    wins=t[t>0].sum(); losses=abs(t[t<=0].sum())
    pf=wins/losses if losses>0 else float('inf')
    wr=(t>0).mean()*100
    avgk=np.mean([x[1] for x in trades]); avgw=np.mean([x[2] for x in trades])
    last=px.iloc[-1]
    print(f"{sym:>6} {last:>7.2f} {vol.iloc[-1]*100:>5.0f}% {len(t):>4} {wr:>6.0f}% {pf:>6.2f} {t.mean()*100:>+8.2f}% {avgk:>6.2f} {avgw:>6.2f}")
