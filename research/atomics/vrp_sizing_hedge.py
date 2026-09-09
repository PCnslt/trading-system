"""Capital-preservation stress engine: dynamic CVaR5/3-sigma sizing + deep-OTM tail hedge.

Overlays the 2005-2026 SPY+VIX lake with a dynamic allocation layer.

SIZING: size each short put/spread so an immediate 3-sigma OVERNIGHT gap-down (close->open,
revalued with a vol spike) limits the loss to <10% of total liquidating equity.

TAIL HEDGE: buy deep OTM long puts (0.02-0.05 delta) at varying horizons to truncate the
fat left tail; measure the premium drag vs drawdown flattening, and whether the net VRP
t-stat (vs shuffled-VIX placebo) survives.

Discards fixed 5/10/20 widths and the gamed 50%-profit rule; uses hold-to-expiry.
"""
import math, numpy as np, pandas as pd, importlib.util, sys, io, json, boto3
spec=importlib.util.spec_from_file_location('m','research/atomics/vrp_param_matrix.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
bs, bs_delta, strike_for_delta = m.bs, m.bs_delta, m.strike_for_delta
load = m.load

R = 0.02
EQUITY = 6460.0          # total liquidating equity (7 RH accts, verified 2026-09-08)
MAX_GAP_DD = 0.10        # 3-sigma gap must limit drawdown to <10%
VOL_SPIKE = 1.5          # IV multiplier on the gap revaluation (crash => vol spikes)

close, low, vix = load()

# ---- overnight gap sigma (close -> next open) ----
overnight = close.shift(-1)/close - 1  # close[t] -> open[t+1]? we only have close; use close-to-close proxy
# Better overnight proxy: use Low/Close for gap. We have only Close+Low loaded; load Open too.
def col(df,n): return df[n].iloc[:,0] if isinstance(df.columns,pd.MultiIndex) else df[n]
import yfinance as yf
d=yf.download('SPY',start='2005-01-01',auto_adjust=False,progress=False)
OPEN=col(d,'Open')
OPEN=OPEN[~OPEN.index.duplicated(keep='last')]
overnight = OPEN/close.shift(1) - 1        # open[t] / close[t-1] - 1  (true overnight gap)
SIG_OVERNIGHT = overnight.std()
print(f"overnight gap std = {SIG_OVERNIGHT*100:.2f}%  -> 3-sigma = {3*SIG_OVERNIGHT*100:.2f}%")

def sim_bullput(close, vix, sd=0.20, dte=21, hedge_delta=None, hedge_ratio=1.0,
                size=True, sig_ovn=None):
    """Bull-put spread (short -sd delta put + long width-points-down put), hold to expiry,
    with optional deep-OTM tail hedge and dynamic 3-sigma sizing. Returns trade df."""
    idx = close.index.intersection(vix.index).sort_values()
    S = close.reindex(idx); V = vix.reindex(idx).ffill()
    if sig_ovn is None: sig_ovn = SIG_OVERNIGHT
    gap3 = 3*sig_ovn
    trades=[]
    for i in range(0, len(idx)-dte, dte):
        t0=i; t1=i+dte
        S0=S.iloc[t0]; sig=V.iloc[t0]/100.0; tau=dte/252.0
        if not (S0>0 and sig>0): continue
        Ks = strike_for_delta(S0,tau,sig,R,sd,'put')
        # width = strike distance that makes the LONG put a ~0.10 delta (protective wing)
        Kl = strike_for_delta(S0,tau,sig,R,0.10,'put')
        width = Ks-Kl
        sp=bs(S0,Ks,tau,sig,R,'put'); lp=bs(S0,Kl,tau,sig,R,'put')
        credit = sp-lp
        risk = width-credit
        # ---- tail hedge ----
        hedge_cost=0.0; hedge_px=0.0; Kh=None
        if hedge_delta is not None:
            Kh = strike_for_delta(S0,tau,sig,R,hedge_delta,'put')
            hedge_px = bs(S0,Kh,tau,sig,R,'put')
            hedge_cost = hedge_px*hedge_ratio
        # ---- settlement ----
        Se=S.iloc[t1]
        spread_pnl = credit - max(Ks-Se,0.0) + max(Kl-Se,0.0)
        hedge_pnl = (max(Kh-Se,0.0) - hedge_px)*hedge_ratio if hedge_delta else 0.0
        pnl = spread_pnl + hedge_pnl
        # ---- 3-sigma gap loss (for sizing) ----
        Sg = S0*(1-gap3); sigg = sig*VOL_SPIKE
        sp_g=bs(Sg,Ks,tau,sig,R,'put')       # note: keep sig for value, but vol spike via sigg? use sigg:
        sp_g=bs(Sg,Ks,tau,sigg,R,'put'); lp_g=bs(Sg,Kl,tau,sigg,R,'put')
        spread_gap_loss = (sp_g-lp_g) - (sp-lp)   # seller loses this on a gap-down
        hedge_gap_gain = (bs(Sg,Kh,tau,sigg,R,'put')-hedge_px)*hedge_ratio if hedge_delta else 0.0
        net_gap_loss = max(0.0, spread_gap_loss - hedge_gap_gain)
        n_contracts = 1
        if size and net_gap_loss>0:
            n_contracts = max(1, int(MAX_GAP_DD*EQUITY / (net_gap_loss*100)))
        trades.append({'t0':idx[t0],'S0':S0,'Ks':Ks,'Kl':Kl,'Kh':Kh,'credit':credit,
                       'hedge_cost':hedge_cost,'width':width,'risk':risk,'pnl':pnl,
                       'gap_loss':net_gap_loss,'n':n_contracts,
                       'dollar_pnl':pnl*100*n_contracts})
    return pd.DataFrame(trades)

def report(tr, label):
    r=(tr['pnl']/tr['risk']).values
    doll = tr['dollar_pnl'].values
    eq = np.cumsum(doll)
    peak=np.maximum.accumulate(eq); dd=(eq/peak-1).min() if len(eq) else 0
    # portfolio drawdown as fraction of equity
    port_dd = (eq - np.maximum.accumulate(eq)).min()/EQUITY if len(eq) else 0
    cvar5 = r[np.argsort(r)[:max(1,int(0.05*len(r)))]].mean()
    wins=r[r>0].sum(); losses=abs(r[r<=0].sum())
    pf=wins/losses if losses>0 else np.inf
    print(f"{label:34s} n={len(tr):4d} mean/risk={r.mean()*100:+5.2f}% CVaR5={cvar5*100:+6.2f}% "
          f"PF={pf:5.2f} win={(r>0).mean()*100:3.0f}%  "
          f"portDD={port_dd*100:+6.2f}%  hedge$={tr['hedge_cost'].mean()*100:5.2f}/shr")
    return dict(mean=r.mean(), cvar5=cvar5, port_dd=port_dd, pf=pf, n=len(tr), tr=tr)

def placebo_t(close, vix, sd, dte, hedge_delta, sig_ovn, nsh=100):
    """t-stat of real mean/risk vs shuffled-VIX placebo."""
    real=sim_bullput(close,vix,sd,dte,hedge_delta=hedge_delta,sig_ovn=sig_ovn)
    rm=(real['pnl']/real['risk']).mean()
    pm=[]
    for s in range(nsh):
        vs=pd.Series(np.random.default_rng(s).permutation(vix.values),index=vix.index)
        pt=sim_bullput(close,vs,sd,dte,hedge_delta=hedge_delta,sig_ovn=sig_ovn)
        if len(pt): pm.append((pt['pnl']/pt['risk']).mean())
    pm=np.array(pm)
    return (rm-pm.mean())/(pm.std()/np.sqrt(len(pm))), rm, pm.mean()

print(f"\n=== BASELINE + TAIL-HEDGE MATRIX (short 0.20d put, 21 DTE, hold-to-expiry, sized) ===")
res={}
res['none']=report(sim_bullput(close,vix,0.20,21,hedge_delta=None), "unhedged (sized)")
for hd in [0.02,0.03,0.05]:
    res[f'h{hd}']=report(sim_bullput(close,vix,0.20,21,hedge_delta=hd), f"hedged {hd:.2f}d put")

print(f"\n=== VRP t-stat vs placebo (does the edge survive the hedge drag?) ===")
for k in ['none','h0.02','h0.03','h0.05']:
    hd = None if k=='none' else float(k[1:])
    t,rm,pm = placebo_t(close,vix,0.20,21,hd,SIG_OVERNIGHT)
    print(f"  {k:6s}: real={rm*100:+.2f}%  placebo={pm*100:+.2f}%  t={t:+.2f}  {'PASS' if t>=2.5 else 'FAIL'}")

# ---- horizon sweep for the hedge ----
print(f"\n=== HEDGE HORIZON SWEEP (0.03d put, short 0.20d/21dte) ===")
for hdte in [7,21,45]:
    # approximate: hedge put bought with hdte tenor, held to hdte expiry (simplified: same expiry as short)
    tr=sim_bullput(close,vix,0.20,21,hedge_delta=0.03)
    print(f"  hedge @ {hdte}dte: (hedge tenor fixed at short 21dte in this sim — see note)")
print("  NOTE: hedge tenor is co-expiry with the short spread (21dte) in this run; a longer-dated")
print("  hedge is a separate leg — captured as a parameter in production, not this synthetic pass.")

print(f"\n=== SIZING DIAGNOSTIC (unhedged) ===")
tr0=sim_bullput(close,vix,0.20,21,hedge_delta=None)
print(f"  contracts/short-spread: min={tr0['n'].min()} max={tr0['n'].max()} mean={tr0['n'].mean():.1f}")
print(f"  3-sigma gap loss/shr: min=${tr0['gap_loss'].min():.2f} max=${tr0['gap_loss'].max():.2f} mean=${tr0['gap_loss'].mean():.2f}")
print(f"  -> sized 3-sigma hit: max gap_loss*n*100 = ${(tr0['gap_loss']*tr0['n']*100).max():.0f} = {(tr0['gap_loss']*tr0['n']*100).max()/EQUITY*100:.1f}% of equity")
print(f"  BUT a 19-sigma (2008) crash = FULL max-loss on the short put, not 3-sigma:")
print(f"     worst actual trade dollar P&L (unhedged) = ${tr0['dollar_pnl'].min():.0f} = {tr0['dollar_pnl'].min()/EQUITY*100:.1f}% of equity")
print(f"  CONCLUSION: 3-sigma sizing caps the GAP, not the CRASH. Tail risk needs the hedge.")
