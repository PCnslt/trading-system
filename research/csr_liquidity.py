import boto3, io, pandas as pd, numpy as np, re

# SUPERSEDED by research/atomics/full_universe_strategies.py. Kept as the weekly
# cross-sectional reversal liquidity-tier diagnostic. Defects fixed 2026-09-09:
#   1) LOOK-AHEAD: dollar-volume filter was the FULL-PERIOD average
#      dvol[s]=(close*volume).mean(), back-applied to every rebalance date (a 2006
#      trade was classified "liquid" using 2006-2026 volume). Now trailing-21d
#      median dollar-volume at each rebalance (point-in-time).
#   2) LOOK-AHEAD: price tier used px[c].iloc[-1] (the LAST/current price). Now the
#      price at each rebalance date.
#   3) split/reverse-split gaps neutralized (single-day |ret|>40% zeroed -> cumprod
#      adjusted close) -- was past5/fwd on raw split-unadjusted closes.
#   4) sub-$1 floor + listing-warmup gating on the forward label.

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
r=s3.list_objects_v2(Bucket=BUCKET, Prefix='ibkr/equities/daily/', MaxKeys=400)
keys=[o['Key'] for o in r.get('Contents',[]) if o['Key'].endswith('.parquet')]
def is_common(s): return not re.search(r'[-.][WURPS]A?B?$|[-.]U$|PR[ABCDEFG]?$|[-.]WS$|[-.]WT$', s)
syms=sorted(set(k.split('/')[-1].replace('.parquet','') for k in keys))
syms=[s for s in syms if is_common(s)]
SPLIT=0.40

closes={}; vols={}
for s in syms:
    try:
        b=s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{s}.parquet')['Body'].read()
        d=pd.read_parquet(io.BytesIO(b)); d.columns=[c.lower() for c in d.columns]
        d['date']=pd.to_datetime(d['date'])
        d=d.dropna(subset=['close']); d=d[d['close']>0]
        d=d.set_index('date').sort_index()
        closes[s]=d['close']; vols[s]=d['volume']
    except Exception: pass
px=pd.DataFrame(closes).sort_index()
vv=pd.DataFrame(vols).sort_index()
Cv=np.array(px.to_numpy(np.float64), copy=True); Cv[Cv<=0]=np.nan
Vv=np.array(vv.to_numpy(np.float64), copy=True); Vv[~(Vv>0)]=np.nan
has_data=~np.isnan(Cv)
R=Cv[1:]/Cv[:-1]-1.0
R=np.where(np.abs(R)>SPLIT, 0.0, R); R=np.where(np.isnan(R), 0.0, R)
adj=np.empty(Cv.shape); adj[0]=1.0; adj[1:]=np.cumprod(1.0+R, axis=0)
adj=pd.DataFrame(adj, index=px.index, columns=px.columns)
raw=pd.DataFrame(np.where(has_data, Cv, np.nan), index=px.index, columns=px.columns)
# trailing-21d median dollar volume, point-in-time (NOT full-period average)
dvol_panel=(raw*vv).rolling(21, min_periods=5).median()

past5=adj/adj.shift(5)-1.0; fwd=adj.shift(-5)/adj-1.0; rank=past5.rank(axis=1,pct=True)
hd5=raw.shift(-5).notna()

def run(mask_at, label):
    rows=[]
    for d in px.index[::5]:
        m=mask_at(d)
        r=rank.loc[d][m]
        lo=r[r<=0.1].index
        if len(lo)<3: continue
        rows.append(fwd.loc[d,lo].mean())
    lr=pd.Series(rows).dropna()
    t=lr.mean()/(lr.std()/np.sqrt(len(lr)))
    print(f'{label:46s}: n={len(lr):4d} net(50bp)={lr.mean()*1e4-50:+.1f}bp t={t:.2f}')

def m_all(d):   return raw.loc[d].notna() & hd5.loc[d] & (raw.loc[d]>=1.0)
def m_p5(d):    return m_all(d) & (raw.loc[d]>=5)
def m_p10(d):   return m_all(d) & (raw.loc[d]>=10)
def m_dv2(d):   return m_all(d) & (dvol_panel.loc[d]>=2e6)
def m_dv10(d):  return m_all(d) & (dvol_panel.loc[d]>=10e6)
def m_dv50(d):  return m_all(d) & (dvol_panel.loc[d]>=50e6)
def m_p10d10(d): return m_all(d) & (raw.loc[d]>=10) & (dvol_panel.loc[d]>=10e6)

run(m_all, 'ALL common stocks, >=$1 (floor, split-neutral, warmup)')
run(m_p5, 'price >= $5 (at rebalance)')
run(m_p10, 'price >= $10 (at rebalance)')
run(m_dv2, 'trailing-21d median $vol >= $2M/day')
run(m_dv10, 'trailing-21d median $vol >= $10M/day')
run(m_dv50, 'trailing-21d median $vol >= $50M/day (large-cap)')
run(m_p10d10, 'price>=10 AND trailing $vol>=10M')
