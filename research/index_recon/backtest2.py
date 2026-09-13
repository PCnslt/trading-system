#!/usr/bin/env python
"""Extended: tradeable entries + the announcement 'pop' + concentration checks."""
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
    if not os.path.exists(p):
        return None
    s = pd.read_parquet(p)["adjclose"]
    s.index = pd.to_datetime(s.index)
    return s[~s.index.duplicated(keep="last")].sort_index()

def stat(x):
    x = np.array(x)
    n = len(x)
    if n < 2: return None
    m = x.mean(); sd = x.std(ddof=1)
    return dict(n=n, mean=m*10000, sd=sd*10000, t=m/(sd/np.sqrt(n)),
                med=np.median(x)*10000, pos=(x>0).mean())

def cluster_t(vals, dates):
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

# ---- A. The announcement pop: ann-close -> next-close (and next-open) ----
print("=== A. Announcement reaction ('pop'): ann-close -> next-day close ===")
pop, popd = [], []
for e in events:
    if e["ann"] is None: continue
    s = load_series(e["ticker"])
    if s is None: continue
    idx = s.index
    pos = idx.searchsorted(pd.Timestamp(e["ann"]))
    if pos + 1 < len(idx):
        r = s.iloc[pos+1]/s.iloc[pos] - 1
        # mkt adj over same 1-day
        sp0 = spy.index.searchsorted(idx[pos])
        if sp0+1 < len(spy):
            m = spy.iloc[sp0+1]/spy.iloc[sp0] - 1
            pop.append(r - m); popd.append(str(idx[pos].date()))
s=stat(pop); s['t_clust']=cluster_t(pop,popd)
print(f"  pop (1-day, mkt-adj): n={s['n']} mean={s['mean']:+6.1f}bp med={s['med']:+6.1f}bp t={s['t']:+5.2f} t_clust={s['t_clust']:+5.2f} pos={s['pos']*100:.0f}%")

# ---- B. Tradeable pre-add drift: next-close -> effective close ----
print("\n=== B. TRADEABLE pre-add drift: next-day-close -> effective-close (net 6bp) ===")
pre, pred = [], []
for e in events:
    if e["ann"] is None: continue
    s = load_series(e["ticker"])
    if s is None: continue
    idx = s.index
    pos = idx.searchsorted(pd.Timestamp(e["ann"]))
    pef = idx.searchsorted(pd.Timestamp(e["eff"]))
    if pos+1 < len(idx) and pef < len(idx) and pef > pos+1:
        p0 = s.iloc[pos+1]; p1 = s.iloc[pef]
        sp0 = spy.index.searchsorted(idx[pos+1]); spf = spy.index.searchsorted(idx[pef])
        if spf < len(spy) and sp0 < len(spy) and p0>0 and p1>0:
            r = p1/p0-1; m = spy.iloc[spf]/spy.iloc[sp0]-1
            pre.append(r-m-COST); pred.append(str(e["ann"]))
s=stat(pre); s['t_clust']=cluster_t(pre,pred)
print(f"  n={s['n']} mean={s['mean']:+6.1f}bp med={s['med']:+6.1f}bp t={s['t']:+5.2f} t_clust={s['t_clust']:+5.2f} pos={s['pos']*100:.0f}%")

# ---- C. Post-effective drift concentration (top-10 names/dates share) ----
print("\n=== C. Concentration: post-effective +20d drift (eff-close, net 6bp, mkt-adj) ===")
rows = []
for e in events:
    if e["eff"].year < 2000: continue
    s = load_series(e["ticker"])
    if s is None: continue
    idx = s.index
    pos = idx.searchsorted(pd.Timestamp(e["eff"]))
    if pos+20 < len(idx):
        p0=s.iloc[pos]; p1=s.iloc[pos+20]
        sp0=spy.index.searchsorted(idx[pos])
        if sp0+20 < len(spy) and p0>0 and p1>0:
            m=spy.iloc[sp0+20]/spy.iloc[sp0]-1
            rows.append(dict(tk=e["ticker"], eff=str(e["eff"]), val=(p1/p0-1)-m-COST))
df = pd.DataFrame(rows)
total = df['val'].sum()
print(f"  n={len(df)} total mkt-adj net P&L (sum of bp/fraction) = {total*10000:.0f}bp")
top10n = df.nlargest(10,'val')
top10d = df.nlargest(10,'val')
print(f"  top-10 NAMES share of total P&L: {top10n['val'].sum()/total*100:.1f}%")
print(f"  top-10 NAMES: {list(zip(top10n['tk'], (top10n['val']*10000).round(0).astype(int)))}")
# top 10 dates by total P&L on that date
df['d'] = df['eff']
g = df.groupby('d')['val'].sum().sort_values(ascending=False)
print(f"  top-10 DATES share of total P&L: {g.head(10).sum()/total*100:.1f}%")
print(f"  top-10 DATES: {[(d, round(v*10000,0)) for d,v in g.head(10).items()]}")
# what about the LARGEST adds (market cap) - is the effect concentrated in mega-caps?
# (proxy: use magnitude of pop? skip)

# ---- D. Post-effective drift by year (to see if negative is consistent or era-driven) ----
print("\n=== D. Post-effective +20d drift by year (net 6bp, mkt-adj) ===")
yr = df.copy(); yr['y'] = pd.to_datetime(yr['eff']).dt.year
for y in sorted(yr['y'].unique()):
    sub = yr[yr['y']==y]['val']
    if len(sub)>=3:
        m=sub.mean()*10000; t=sub.mean()/(sub.std(ddof=1)/np.sqrt(len(sub)))
        print(f"  {y}: n={len(sub):2d} mean={m:+7.1f}bp t={t:+5.2f}")
