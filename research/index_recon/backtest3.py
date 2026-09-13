#!/usr/bin/env python
"""Final robustness: tradeable-entry OOS, next-open entry, era split on tradeable forms."""
import json, datetime, os
import numpy as np
import pandas as pd

CACHE = "/home/ubuntu/trading-system/research/index_recon/cache"
COST = 6.0 / 10000.0

spy = pd.read_parquet(os.path.join(CACHE, "SPY.parquet"))["adjclose"]
spy.index = pd.to_datetime(spy.index)
spy = spy[~spy.index.duplicated(keep="last")].sort_index()

events = json.load(open("/home/ubuntu/trading-system/research/index_recon/events.json"))
for e in events:
    e["eff"] = datetime.date.fromisoformat(e["eff"])
    e["ann"] = datetime.date.fromisoformat(e["ann"]) if e.get("ann") else None

def load_series(tk):
    p = os.path.join(CACHE, f"{tk}.parquet")
    if not os.path.exists(p): return None
    s = pd.read_parquet(p)["adjclose"]; s.index = pd.to_datetime(s.index)
    return s[~s.index.duplicated(keep="last")].sort_index()

def stat(x):
    x=np.array(x); n=len(x)
    if n<2: return None
    m=x.mean(); sd=x.std(ddof=1)
    return dict(n=n, mean=m*10000, t=m/(sd/np.sqrt(n)), med=np.median(x)*10000, pos=(x>0).mean())

def clust(vals, dates):
    import collections
    vals=np.array(vals); n=len(vals)
    if n<2: return np.nan
    m=vals.mean(); resid=vals-m
    g=collections.defaultdict(list)
    for v,d in zip(vals,dates): g[d].append(v)
    gids=list(g.keys())
    sc=np.array([sum(resid[i] for i in range(n) if dates[i]==gd) for gd in gids])
    V=(len(gids)/(len(gids)-1))*((n-1)/n)*np.sum(sc**2)/(n**2)
    return m/np.sqrt(V) if V>0 else np.nan

def pn(s, ct=None):
    if s is None: return ""
    extra=f" t_clust={ct:+5.2f}" if ct is not None else ""
    return f"n={s['n']:3d} mean={s['mean']:+6.1f}bp med={s['med']:+6.1f}bp t={s['t']:+5.2f}{extra} pos={s['pos']*100:3.0f}%"

# --- tradeable entry: next-day OPEN ---
print("=== Announcement drift, entry = NEXT-OPEN (most realistic tradeable) ===")
for h in [5,10,20]:
    vals,ds=[],[]
    for e in events:
        if e["ann"] is None: continue
        s=load_series(e["ticker"])
        if s is None: continue
        idx=s.index; pos=idx.searchsorted(pd.Timestamp(e["ann"]))
        if pos+1+h < len(idx):
            p0=s.iloc[pos+1]; p1=s.iloc[pos+1+h]   # open proxied by next close? use next OPEN below
            # next-open requires Open column; we only stored Close. Use next-close as lower bound on entry,
            # but here compute next-OPEN via raw Open — reload raw? Instead report next-close (already have).
            pass
    # We don't have Open cached; skip next-open, note next-close is the conservative proxy.
print("  (Open column not cached; next-CLOSE entry is the conservative proxy — see backtest.py Test 1)")

# --- OOS for tradeable next-close entry ---
print("\n=== Chronological OOS (last 30%) for TRADEABLE entries ===")
ann_sorted = sorted([e for e in events if e["ann"] and load_series(e["ticker"]) is not None], key=lambda e: e["ann"])
cut = int(len(ann_sorted)*0.70)
o = ann_sorted[cut:]
print(f"  OOS n={len(o)} from {o[0]['ann']} to {o[-1]['ann']}")
for h in [5,10,20]:
    vals,ds=[],[]
    for e in o:
        s=load_series(e["ticker"]); idx=s.index; pos=idx.searchsorted(pd.Timestamp(e["ann"]))
        if pos+1+h < len(idx):
            p0=s.iloc[pos+1]; p1=s.iloc[pos+1+h]
            sp0=spy.index.searchsorted(idx[pos+1])
            if sp0+h < len(spy) and p0>0 and p1>0:
                m=spy.iloc[sp0+h]/spy.iloc[sp0]-1
                vals.append((p1/p0-1)-m-COST); ds.append(str(idx[pos+1].date()))
    s=stat(vals)
    print(f"  OOS next-close -> +{h}d: {pn(s, clust(vals,ds))}")

# --- OOS for effective-date entry ---
eff_sorted = sorted([e for e in events if e["eff"].year>=2000 and load_series(e["ticker"]) is not None], key=lambda e: e["eff"])
cut2 = int(len(eff_sorted)*0.70)
o2 = eff_sorted[cut2:]
print(f"  OOS (eff) n={len(o2)} from {o2[0]['eff']} to {o2[-1]['eff']}")
for h in [5,10,20]:
    vals,ds=[],[]
    for e in o2:
        s=load_series(e["ticker"]); idx=s.index; pos=idx.searchsorted(pd.Timestamp(e["eff"]))
        if pos+h < len(idx):
            p0=s.iloc[pos]; p1=s.iloc[pos+h]
            sp0=spy.index.searchsorted(idx[pos])
            if sp0+h < len(spy) and p0>0 and p1>0:
                m=spy.iloc[sp0+h]/spy.iloc[sp0]-1
                vals.append((p1/p0-1)-m-COST); ds.append(str(idx[pos].date()))
    s=stat(vals)
    print(f"  OOS eff-close -> +{h}d: {pn(s, clust(vals,ds))}")

# --- era split on tradeable next-close entry (post-announcement drift) ---
print("\n=== Tradeable next-close drift by era (pre vs post 2015) ===")
for h in [5,10,20]:
    pre,post=[],[]
    for e in events:
        if e["ann"] is None: continue
        s=load_series(e["ticker"])
        if s is None: continue
        idx=s.index; pos=idx.searchsorted(pd.Timestamp(e["ann"]))
        if pos+1+h < len(idx):
            p0=s.iloc[pos+1]; p1=s.iloc[pos+1+h]
            sp0=spy.index.searchsorted(idx[pos+1])
            if sp0+h < len(spy) and p0>0 and p1>0:
                m=spy.iloc[sp0+h]/spy.iloc[sp0]-1
                v=(p1/p0-1)-m-COST
                (pre if e["ann"].year<2015 else post).append(v)
    sp=stat(pre); st=stat(post)
    print(f"  +{h}d pre-2015: {pn(sp)}  |  post-2015: {pn(st)}")

# --- sample size / coverage summary ---
print("\n=== Coverage summary ===")
alltk = set(e["ticker"] for e in events)
have = set(tk for tk in alltk if load_series(tk) is not None)
print(f"  events (2000+) = {len([e for e in events if e['eff'].year>=2000])}")
print(f"  unique tickers = {len(alltk)}, with price data = {len(have)}, missing = {len(alltk-have)}")
miss_2019 = [e["ticker"] for e in events if e["eff"].year>=2019 and load_series(e["ticker"]) is None]
print(f"  missing tickers among 2019+ adds: {sorted(set(miss_2019))}")
