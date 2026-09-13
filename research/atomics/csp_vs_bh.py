#!/usr/bin/env python3
"""HONEST CSP edge test — does selling a cash-secured put beat buy-and-hold?

The wheel backtest (bot/wheel_backtest.py) reported F PF 2.60 / stable-universe
PF 2.52, but that number is RAW DOLLAR P&L over 2019-2026 — a bull market — with
NO option bid/ask spread, realized-vol (no-VRP) pricing, and no comparison to
just owning the stock. A cash-secured put is economically a COVERED CALL / long-
equity overlay, so its edge over buy-and-hold is the ONLY thing that matters.

This test asks the decisive question, name by name:
    CSP_ret  = (net premium  -  max(K - S_expiry, 0)) / K        (sell 30d put)
    BH_ret   = S_expiry / S_entry - 1                              (own the stock)
    overlay  = CSP_ret - BH_ret
If overlay ~ 0 (or negative), the "edge" is just long-beta. If overlay > 0
consistently, selling premium genuinely adds value on that name.

Honest assumptions (mirror LIVE fills):
  - Option priced Black-Scholes at TRAILING 30d realized vol (clamped 15-150%).
    This is the NO-VRP baseline: if CSP beats BH here, the edge is robust; if it
    only beats BH when we ADD the VRP, the edge is VRP-dependent (index-only).
  - Option bid/ask: spread = max(0.03, 0.15*mid), SELL at mid - spread/2.
    (Live F $13.50p: bid .11 / ask .14 = .03 spread on .125 mid — matches.)
  - No early management; settle at expiry. 21 trading days (~1 month) per cycle.
  - Capital per cycle = 100*K (put collateral) vs 100*S (stock). Returns in %.
"""
import math
import json
import numpy as np
import pandas as pd
import yfinance as yf

UNIVERSE = [
    # large-cap dividend / value
    'F','T','VZ','INTC','PFE','KHC','GM','CSCO','XOM','WBA','KO','MMM','IBM','ORCL',
    # large-cap growth
    'AAPL','MSFT','NVDA','GOOGL','AMZN','META','TSLA','NFLX','AMD','CRM','MU','QCOM',
    # financials / cyclicals
    'BAC','C','JPM','WFC','DIS','SBUX','NKE','MCD','CAT','DE','HON','BA','GE','OXY','DVN',
    # mid / high-beta
    'SOFI','PLTR','UBER','ABNB','ROKU','DKNG','HOOD','COIN','PINS','TWLO','SNAP','RIVN','PLUG','NIO','AAL','CCL','GME','AMC','LCID','TLRY','MRO','F',
]
UNIVERSE = list(dict.fromkeys(UNIVERSE))  # dedupe, keep order

DTE = 21          # trading days (~1 month)
DELTA = 0.30      # short put target delta
R = 0.02
VOL_WINDOW = 30
VOL_FLOOR, VOL_CAP = 0.15, 1.50
START = '2016-01-01'
MIN_PRICE = 3.0
MAX_PRICE = 200.0

def ncdf(x): return 0.5*(1.0+math.erf(x/math.sqrt(2)))
def _d1(S,K,t,s,r): return (math.log(S/K)+(r+0.5*s*s)*t)/(s*math.sqrt(t))
def bs(S,K,t,s,r,kind='put'):
    if t<=0: return max(K-S,0.0) if kind=='put' else max(S-K,0.0)
    d1=_d1(S,K,t,s,r); d2=d1-s*math.sqrt(t)
    if kind=='put': return K*math.exp(-r*t)*ncdf(-d2)-S*ncdf(-d1)
    return S*ncdf(d1)-K*math.exp(-r*t)*ncdf(d2)
def bs_delta(S,K,t,s,r,kind='put'):
    if t<=0: return -1.0 if(kind=='put' and S<K) else(1.0 if kind=='call' and S>=K else 0.0)
    return ncdf(_d1(S,K,t,s,r))-1.0 if kind=='put' else ncdf(_d1(S,K,t,s,r))
