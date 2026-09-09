"""VRP placebo + tail-risk analysis. Answers: is the VRP real (not curve-fit), and
what does the tail actually look like (Sortino is blind to it)?
"""
import numpy as np, pandas as pd, importlib.util, sys
spec=importlib.util.spec_from_file_location('m','research/atomics/vrp_param_matrix.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

close, low, vix = m.load()

def tail(tr):
    r=(tr['pnl']/tr['risk']).values
    worst=r.min()
    cvar=r[np.argsort(r)[:max(1,int(0.05*len(r)))]].mean()
    maxloss=(r < -0.5).mean()   # fraction losing >50% of risk
    return dict(n=len(r), worst=worst, cvar5=cvar, pct_half=(r<0).mean(), pct_ge50=maxloss)

print("=== TAIL RISK by config (mean return % + worst trade + CVaR5 + maxDD) ===")
for cfg in [(0.20,10,21,'alpha'),(0.20,10,21,'gamma'),(0.20,20,45,'gamma'),
            (0.15,10,21,'gamma'),(0.10,20,45,'beta'),(0.10,10,21,'alpha')]:
    sd,w,dte,rule=cfg
    tr=m.simulate(close,low,vix,sd,w,dte,rule)
    t=tail(tr); mm=m.metrics(tr)
    print(f"  {sd:.2f}Δ/{w}w/{dte}dte/{rule:5s}: mean={mm['mean_rt']*100:+5.2f}% "
          f"worst={t['worst']*100:+6.1f}% CVaR5={t['cvar5']*100:+6.1f}% "
          f"maxDD={mm['maxdd']*100:+6.1f}%  P(loss)={t['pct_half']*100:4.0f}%  P(>50% loss)={t['pct_ge50']*100:4.0f}%")

# ---- placebo: shuffle VIX (breaks IV-RV link), re-run hold-to-expiry ----
print("\n=== PLACEBO (calendar-shuffled VIX, 0.20Δ/10w/21d/alpha) ===")
cfg=(0.20,10,21,'alpha')
real=m.simulate(close,low,vix,*cfg)
real_mean=(real['pnl']/real['risk']).mean()
placebo_means=[]
for s in range(200):
    vs=pd.Series(np.random.default_rng(s).permutation(vix.values), index=vix.index)
    pt=m.simulate(close,low,vs,*cfg)
    if len(pt): placebo_means.append((pt['pnl']/pt['risk']).mean())
placebo_means=np.array(placebo_means)
tstat=(real_mean-placebo_means.mean())/(placebo_means.std()/np.sqrt(len(placebo_means)))
print(f"real mean/risk = {real_mean*100:+.2f}%   placebo mean = {placebo_means.mean()*100:+.2f}% "
      f"(std {placebo_means.std()*100:.2f}%)")
print(f"t-stat vs placebo = {tstat:+.2f}  (prompt gate: >=2.5)  -> "
      f"{'PASS (VRP real, not curve-fit)' if tstat>=2.5 else 'FAIL (curve-fit artifact)'}")

# ---- also placebo on the beta artifact config ----
print("\n=== PLACEBO on 'beta artifact' (0.10Δ/20w/45d/beta) ===")
cfg2=(0.10,20,45,'beta')
real2=m.simulate(close,low,vix,*cfg2)
real2_mean=(real2['pnl']/real2['risk']).mean()
pm2=[]
for s in range(200):
    vs=pd.Series(np.random.default_rng(s).permutation(vix.values), index=vix.index)
    pt=m.simulate(close,low,vs,*cfg2)
    if len(pt): pm2.append((pt['pnl']/pt['risk']).mean())
pm2=np.array(pm2)
t2=(real2_mean-pm2.mean())/(pm2.std()/np.sqrt(len(pm2)))
print(f"real mean={real2_mean*100:+.2f}%  placebo mean={pm2.mean()*100:+.2f}%  t={t2:+.2f}")
print(f"NOTE: even if beta passes placebo, its 50:1 risk/reward + 100% win is a tail-trap, not alpha.")
