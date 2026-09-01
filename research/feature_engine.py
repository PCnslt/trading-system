"""Feature engine (Phase 1) + cross-sectional ranking test (Phase 3).

Computes a causal feature vector per 5-min bar per symbol, then tests whether
the cross-section of feature states predicts next-horizon returns better than
chance. All features use only information available at the decision timestamp.
"""
import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'
P5 = 'ibkr/equities/5min/'
def _discover():
    r = s3.list_objects_v2(Bucket=B, Prefix=P5)
    return sorted(o['Key'].split('/')[-1].replace('.parquet','') for o in r.get('Contents',[]))
SYMS = _discover()
print(f"discovered {len(SYMS)} symbols")

def load5(sym):
    d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=f'{P5}{sym}.parquet')['Body'].read()))
    d['date'] = pd.to_datetime(d['date']); d = d.set_index('date').sort_index()
    d.index = d.index.tz_localize(None)
    return d

def features(d):
    c, v = d['close'], d['volume']
    r5 = c.pct_change()
    r15 = c.pct_change(3); r30 = c.pct_change(6)
    # RSI(14) on 5-min closes
    delta = c.diff(); up = delta.clip(lower=0); dn = -delta.clip(upper=0)
    rs = up.rolling(14).mean() / dn.rolling(14).mean()
    rsi = 100 - 100/(1+rs)
    # VWAP distance (running VWAP vs close)
    vwap = (c*v).rolling(30).sum() / v.rolling(30).sum()
    vwap_dist = (c - vwap) / vwap
    # volume ratio vs trailing 30-bar median (time-of-day aware via same-bar rolling)
    vr = v / v.rolling(30).median()
    # realized vol
    rv = r5.rolling(20).std()
    f = pd.DataFrame({'r5':r5,'r15':r15,'r30':r30,'rsi':rsi,'vwap_dist':vwap_dist,
                      'vr':vr,'rv':rv})
    return f

# build features for all symbols
feats = {s: features(load5(s)) for s in SYMS}

# cross-sectional ranks (computed at each timestamp across symbols)
# signal = mean rank of (r30 momentum, -vwap_dist, -rsi-extreme, vr)  -- simple composite
def cs_signal(feats, t):
    vals = {}
    for s, f in feats.items():
        if t not in f.index: continue
        row = f.loc[t]
        if row.isna().any(): continue
        vals[s] = row
    if len(vals) < 10: return None
    df = pd.DataFrame(vals).T
    # composite signal (higher = more likely to rise): momentum + volume + not-overbought
    sig = (df['r30'].rank()*0.4 + df['vr'].rank()*0.2
           + (100-df['rsi']).rank()*0.2 + (-df['vwap_dist']).rank()*0.2)
    return sig

# evaluate: at each timestamp, rank by signal, measure top/bottom decile next 30m return
rows = []
times = sorted(set.intersection(*[set(f.index) for f in feats.values()]))[::6]  # every 30m
for t in times:
    sig = cs_signal(feats, t)
    if sig is None: continue
    # next 30m return for each symbol
    nxt = {}
    for s in sig.index:
        fi = feats[s].loc[t:]
        if len(fi) < 7: continue
        nxt[s] = fi['r5'].iloc[1:7].sum()  # sum of next 6 five-min bars = ~30m
    if len(nxt) < 10: continue
    nxt = pd.Series(nxt)
    q = sig.rank(pct=True)
    top = nxt[q >= 0.9]; bot = nxt[q <= 0.1]; mid = nxt[(q>0.4)&(q<0.6)]
    rows.append(dict(t=t, top=top.mean(), bot=bot.mean(), mid=mid.mean(),
                     spread=top.mean()-bot.mean(), n_top=len(top)))

res = pd.DataFrame(rows)
print(f"timestamps: {len(res)}, top n={res.n_top.sum()}")
for name, col in [('top decile','top'),('bottom decile','bot'),('mid','mid'),('top-bottom spread','spread')]:
    s = res[col].dropna()
    print(f"{name}: mean {s.mean()*1e4:+.2f}bp, median {s.median()*1e4:+.2f}bp, t={s.mean()/s.std()*np.sqrt(len(s)):.2f} (n={len(s)})")
# long-only top decile, market-adjusted
print(f"\ntop decile P(pos) = {(res.top>0).mean():.3f}  vs mid P(pos) = {(res.mid>0).mean():.3f}")
