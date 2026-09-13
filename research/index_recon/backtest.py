#!/usr/bin/env python
"""Index reconstitution drift backtest (S&P 500 adds) — event study.

Discipline (per trading-backtest-validation skill):
- market-adjusted (vs SPY) returns, net of 6bp round-trip, long-only
- date-clustered t-stat (cluster-robust SE by event date)
- chronological OOS (last ~30% of events by time)
- era split pre/post-2015 for the decay question
"""
import json, datetime, os
import numpy as np
import pandas as pd

CACHE = "/home/ubuntu/trading-system/research/index_recon/cache"
COST_BP = 6.0
COST = COST_BP / 10000.0

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
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s

def fwd_ret(s, entry_date, h):
    """return from entry_date close to entry_date+h trading days close. entry at first bar >= entry_date."""
    idx = s.index
    pos = idx.searchsorted(pd.Timestamp(entry_date))
    if pos >= len(idx):
        return None, None
    t0 = idx[pos]
    epos = pos + h
    if epos >= len(idx):
        return None, None
    t1 = idx[epos]
    p0, p1 = s.iloc[pos], s.iloc[epos]
    if p0 <= 0 or p1 <= 0 or np.isnan(p0) or np.isnan(p1):
        return None, None
    return (p1 / p0 - 1.0), t0

def spy_fwd(entry_ts, h):
    """SPY return over the same h trading days starting at first bar >= entry_ts."""
    pos = spy.index.searchsorted(entry_ts)
    if pos >= len(spy.index):
        return None
    epos = pos + h
    if epos >= len(spy.index):
        return None
    return spy.iloc[epos] / spy.iloc[pos] - 1.0

def run(ev, entry_dates, horizons):
    """For each horizon, compute market-adjusted net return. entry_dates: list of (label, date)."""
    s = load_series(ev["ticker"])
    if s is None:
        return None
    out = {}
    for label, d in entry_dates:
        if d is None:
            continue
        for h in horizons:
            r, t0 = fwd_ret(s, d, h)
            if r is None:
                continue
            m = spy_fwd(t0, h)
            if m is None:
                continue
            out[(label, h)] = dict(ret=r, mkt=m, xr=r - m, net=r - m - COST, t0=str(t0.date()))
    return out

# ---------- Build event tables ----------
def build_events():
    ann_ev = []   # events with announcement dates
    eff_ev = []   # all events (effective date entry)
    for e in events:
        if e["eff"].year < 2000:
            continue
        if e["ann"] is not None:
            ann_ev.append(e)
        eff_ev.append(e)
    return ann_ev, eff_ev

def summarize(rows, label):
    if not rows:
        return None
    x = np.array(rows)
    n = len(x)
    mean = x.mean()
    sd = x.std(ddof=1)
    t = mean / (sd / np.sqrt(n)) if sd > 0 else np.nan
    med = np.median(x)
    pos = (x > 0).mean()
    # PF on net market-adjusted (long-only)
    gains = x[x > 0].sum()
    losses = -x[x < 0].sum()
    pf = gains / losses if losses > 0 else np.inf
    return dict(n=n, mean_bp=mean * 10000, med_bp=med * 10000, pos=pos,
                t=t, pf=pf, sd_bp=sd * 10000)

def clustered_t(vals, dates):
    """cluster-robust t-stat clustering by date."""
    vals = np.array(vals); dates = list(dates)
    n = len(vals)
    if n < 2:
        return np.nan
    mean = vals.mean()
    # cluster by date string
    import collections
    groups = collections.defaultdict(list)
    for v, d in zip(vals, dates):
        groups[d].append(v)
    # Cameron-Gelbach-Miller cluster-robust variance
    gids = list(groups.keys())
    # residual = vals - mean
    resid = vals - mean
    # sum of cluster scores
    score = np.array([sum(resid[i] for i in range(n) if dates[i] == g) for g in gids])
    V = (len(gids) / (len(gids) - 1)) * ((n - 1) / n) * np.sum(score ** 2) / (n ** 2)
    se = np.sqrt(V)
    return mean / se if se > 0 else np.nan

