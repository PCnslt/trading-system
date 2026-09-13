#!/usr/bin/env python3
"""Verify the MGC gold slow-TSMOM / Donchian claim (subagent: 'OOS PF 1.73-1.81').

Decisive test the fan-out didn't run: is gold trend-following ALPHA, or just
GOLD BETA with timing? Compare both strategies to buy-and-hold gold (same
underlying, same period) on Sharpe/CAGR/maxDD, full-sample AND chronological
OOS (last 40% of dates). Charge honest per-trade cost (1-2 ticks ≈ ~1bp RT on
$20k MGC notional; use 2bp RT to be conservative).
"""
import math
import numpy as np
import pandas as pd
import yfinance as yf

df = yf.download('GC=F', start='2000-01-01', interval='1d', progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
px = df['Close'].dropna()
px = px[~px.index.duplicated(keep='last')]
ret = px.pct_change().fillna(0.0)

def stats(r, label, ann=252):
    r = r.dropna()
    if len(r) == 0:
        print(f"  {label:<28} n=0"); return None
    sharpe = r.mean()/r.std()*math.sqrt(ann) if r.std() > 0 else 0
    eq = (1+r).cumprod()
    cagr = eq.iloc[-1]**(ann/len(r)) - 1
    dd = (eq/eq.cummax() - 1).min()
    # PF on daily strategy returns
    wins = r[r>0].sum(); losses = abs(r[r<=0].sum())
    pf = wins/losses if losses > 0 else float('inf')
    print(f"  {label:<28} Sharpe={sharpe:+.2f} CAGR={cagr*100:+.1f}% maxDD={dd*100:.0f}% PF={pf:.2f} n={len(r)}")
    return dict(sharpe=sharpe, cagr=cagr, dd=dd, pf=pf)

def tsmom(px, ret, lookback=252, rebal=21):
    """sign of trailing 12m return, rebalanced every `rebal` bars, always-in-market."""
    mom = px / px.shift(lookback) - 1.0
    sig = np.sign(mom)
    # hold position constant between rebalance dates
    pos = sig.copy()
    pos.iloc[::rebal] = sig.iloc[::rebal]
    pos = pos.ffill().fillna(0.0)
    return pos.shift(1).fillna(0.0)

def donchian(px, ret, lookback=20, atr_n=14, stop_atr=2.0, time_stop=5):
    hi = px.rolling(lookback).max().shift(1)
    lo = px.rolling(lookback).min().shift(1)
    pos = pd.Series(0.0, index=px.index)
    p = 0.0
    entry_i = None
    for i in range(lookback, len(px)):
        c = px.iloc[i]
        if p == 0:
            if c > hi.iloc[i]: p = 1.0; entry_i = i
            elif c < lo.iloc[i]: p = -1.0; entry_i = i
        else:
            # time stop
            if entry_i is not None and i - entry_i >= time_stop:
                p = 0.0; entry_i = None
            elif p == 1 and c < lo.iloc[i]:
                p = -1.0; entry_i = i
            elif p == -1 and c > hi.iloc[i]:
                p = 1.0; entry_i = i
        pos.iloc[i] = p
    return pos.shift(1).fillna(0.0)

def evaluate(name, pos, ret, cost_rt_bp=2.0):
    strat = pos * ret
    # turnover cost (round-trip bp charged on each |dpos|)
    turn = pos.diff().abs().fillna(0.0)
    cost = turn * cost_rt_bp / 10000.0
    strat = strat - cost
    print(f"[{name}]")
    stats(strat, "strategy net")

# full-sample and OOS split (chronological, last 40%)
n = len(px)
oos_i = int(n*0.6)
for label, mask in [("FULL", pd.Series(True, index=px.index)),
                    ("OOS(last40%)", px.index >= px.index[oos_i])]:
    print(f"\n===== {label} =====")
    stats(ret[mask], "BUY&HOLD GOLD (drift)")
    evaluate("TSMOM 12m rebal21", tsmom(px, ret), ret)
    evaluate("Donchian 20d", donchian(px, ret), ret)

# how much of the time is gold trend UP (context)
up = (px.pct_change(252) > 0).mean()
print(f"\nGold up over trailing 12m: {up*100:.0f}% of days  (a long-biased trend signal rides this)")
print(f"Gold 2000->2026: {px.iloc[0]:.0f} -> {px.iloc[-1]:.0f}  ({(px.iloc[-1]/px.iloc[0]-1)*100:.0f}% total)")
