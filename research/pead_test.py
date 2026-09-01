import boto3, io, json, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'

earn = []
for o in s3.list_objects_v2(Bucket=B, Prefix='av/earnings/').get('Contents', []):
    d = json.loads(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read())
    for r in d.get('quarterlyEarnings', []):
        try:
            rep = float(r['reportedEPS']); est = float(r['estimatedEPS'])
        except (TypeError, ValueError):
            continue
        earn.append(dict(symbol=d['symbol'], date=pd.to_datetime(r['reportedDate']),
                         rt=r.get('reportTime',''), rep=rep, est=est))
earn = pd.DataFrame(earn).dropna(subset=['rep','est'])
earn['sue'] = (earn['rep'] - earn['est'])  # normalized by price below
print(f"events {len(earn)}  syms {earn.symbol.nunique()}  {earn.date.min().date()}..{earn.date.max().date()}")

closes = {}
for sym in earn.symbol.unique():
    try:
        d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=f'ibkr/equities/daily/{sym}.parquet')['Body'].read()))
        d['date'] = pd.to_datetime(d['date']); d = d.set_index('date')
        closes[sym] = d['close'].dropna()
    except Exception: pass

# market EW (all daily)
mkt = []
for o in s3.list_objects_v2(Bucket=B, Prefix='ibkr/equities/daily/').get('Contents', []):
    try:
        d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read()))
        d['date'] = pd.to_datetime(d['date']); d = d.set_index('date')
        mkt.append(d['close'].dropna().pct_change())
    except Exception: pass
mkt = pd.concat(mkt, axis=1).mean(axis=1, skipna=True)

# normalize SUE by price at announcement
sues = []
for _, e in earn.iterrows():
    if e.symbol not in closes or e.date not in closes[e.symbol].index: continue
    p = closes[e.symbol].loc[e.date]
    if p <= 0: continue
    sues.append((e.symbol, e.date, e.rt, e.sue / p))
df = pd.DataFrame(sues, columns=['symbol','date','rt','sue'])
df['bucket'] = pd.qcut(df['sue'].rank(method='first'), 5, labels=False)
print(f"SUE-normalized events: {len(df)}")

def run(bucket_vals, hold, label):
    out = []
    for _, e in df[df['bucket'].isin(bucket_vals)].iterrows():
        px = closes[e.symbol]; idx = px.index
        if e.date not in idx: continue
        pos = idx.get_loc(e.date); entry = e.date
        if e.rt == 'post-market':
            if pos+1 >= len(idx): continue
            entry = idx[pos+1]
        if entry not in idx: continue
        ep = idx.get_loc(entry)
        if ep + hold >= len(idx): continue
        out.append((px.iloc[ep+hold]/px.iloc[ep]-1, entry))
    if len(out) < 20: print(f"{label}: n<20"); return
    r = pd.DataFrame(out, columns=['ret','edate']).set_index('edate')
    mr = mkt.reindex(r.index).fillna(0)
    resid = r['ret'] - mr
    dm = resid.groupby(level=0).mean()
    t = dm.mean()/dm.std()*np.sqrt(len(dm))
    print(f"{label}: n={len(r)} gross {r['ret'].mean()*1e4:+.1f}bp  mkt-adj {resid.mean()*1e4:+.1f}bp  t(clustered {len(dm)}d)={t:+.1f}  win {(r['ret']>0).mean()*100:.0f}%")

for h in (20, 40, 60):
    run([4], h, f"TOP-Q {h}d")
    run([0], h, f"BOT-Q {h}d")