def table(rows, dates, title):
    s = summarize(rows, title)
    if s is None:
        return None
    s["t_clust"] = clustered_t(rows, dates)
    return s

# ================= ANALYSIS =================
ann_ev, eff_ev = build_events()
print(f"announcement-date events (2000+): {len(ann_ev)}")
print(f"effective-date events (2000+): {len(eff_ev)}")

HORIZONS = [5, 10, 20]

# ---- Test 1: Announcement drift (exact ann dates), entry at ann close ----
print("\n=== TEST 1: Announcement-day drift (entry = ann-day close, net 6bp, mkt-adj) ===")
results = {h: [] for h in HORIZONS}
dates = {h: [] for h in HORIZONS}
results_next = {h: [] for h in HORIZONS}   # entry = next-day close (realistic)
for e in ann_ev:
    s = load_series(e["ticker"])
    if s is None:
        continue
    for h in HORIZONS:
        r, t0 = fwd_ret(s, e["ann"], h)
        if r is None:
            continue
        m = spy_fwd(t0, h)
        if m is None:
            continue
        results[h].append(r - m - COST)
        dates[h].append(str(t0.date()))
        # next-day close entry
        r2, t0b = fwd_ret(s, e["ann"], 1)
        if r2 is not None:
            # entry at ann-day+1 close, hold h days from there
            idx = s.index
            pos = idx.searchsorted(pd.Timestamp(e["ann"]))
            ep = pos + 1 + h
            if ep < len(idx):
                p0 = s.iloc[pos + 1]; p1 = s.iloc[ep]
                sp0 = spy.index.searchsorted(idx[pos + 1])
                if sp0 + h < len(spy) and p0 > 0 and p1 > 0:
                    m2 = spy.iloc[sp0 + h] / spy.iloc[sp0] - 1
                    results_next[h].append((p1 / p0 - 1) - m2 - COST)

for h in HORIZONS:
    t = table(results[h], dates[h], f"ann+{h}")
    if t:
        print(f"  ann-close -> +{h}d: n={t['n']:3d} mean={t['mean_bp']:+6.1f}bp med={t['med_bp']:+6.1f}bp "
              f"pos={t['pos']*100:4.0f}% t={t['t']:+5.2f} t_clust={t['t_clust']:+5.2f} PF={t['pf']:.2f}")
    tn = summarize(results_next[h], f"next+{h}")
    if tn:
        print(f"    next-close -> +{h}d: n={tn['n']:3d} mean={tn['mean_bp']:+6.1f}bp t={tn['t']:+5.2f} PF={tn['pf']:.2f}")

# ---- Test 2: Pre-add drift (ann close -> effective close) ----
print("\n=== TEST 2: Pre-add drift (ann-close -> effective-close, net 6bp, mkt-adj) ===")
pre_rows, pre_dates = [], []
for e in ann_ev:
    s = load_series(e["ticker"])
    if s is None:
        continue
    a = pd.Timestamp(e["ann"]); f = pd.Timestamp(e["eff"])
    if f <= a:
        continue
    pa = s.index.searchsorted(a); pf = s.index.searchsorted(f)
    if pa >= len(s.index) or pf >= len(s.index):
        continue
    p0, p1 = s.iloc[pa], s.iloc[pf]
    m0 = spy.index.searchsorted(s.index[pa]); mf = spy.index.searchsorted(s.index[pf])
    if m0 >= len(spy) or mf >= len(spy) or p0 <= 0 or p1 <= 0:
        continue
    r = p1 / p0 - 1
    m = spy.iloc[mf] / spy.iloc[m0] - 1
    pre_rows.append(r - m - COST)
    pre_dates.append(str(e["ann"]))
t = table(pre_rows, pre_dates, "pre-add")
if t:
    print(f"  n={t['n']:3d} mean={t['mean_bp']:+6.1f}bp med={t['med_bp']:+6.1f}bp pos={t['pos']*100:4.0f}% "
          f"t={t['t']:+5.2f} t_clust={t['t_clust']:+5.2f} PF={t['pf']:.2f}")