def strike_for_delta(S,t,s,r,target,kind='put'):
    lo,hi=S*0.05,S*4.0
    for _ in range(80):
        m=0.5*(lo+hi); d=bs_delta(S,m,t,s,r,kind)
        if kind=='put':
            if -d>target: hi=m
            else: lo=m
        else:
            if d>target: lo=m
            else: hi=m
    return 0.5*(lo+hi)

def col(df,n):
    return df[n].iloc[:,0] if isinstance(df.columns,pd.MultiIndex) else df[n]

def run_name(sym):
    try:
        df = yf.download(sym, start=START, interval='1d', progress=False, auto_adjust=True)
    except Exception as e:
        return {'sym': sym, 'error': f'download {str(e)[:40]}'}
    px = col(df,'Close').dropna()
    if len(px) < 500:
        return {'sym': sym, 'error': f'insufficient data ({len(px)})'}
    ret = np.log(px/px.shift(1))
    vol = (ret.rolling(VOL_WINDOW).std()*math.sqrt(252)).clip(VOL_FLOOR, VOL_CAP)
    S = px.to_numpy()
    v = vol.to_numpy()
    n = len(S)
    csp, bh = [], []
    for i in range(60, n-DTE, DTE):
        s0 = S[i]; sig = v[i]
        if not (MIN_PRICE <= s0 <= MAX_PRICE) or not np.isfinite(sig) or sig<=0:
            continue
        tau = DTE/252.0
        K = strike_for_delta(s0, tau, sig, R, DELTA, 'put')
        mid = bs(s0, K, tau, sig, R, 'put')
        spread = max(0.03, 0.15*mid)
        net_prem = max(mid - spread/2.0, 0.0)   # sell at bid
        se = S[i+DTE]
        # CSP return on collateral K
        csp_pnl = net_prem - max(K - se, 0.0)
        csp.append(csp_pnl / K)
        # buy-and-hold return
        bh.append(se / s0 - 1.0)
    if len(csp) < 10:
        return {'sym': sym, 'error': f'only {len(csp)} cycles'}
    csp = np.array(csp); bh = np.array(bh)
    overlay = csp - bh
    def stat(x):
        return dict(mean=x.mean(), med=np.median(x), win=(x>0).mean())
    return dict(sym=sym, n=len(csp), last=float(S[-1]),
                csp=stat(csp), bh=stat(bh), overlay=stat(overlay),
                csp_pf=(csp[csp>0].sum()/abs(csp[csp<=0].sum()) if (csp<=0).any() else float('inf')))

def main():
    rows = []
    print(f"{'sym':<6} {'last':>7} {'n':>4} {'CSP%':>8} {'BH%':>8} {'overlay%':>9} {'ov.win%':>7} {'CSP PF':>7}")
    print('-'*66)
    for sym in UNIVERSE:
        r = run_name(sym)
        if 'error' in r:
            print(f"{sym:<6}  {r['error']}")
            continue
        rows.append(r)
        print(f"{sym:<6} {r['last']:>7.2f} {r['n']:>4} {r['csp']['mean']*100:>+7.2f} "
              f"{r['bh']['mean']*100:>+7.2f} {r['overlay']['mean']*100:>+8.2f} "
              f"{r['overlay']['win']*100:>6.0f}% {r['csp_pf']:>7.2f}")
    # pooled summary
    ov = np.array([r['overlay']['mean'] for r in rows])
    print('\n' + '='*66)
    print(f'Pooled overlay (CSP - BH), {len(rows)} names: mean {ov.mean()*100:+.3f}% / median {np.median(ov)*100:+.3f}%')
    print(f'Names with POSITIVE overlay: {(ov>0).sum()}/{len(rows)}')
    print(f'Overlay t-stat (across names): {ov.mean()/(ov.std(ddof=1)/math.sqrt(len(ov))):+.2f}')
    json.dump(rows, open('/home/ubuntu/trading-system/research/atomics/csp_vs_bh.json','w'), indent=1, default=float)

if __name__ == '__main__':
    main()
