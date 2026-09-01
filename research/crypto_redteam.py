import boto3, json, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','AVAXUSDT','LINKUSDT','LTCUSDT','BCHUSDT','ADAUSDT','DOTUSDT','UNIUSDT','AAVEUSDT']

def load(s):
    d=json.loads(s3.get_object(Bucket=BUCKET, Key=f'crypto-hist/{s}/daily.json')['Body'].read())['bars']
    df=pd.DataFrame(d); df['date']=pd.to_datetime(df['date']); df=df.set_index('date')
    return df['close']

px=pd.DataFrame({s:load(s) for s in SYMS}).ffill()
px=px[px.notna().sum(axis=1)>=6]

L,H=14,7
past=px.pct_change(L); fwd=px.pct_change(H).shift(-H)

def mom_long(price_ret, k=3, cost=0.0, seed=None):
    rows=[]
    for d in past.index:
        r=past.loc[d].dropna()
        if len(r)<6: continue
        top=r.nlargest(k).index
        f=fwd.loc[d].reindex(top).dropna()
        if len(f): rows.append(f.mean()-cost)
    return pd.Series(rows, index=[d for d in past.index if len(past.loc[d].dropna())>=6][:len(rows)])

# 1. Long-only momentum net 20bp
mom=mom_long(px,k=3,cost=0.002)
# 2. Equal-weight basket (buy-and-hold all coins, H-day return) — the beta benchmark
basket=fwd.mean(axis=1).dropna()
# align
idx=mom.index.intersection(basket.index)
mom=mom[idx]; basket=basket[idx]
alpha=mom-basket  # momentum minus basket = true alpha
# non-overlapping resample every H days
nono=alpha.iloc[::H]
t_nono=nono.mean()/nono.std()*np.sqrt(len(nono))
print(f"1) Long-only mom net20bp: {mom.mean()*1e4:+.1f}bp/yr-agnostic (t_raw={mom.mean()/mom.std()*np.sqrt(len(mom)):.2f})")
print(f"2) Equal-weight basket:   {basket.mean()*1e4:+.1f}bp")
print(f"3) ALPHA (mom-basket):    {alpha.mean()*1e4:+.1f}bp, t_nonoverlap={t_nono:.2f} (n={len(nono)})")
print(f"4) Corr(mom,basket)={np.corrcoef(mom,basket)[0,1]:.2f}  (high => beta)")

# 5. Cost break-even
print("\n5) Cost sweep (long-only net of cost):")
for c in [0,5,10,20,30,50,75,100]:
    m=mom_long(px,k=3,cost=c/1e4).reindex(idx).dropna()
    t=m.mean()/m.std()*np.sqrt(len(m))
    print(f"   {c:>3}bp: {m.mean()*1e4:+.1f}bp (t={t:.2f})")

# 6. Placebo: shuffle the ranking
rng=np.random.default_rng(0)
past_sh=past.copy(); past_sh[:]=rng.permutation(past_sh.values, axis=1)
mom_p=pd.Series([fwd.loc[d].reindex(past_sh.loc[d].nlargest(3).index).mean() for d in past.index if len(past_sh.loc[d].dropna())>=6]).dropna()
print(f"\n6) Placebo (shuffled ranking): {mom_p.mean()*1e4:+.1f}bp  (should ~0)")

# 7. Leave-one-coin-out concentration
print("\n7) Leave-one-coin-out (alpha vs basket, net20bp):")
for s in SYMS:
    sub=px.drop(columns=[s]); sub=sub[sub.notna().sum(axis=1)>=6]
    p=sub.pct_change(L); f=sub.pct_change(H).shift(-H)
    rows=[]
    for d in p.index:
        r=p.loc[d].dropna()
        if len(r)<6: continue
        rows.append(f.loc[d].reindex(r.nlargest(3).index).mean()-0.002)
    m=pd.Series(rows); b=f.mean(axis=1).dropna()
    i=m.index.intersection(b.index) if hasattr(m,'index') else None
    print(f"   drop {s.replace('USDT',''):>5}: alpha {m.mean()*1e4:+.1f}bp")

# 8. Per-year walk-forward
print("\n8) Per-year long-only momentum net20bp (vs basket):")
for yr in range(2019,2027):
    y=mom[mom.index.year==yr]; b=basket[basket.index.year==yr]
    if len(y)>20:
        print(f"   {yr}: mom {y.mean()*1e4:+.0f}bp | basket {b.mean()*1e4:+.0f}bp | alpha {(y.mean()-b.mean())*1e4:+.0f}bp | n={len(y)}")
