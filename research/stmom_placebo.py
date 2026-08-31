import os, io, json
import boto3, pandas as pd, numpy as np

S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'

def load_universe():
    with open('/home/ubuntu/trading-system/research/universe_1500.json') as f:
        u = json.load(f)
    if isinstance(u, dict):
        u = u.get('symbols', u.get('universe', []))
    return [s for s in u if isinstance(s, str)][:300]

def load_close(s):
    try:
        o = S3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{s}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        df['date'] = pd.to_datetime(df['date'])
        return df.set_index('date')['close'].sort_index()
    except Exception:
        return None

syms = load_universe()
closes = {}
for s in syms:
    c = load_close(s)
    if c is not None and len(c) > 250:
        closes[s] = c
print(f'loaded {len(closes)} symbols')

# build a price panel on a common calendar
px = pd.DataFrame({s: c for s, c in closes.items()}).dropna(how='all')
idx = px.index

def forward_ret(sels, d, hold=21):
    j = idx.get_loc(d)
    if j + hold >= len(idx): return None
    dn = idx[j + hold]
    return np.mean([px[s].loc[dn] / px[s].loc[d] - 1.0 for s in sels if s in px.columns])

def run(rank_mode, topn=25, hold=21, rebalance=21, oos_frac=0.30):
    # momentum = return from t-25 to t-5 (skip recent 5)
    mom = px.shift(5) / px.shift(25) - 1.0
    step = rebalance
    reb = idx[step::step]
    split = int(len(reb) * (1 - oos_frac))
    out = {}
    for seg, dates in [('IS', reb[:split]), ('OOS', reb[split:])]:
        rets = []
        for d in dates:
            m = mom.loc[d].dropna()
            if len(m) < 30: continue
            if rank_mode == 'top': sels = m.nlargest(topn).index
            elif rank_mode == 'bottom': sels = m.nsmallest(topn).index
            elif rank_mode == 'random': sels = np.random.choice(m.index, topn, replace=False)
            r = forward_ret(sels, d, hold)
            if r is None: continue
            rets.append(r * 10000)
        out[seg] = np.array(rets)
    return out

np.random.seed(0)
print(f"\n{'rank':>8} | {'OOS':>8} {'win%':>5} {'t':>6} {'n':>4}")
for mode in ['top', 'bottom', 'random']:
    r = run(mode)
    oos = r['OOS']
    t = oos.mean()/oos.std()*np.sqrt(len(oos))
    print(f"{mode:>8} | {oos.mean():>7.1f} {(oos>0).mean()*100:>4.0f}% {t:>6.2f} {len(oos):>4}")

# long-short (top - bottom) — the actual momentum spread
rt = run('top'); rb = run('bottom')
# align
n = min(len(rt['OOS']), len(rb['OOS']))
ls = rt['OOS'][:n] - rb['OOS'][:n]
print(f"\nMOMENTUM LONG-SHORT (top-bottom) OOS: {ls.mean():.1f}bp  win {(ls>0).mean()*100:.0f}%  t {ls.mean()/ls.std()*np.sqrt(n):.2f}  n={n}")
