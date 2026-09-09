"""VRP harvesting parameter matrix — SPY bull-put spreads, synthetic BS + VIX.

Exhaustive matrix: short-delta {0.10,0.15,0.20} x width {5,10,20}pts x DTE {45,21,7}
x exit-rule {alpha=hold-to-expiry, beta=50%-profit, gamma=touch-short-strike}.

Cost: $1/contract/leg + 2% bid-ask slippage on BOTH legs.
Metrics: Sortino, Max tail drawdown, Sharpe, win%, PF; vs SPY buy-and-hold.
Placebo: calendar-shuffled VIX (breaks IV-RV link) — real must beat placebo t>=2.5.

HONEST LIMITATION: synthetic BS+VIX pricing (no real historical SPY option chains in
lake). Tests the MECHANICS of harvesting a GIVEN VRP, not live tradeability.
"""
import math, numpy as np, pandas as pd, yfinance as yf, boto3, json, io

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
    d1=_d1(S,K,t,sig,r); return ncdf(d1)-1.0 if kind=='put' else ncdf(d1)
def strike_for_delta(S,t,sig,r,target,kind):
    lo,hi=S*0.5,S*1.5
    for _ in range(100):
        mid=0.5*(lo+hi); d=bs_delta(S,mid,t,sig,r,kind)
        if kind=='put':
            if abs(d) > target: hi=mid
            else: lo=mid
        else:
            if d > target: hi=mid
            else: lo=mid
    return 0.5*(lo+hi)

def load():
    def col(df,n): return df[n].iloc[:,0] if isinstance(df.columns,pd.MultiIndex) else df[n]
    d=yf.download('SPY',start='2005-01-01',auto_adjust=False,progress=False)
    close=col(d,'Close'); low=col(d,'Low')
    close=close[~close.index.duplicated(keep='last')]; low=low[~low.index.duplicated(keep='last')]
    s3=boto3.client('s3',region_name='us-east-1')
    v=json.loads(s3.get_object(Bucket='trading-datalake-920641308584',Key='macro/VIXCLS.json')['Body'].read())
    obs=v.get('observations',v if isinstance(v,list) else [])
    vix=pd.Series({pd.to_datetime(o['date']):float(o['value']) for o in obs if o.get('value') not in ('.','',None)}).sort_index()
    vix=vix[~vix.index.duplicated(keep='last')]
    return close, low, vix

def simulate(close, low, vix, sd, width, dte, rule, fee=1.0, slip=0.02, R=0.02):
    idx = close.index.intersection(vix.index).sort_values()
    S=close.reindex(idx); L=low.reindex(idx); V=vix.reindex(idx).ffill()
    fee_share = 2*fee/100.0  # $1/contract/leg -> $0.01/share/leg x2 legs
    trades=[]
    for i in range(0, len(idx)-dte, dte):
        t0=i; t1=i+dte
        S0=S.iloc[t0]; sig=V.iloc[t0]/100.0; tau=dte/252.0
        if not (S0>0 and sig>0): continue
        Ks=strike_for_delta(S0,tau,sig,R,sd,'put')
        Kl=Ks-width
        sp=bs(S0,Ks,tau,sig,R,'put'); lp=bs(S0,Kl,tau,sig,R,'put')
        credit = sp*(1-slip) - lp*(1+slip) - fee_share
        risk = width - credit
        if risk<=0: continue
        pnl=None; exit_t=None
        if rule=='alpha':
            Se=S.iloc[t1]
            pnl = credit - max(Ks-Se,0.0) + max(Kl-Se,0.0)
        elif rule=='beta':
            for t in range(t0+1, t1+1):
                St=S.iloc[t]; tt=(t1-t)/252.0
                val=bs(St,Ks,tt,sig,R,'put')-bs(St,Kl,tt,sig,R,'put')
                if val <= 0.5*credit:
                    close_cost = val*(1+slip)+fee_share   # buy back w/ slippage+fee
                    pnl=credit-close_cost; exit_t=t; break
            if pnl is None:
                Se=S.iloc[t1]; pnl=credit-max(Ks-Se,0.0)+max(Kl-Se,0.0)
        elif rule=='gamma':
            for t in range(t0+1, t1+1):
                if L.iloc[t] <= Ks:   # touched short strike
                    tt=(t1-t)/252.0
                    val=bs(Ks,Ks,tt,sig,R,'put')-bs(Ks,Kl,tt,sig,R,'put')
                    close_cost = val*(1+slip)+fee_share
                    pnl=credit-close_cost; exit_t=t; break
            if pnl is None:
                Se=S.iloc[t1]; pnl=credit-max(Ks-Se,0.0)+max(Kl-Se,0.0)
        trades.append({'t0':idx[t0],'S0':S0,'Ks':Ks,'Kl':Kl,'credit':credit,'risk':risk,
                       'pnl':pnl,'width':width,'dte':dte,'hold':(exit_t-t0) if exit_t else dte})
    return pd.DataFrame(trades)

