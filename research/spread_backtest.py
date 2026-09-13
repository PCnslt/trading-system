#!/usr/bin/env python3
"""Defined-risk spread backtest (the Level-3 route) — does selling premium as a
bull-put-spread / iron-condor beat the cash-secured-put wheel, at small capital?

Honest methodology (mirrors bot/wheel_backtest.py):
- SPY daily via yfinance; VIX (30d implied vol) as the option IV input, so the
  pricing includes the volatility risk premium (selling at IV > realized RV).
- Monthly re-entry (~21 trading days), 30-day-tenor conventions.
- Black-Scholes for option prices; strikes by delta (short 0.30, wing 0.15).
- Defined risk: bull-put-spread = short 0.30d put + long 0.15d put.
  Iron condor = that + short 0.30d call + long 0.15d call.
- No early management; settle at expiry. Fee $0.65/contract/leg.
- Reports in % of capital so it scales. NOT a live recommendation.
"""
import math
import numpy as np
import pandas as pd
import yfinance as yf
import boto3, json, io

# ---- Black-Scholes ----
def ncdf(x): return 0.5*(1.0+math.erf(x/math.sqrt(2)))
def _d1(S,K,t,sig,r): return (math.log(S/K)+(r+0.5*sig*sig)*t)/(sig*math.sqrt(t))
def bs(S,K,t,sig,r,kind):
    if t<=0: return max(K-S,0.0) if kind=='put' else max(S-K,0.0)
    d1=_d1(S,K,t,sig,r); d2=d1-sig*math.sqrt(t)
    if kind=='put': return K*math.exp(-r*t)*ncdf(-d2)-S*ncdf(-d1)
    return S*ncdf(d1)-K*math.exp(-r*t)*ncdf(d2)
def bs_delta(S,K,t,sig,r,kind):
    if t<=0: return (-1.0 if (kind=='put' and S<K) else (1.0 if kind=='call' and S>=K else 0.0))
    d1=_d1(S,K,t,sig,r)
    return ncdf(d1)-1.0 if kind=='put' else ncdf(d1)
def strike_for_delta(S,t,sig,r,target,kind):
    lo,hi=S*0.05,S*4.0
    for _ in range(80):
        mid=0.5*(lo+hi); d=bs_delta(S,mid,t,sig,r,kind)
        if kind=='put':
            if -d>target: hi=mid
            else: lo=mid
        else:
            if d>target: lo=mid
            else: hi=mid
    return 0.5*(lo+hi)

def load():
    def col(df,n): return df[n].iloc[:,0] if isinstance(df.columns,pd.MultiIndex) else df[n]
    spy = col(yf.download('SPY',start='2005-01-01',auto_adjust=False,progress=False),'Close')
    spy = spy[~spy.index.duplicated(keep='last')]
    # VIX from FRED (full history)
    s3=boto3.client('s3',region_name='us-east-1')
    v=json.loads(s3.get_object(Bucket='trading-datalake-920641308584',Key='macro/VIXCLS.json')['Body'].read())
    obs=v.get('observations',v if isinstance(v,list) else [])
    vix=pd.Series({pd.to_datetime(o['date']):float(o['value']) for o in obs if o.get('value') not in ('.','',None)}).sort_index()
    vix=vix[~vix.index.duplicated(keep='last')]
    return spy, vix

def run(spy, vix, mode, dte=21, fee=0.65):
    R=0.02
    idx=spy.index.intersection(vix.index).sort_values()
    S_=spy.reindex(idx); V_=vix.reindex(idx).ffill()
    trades=[]
    for i in range(0, len(idx)-dte, dte):
        t0=i; t1=i+dte
        S=S_.iloc[t0]; sig=V_.iloc[t0]/100.0; tau=dte/252.0
        if not (S>0 and sig>0): continue
        if mode=='bps':
            Ks=strike_for_delta(S,tau,sig,R,0.30,'put')
            Kl=strike_for_delta(S,tau,sig,R,0.15,'put')
            credit=bs(S,Ks,tau,sig,R,'put')-bs(S,Kl,tau,sig,R,'put')
            width=Ks-Kl; risk=width-credit
            Se=S_.iloc[t1]
            if Se>=Ks: pnl=credit
            elif Se<=Kl: pnl=-risk
            else: pnl=-(Ks-Se)+credit
        elif mode=='ic':
            Kps=strike_for_delta(S,tau,sig,R,0.30,'put'); Kpl=strike_for_delta(S,tau,sig,R,0.15,'put')
            Kcs=strike_for_delta(S,tau,sig,R,0.30,'call'); Kcl=strike_for_delta(S,tau,sig,R,0.15,'call')
            credit=(bs(S,Kps,tau,sig,R,'put')-bs(S,Kpl,tau,sig,R,'put')
                    +bs(S,Kcs,tau,sig,R,'call')-bs(S,Kcl,tau,sig,R,'call'))
            width=Kcs-Kps; risk=width-credit
            Se=S_.iloc[t1]
            pnl=credit
            if Se<Kps: pnl -= (Kps-Se)
            if Se>Kcs: pnl -= (Se-Kcs)
            pnl=max(pnl, -risk)   # defined risk: loss capped at the wings
        trades.append({'t0':idx[t0],'S':S,'credit':credit,'risk':risk,'pnl':pnl,
                       'width':width,'Se':Se,'prem_pct':credit/width*100 if width>0 else 0})
    tr=pd.DataFrame(trades)
    return tr

def report(tr, label):
    if tr.empty: print(label,'no trades'); return
    pnl=tr['pnl'].values
    wins=pnl[pnl>0].sum(); losses=abs(pnl[pnl<=0].sum())
    pf=wins/losses if losses>0 else float('inf')
    wr=(pnl>0).mean()*100
    # per-trade return on risk (defined-risk capital)
    ret=pnl/tr['risk'].values
    # annualized (one trade per ~21 trading days = ~12/yr)
    cagr=(1+ret.mean())**12-1
    print(f"{label:24s} n={len(tr):>4}  win%={wr:4.0f}%  PF={pf:5.2f}  "
          f"avg credit={tr['credit'].mean():6.2f}  avg width={tr['width'].mean():6.2f}  "
          f"mean ret/risk={ret.mean()*100:+.2f}%  CAGR~{cagr*100:+.1f}%/yr")
    # regime split
    for lbl,mask in [('pre-2015',tr['t0']<'2015-01-01'),('2015-2020',(tr['t0']>='2015-01-01')&(tr['t0']<'2020-01-01')),('2020+',tr['t0']>='2020-01-01')]:
        s=tr[mask]
        if len(s)==0: continue
        r=s['pnl']/s['risk']
        print(f"    {lbl:12s}: n={len(s):>3} win%={(s['pnl']>0).mean()*100:4.0f}% PF={s['pnl'][s['pnl']>0].sum()/abs(s['pnl'][s['pnl']<=0].sum()) if (s['pnl']<=0).any() else float('inf'):5.2f} ret/risk={r.mean()*100:+.2f}%")

if __name__=='__main__':
    spy,vix=load()
    print(f"SPY {spy.index.min().date()}..{spy.index.max().date()} | VIX {vix.index.min().date()}..{vix.index.max().date()}")
    print("Defined-risk spread on SPY, monthly re-entry, IV = VIX (includes VRP):\n")
    report(run(spy,vix,'bps'), "Bull-put spread (30/15d)")
    report(run(spy,vix,'ic'),  "Iron condor (30/15d)")