# ---- Test 3: Effective-date drift (full history 2000+) ----
print("\n=== TEST 3: Effective-date drift (entry = eff-day close, net 6bp, mkt-adj, full 2000+) ===")
eff_results = {h: [] for h in HORIZONS}
eff_dates = {h: [] for h in HORIZONS}
eff_meta = {h: [] for h in HORIZONS}  # store (val, eff_year, ticker)
for e in eff_ev:
    s = load_series(e["ticker"])
    if s is None:
        continue
    for h in HORIZONS:
        r, t0 = fwd_ret(s, e["eff"], h)
        if r is None:
            continue
        m = spy_fwd(t0, h)
        if m is None:
            continue
        eff_results[h].append(r - m - COST)
        eff_dates[h].append(str(t0.date()))
        eff_meta[h].append((r - m - COST, e["eff"].year, e["ticker"]))

for h in HORIZONS:
    t = table(eff_results[h], eff_dates[h], f"eff+{h}")
    if t:
        print(f"  eff-close -> +{h}d: n={t['n']:3d} mean={t['mean_bp']:+6.1f}bp med={t['med_bp']:+6.1f}bp "
              f"pos={t['pos']*100:4.0f}% t={t['t']:+5.2f} t_clust={t['t_clust']:+5.2f} PF={t['pf']:.2f}")

# ---- Test 4: Era split pre/post 2015 (effective-date drift) ----
print("\n=== TEST 4: Era split (effective-date drift, net 6bp) ===")
for h in HORIZONS:
    pre = [(v, y) for v, y, _ in eff_meta[h] if y < 2015]
    post = [(v, y) for v, y, _ in eff_meta[h] if y >= 2015]
    for era, rows in [("pre-2015", pre), ("post-2015", post)]:
        if not rows:
            continue
        vals = np.array([r[0] for r in rows])
        n = len(vals)
        mean = vals.mean(); sd = vals.std(ddof=1)
        tstat = mean / (sd / np.sqrt(n)) if sd > 0 else np.nan
        print(f"  +{h}d {era:9s}: n={n:3d} mean={mean*10000:+6.1f}bp t={tstat:+5.2f} pos={(vals>0).mean()*100:4.0f}%")

# ---- Chronological OOS (last 30% by effective date, on the announcement-drift sample) ----
print("\n=== TEST 5: Chronological OOS (announcement-drift, last 30% of events by date) ===")
ann_sorted = sorted([e for e in ann_ev if load_series(e["ticker"]) is not None], key=lambda e: e["ann"])
cut = int(len(ann_sorted) * 0.70)
o = ann_sorted[cut:]
print(f"  IS n={cut}  OOS n={len(o)}  (OOS from {o[0]['ann']})")
for h in HORIZONS:
    vals, ds = [], []
    for e in o:
        s = load_series(e["ticker"])
        r, t0 = fwd_ret(s, e["ann"], h)
        if r is None:
            continue
        m = spy_fwd(t0, h)
        if m is None:
            continue
        vals.append(r - m - COST); ds.append(str(t0.date()))
    t = table(vals, ds, f"OOS+{h}")
    if t:
        print(f"  OOS ann-close -> +{h}d: n={t['n']:3d} mean={t['mean_bp']:+6.1f}bp t={t['t']:+5.2f} t_clust={t['t_clust']:+5.2f} PF={t['pf']:.2f}")

# ---- Raw (no mkt-adjust, no cost) for context on the announcement drift ----
print("\n=== Context: raw gross returns (ann-close, no mkt adj, no cost) ===")
for h in HORIZONS:
    vals = []
    for e in ann_ev:
        s = load_series(e["ticker"])
        if s is None:
            continue
        r, t0 = fwd_ret(s, e["ann"], h)
        if r is not None:
            vals.append(r)
    if vals:
        vals = np.array(vals)
        print(f"  +{h}d raw gross: n={len(vals)} mean={vals.mean()*10000:+6.1f}bp med={np.median(vals)*10000:+6.1f}bp")