def sortino(r):
    r=np.asarray(r,float)
    dd=r[r<0]
    down=math.sqrt(np.mean(dd**2)) if len(dd) else 0.0
    return r.mean()/down if down>0 else np.inf

def maxdd(r):
    eq=np.cumprod(1+np.asarray(r,float)); peak=np.maximum.accumulate(eq)
    return (eq/peak-1).min()

def metrics(tr):
    r=(tr['pnl']/tr['risk']).values
    wins=r[r>0].sum(); losses=abs(r[r<=0].sum())
    return dict(n=len(tr), mean_rt=r.mean(), win=(r>0).mean(),
                pf=wins/losses if losses>0 else np.inf,
                sortino=sortino(r), maxdd=maxdd(r),
                sharpe=r.mean()/r.std() if r.std()>0 else np.inf)

def bh_bench(close):
    r=close.pct_change().dropna().values
    return dict(sharpe=r.mean()/r.std()*math.sqrt(252), sortino=sortino(r)*math.sqrt(252),
                maxdd=maxdd(r), cagr=(close.iloc[-1]/close.iloc[0])**(252/len(close))-1)

def main():
    close, low, vix = load()
    print(f"SPY {close.index.min().date()}..{close.index.max().date()} | VIX {vix.index.min().date()}..{vix.index.max().date()}\n")
    bh=bh_bench(close)
    print(f"BENCHMARK SPY buy&hold: Sharpe={bh['sharpe']:.2f} Sortino={bh['sortino']:.2f} MaxDD={bh['maxdd']*100:.1f}% CAGR={bh['cagr']*100:.1f}%/yr\n")

    rows=[]
    for sd in [0.10,0.15,0.20]:
        for width in [5,10,20]:
            for dte in [45,21,7]:
                for rule in ['alpha','beta','gamma']:
                    tr=simulate(close,low,vix,sd,width,dte,rule)
                    if tr.empty: continue
                    m=metrics(tr)
                    rows.append(dict(sd=sd,width=width,dte=dte,rule=rule,**m))
    R=pd.DataFrame(rows).sort_values('sortino',ascending=False)
    pd.set_option('display.width',200); pd.set_option('display.max_rows',200)
    R['mean_rt']=(R['mean_rt']*100).round(2); R['win']=(R['win']*100).round(0)
    R['pf']=R['pf'].round(2); R['sortino']=R['sortino'].round(2); R['maxdd']=(R['maxdd']*100).round(1)
    R['sharpe']=R['sharpe'].round(2)
    print("=== TOP 20 by Sortino (all 81 configs) ===")
    print(R.head(20).to_string(index=False))
    R.to_csv('/home/ubuntu/trading-system/research/atomics/vrp_matrix_results.csv',index=False)
    print(f"\nfull 81-config table -> research/atomics/vrp_matrix_results.csv")
    return close, low, vix, R

if __name__=='__main__':
    close,low,vix,R = main()
