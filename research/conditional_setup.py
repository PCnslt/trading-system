import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'
P5 = 'ibkr/equities/5min/'
SYMS = ['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX',
        'INTC','MU','PLTR','ORCL','CRM','COST','UNH','LLY','JPM','V','MA','WMT','HD',
        'PG','JNJ','BAC','XOM','CVX','KO','PEP','DIS','ADBE','QCOM','TXN','CSCO']

def load5(sym):
    d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=P5+sym+'.parquet')['Body'].read()))
    d['date'] = pd.to_datetime(d['date']); d = d.set_index('date'); d.index = d.index.tz_localize(None)
    return d

# build wide 30-min returns per symbol
r30 = {}
for s in SYMS:
    try:
        d = load5(s)
        if len(d) > 5000:
            r = d['close'].resample('30min').last().pct_change()
            r30[s] = r[r.notna()]
    except Exception:
        pass

# common timestamp grid (intersection)
idx = None
for s, r in r30.items():
    idx = r.index if idx is None else idx.intersection(r.index)
R = pd.DataFrame({s: r30[s].reindex(idx) for s in r30})
R = R[R.count(axis=1) >= 20]

mkt = R.mean(axis=1)
idio = R.sub(mkt, axis=0)
idio_vol = idio.rolling(20).std()
z = idio / idio_vol.replace(0, np.nan)
nxt = idio.shift(-1)

# volume
V = pd.DataFrame({s: load5(s)['volume'].resample('30min').sum().reindex(idx) for s in r30})
tod = idx.time
vol_base = V.groupby(tod).transform('median')
vr = V / vol_base.replace(0, np.nan)

# flatten
zs = z.stack().rename('z'); vs = vr.stack().rename('vr'); ns = nxt.stack().rename('nxt')
ms = pd.Series(mkt, index=idx); ms = pd.DataFrame({s: ms for s in R.columns}).stack().rename('mkt')
L = pd.concat([zs, vs, ns, ms], axis=1).dropna(subset=['z','vr','nxt'])

def report(name, m):
    sub = L[m]; n = len(sub)
    if n < 30:
        print(f'{name:46s}: n={n} (too few)'); return
    x = sub['nxt']; rev = (np.sign(x) != np.sign(sub['z'])).mean()
    print(f'{name:46s}: n={n:5d} P(up)={(x>0).mean():.1%} P(rev)={rev:.1%} '
          f'mean={x.mean()*1e4:+.1f}bp P(|nxt|>0.5%)={(x.abs()>0.005).mean():.1%}')

print('=== conditional extreme setups (30-min, market-neutral) ===')
report('UNCONDITIONAL', pd.Series(True, index=L.index))
report('|z|>2', L['z'].abs() > 2)
report('|z|>2.5', L['z'].abs() > 2.5)
report('|z|>2.5 & vol>2x', (L['z'].abs() > 2.5) & (L['vr'] > 2))
ms = mkt.std()
report('|z|>2.5 & vol>2x & mkt flat', (L['z'].abs() > 2.5) & (L['vr'] > 2) & (L['mkt'].abs() < ms))
