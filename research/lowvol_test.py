import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'
px = {}
for o in s3.list_objects_v2(Bucket=B, Prefix='ibkr/equities/daily/').get('Contents', []):
    try:
        d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read()))
        d['date'] = pd.to_datetime(d['date']); d = d.set_index('date')
        s = d['close'].dropna()
        if len(s) > 500: px[o['Key'].split('/')[-1].replace('.parquet','')] = s
    except Exception: pass
print(f"symbols: {len(px)}")

ret = pd.DataFrame({k: v.pct_change() for k, v in px.items()}).sort_index()
# month-end rebalance dates
me = ret.resample('ME').last().index
results = []
for i in range(1, len(me)-1):
    t0, t1 = me[i], me[i+1]
    vol = ret.loc[:t0].tail(21).std()  # trailing 21-day vol at t0
    vol = vol.dropna()
    if len(vol) < 40: continue
    q = vol.quantile([0.2, 0.8])
    low = vol[vol <= q.iloc[0]].index; high = vol[vol >= q.iloc[1]].index
    fwd = ret.loc[t0:t1].dropna(how='all')
    if len(fwd) < 3: continue
    lr = fwd[low].mean(axis=1).add(1).prod() - 1
    hr = fwd[high].mean(axis=1).add(1).prod() - 1
    mr = fwd.mean(axis=1).add(1).prod() - 1
    results.append((t0, lr, hr, mr))

r = pd.DataFrame(results, columns=['m','low','high','mkt']).dropna()
n = len(r)
print(f"months: {n}  ({r.m.min().date()}..{r.m.max().date()})")
def stat(s): return s.mean()*1e4, s.mean()/s.std()*np.sqrt(n)
for col, nm in [('low','LOW-VOL'),('high','HIGH-VOL'),('mkt','MARKET-EW')]:
    m, t = stat(r[col]); print(f"{nm}: {m:+.1f}bp/mo  t={t:+.1f}")
spread = r['low'] - r['high']; m, t = stat(spread)
print(f"LOW-HIGH spread: {m:+.1f}bp/mo  t={t:+.1f}")
alpha = r['low'] - r['mkt']; m, t = stat(alpha)
print(f"LOW-VOL alpha vs EW: {m:+.1f}bp/mo  t={t:+.1f}")
# subperiods
for a,b in [(0,n//3),(n//3,2*n//3),(2*n//3,n)]:
    s=r['low'].iloc[a:b]
    print(f"  low-vol {r.m.iloc[a].year}-{r.m.iloc[b-1].year}: {s.mean()*1e4:+.1f}bp/mo")
