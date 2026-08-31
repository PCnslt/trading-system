import pandas as pd, numpy as np

SECTORS = ['XLK','XLF','XLE','XLV','XLI','XLY','XLP','XLU','XLB']
def load(s):
    df = pd.read_parquet(f'/tmp/{s}_daily.parquet')
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date').sort_index()['close']

px = pd.DataFrame({s: load(s) for s in SECTORS + ['SPY']}).dropna()
spy = px['SPY']
idx = px.index

def momentum(lookback, skip):
    # skip recent `skip` days: return over [T-lookback-skip, T-skip]
    return px.shift(skip) / px.shift(lookback + skip) - 1.0

def portfolio_return(sel, d, step):
    j = idx.get_loc(d)
    if j + step >= len(idx): return None
    dn = idx[j + step]
    return np.mean([px[s].loc[dn] / px[s].loc[d] - 1.0 for s in sel])

def run(mom, rebalance, topn, oos_frac=0.30):
    step = {'weekly':5,'biweekly':10,'monthly':21}[rebalance]
    reb = idx[step::step]
    split = int(len(reb) * (1 - oos_frac))
    out = {}
    for seg, dates in [('IS', reb[:split]), ('OOS', reb[split:])]:
        spread = []
        for d in dates:
            m = mom.loc[d].dropna()
            if len(m) < 5: continue
            top = m.nlargest(topn).index
            pr = portfolio_return(top, d, step)
            if pr is None: continue
            spread.append((pr - (spy.shift(-step).loc[d]/spy.loc[d]-1)) * 10000)
        out[seg] = np.array(spread)
    return out

# --- corrected momentum matrix (monthly, top-1/3) ---
print("=== CORRECTED MATRIX: monthly rebalance, OOS spread vs SPY (bp/mo) ===")
print(f"{'lookback':>8} {'skip':>4} {'top':>4} | {'OOS':>8} {'win%':>5} {'t':>6} {'n':>4}")
results = []
for lb in (5,10,20,60,120,252):
    for sk in (0,1,5,10,20):
        for tn in (1,3):
            mom = momentum(lb, sk)
            r = run(mom, 'monthly', tn)
            if len(r['OOS']) < 20: continue
            oos = r['OOS']; t = oos.mean()/oos.std()*np.sqrt(len(oos))
            results.append((lb, sk, tn, oos.mean(), (oos>0).mean(), t, len(oos)))
            print(f"{lb:>8} {sk:>4} {tn:>4} | {oos.mean():>7.1f} {(oos>0).mean()*100:>4.0f}% {t:>6.2f} {len(oos):>4}")

# --- placebo controls (monthly) ---
print("\n=== PLACEBO CONTROLS (monthly, spread vs SPY, bp/mo, OOS) ===")
def placebo(how):
    step=21; reb=idx[step::step]; split=int(len(reb)*0.7)
    out=[]
    for d in reb[split:]:
        m = momentum(10,0).loc[d].dropna()
        if len(m)<5: continue
        if how=='random': sel=[np.random.choice(SECTORS)]
        elif how=='reverse': sel=m.nsmallest(1).index
        elif how=='median': sel=[m.sort_values().index[len(m)//2]]
        elif how=='equal': sel=list(SECTORS)
        elif how=='prev_winner': sel=[m.sort_values().index[-2]]  # 2nd place (lag)
        pr = portfolio_return(sel, d, step)
        if pr is None: continue
        out.append((pr - (spy.shift(-step).loc[d]/spy.loc[d]-1))*10000)
    o=np.array(out); return o.mean(), o.std()/np.sqrt(len(o)), len(o)
np.random.seed(0)
for name in ['random','reverse','median','equal','prev_winner']:
    m_,se,n = placebo(name)
    print(f"{name:>12}: {m_:>7.1f}bp  (t {m_/se:.2f}, n={n})")

# --- concentration: best config (10d, skip0, top1) ---
print("\n=== CONCENTRATION: 10d/skip0/top1/monthly, full-sample spread by year ===")
mom = momentum(10,0); step=21; reb=idx[step::step]
by_year = {}
for d in reb:
    m = mom.loc[d].dropna()
    if len(m)<5: continue
    top = m.nlargest(1).index
    pr = portfolio_return(top, d, step)
    if pr is None: continue
    sp = (pr - (spy.shift(-step).loc[d]/spy.loc[d]-1))*10000
    by_year.setdefault(d.year, []).append(sp)
for y in sorted(by_year):
    a = np.array(by_year[y])
    print(f"{y}: {a.mean():>7.1f}bp  n={len(a)}")
all_spreads = np.concatenate(list(by_year.values()))
all_spreads.sort()
print(f"\nFull-sample spread: mean {all_spreads.mean():.1f}bp, top-5 months = {all_spreads[-5:].sum():.1f}bp of {all_spreads.sum():.1f}bp total ({all_spreads[-5:].sum()/all_spreads.sum()*100:.0f}%)")
