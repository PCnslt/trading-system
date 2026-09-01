import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'
P5 = 'ibkr/equities/5min/'
SYMS = ['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX',
        'INTC','MU','PLTR','ORCL','CRM','COST','UNH','LLY','JPM','V',
        'MA','WMT','HD','PG','JNJ','BAC','XOM','CVX','KO','PEP','DIS','ADBE','QCOM','TXN','CSCO']

def load5(sym):
    d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=P5+sym+'.parquet')['Body'].read()))
    d['date'] = pd.to_datetime(d['date']); d = d.set_index('date'); d.index = d.index.tz_localize(None)
    return d['close']

close = {}
for s in SYMS:
    try:
        c = load5(s)
        if len(c) > 5000:
            close[s] = c
    except Exception:
        pass

# align on common 5-min grid (use most common timestamps)
rets = pd.DataFrame({s: c.pct_change() for s, c in close.items()}).dropna(how='all')
# keep rows where >= 20 stocks present
rets = rets[rets.count(axis=1) >= 20]

# market = equal-weight (dropna) mean
mkt = rets.mean(axis=1)
mkt_lag = mkt.shift(1)

# For each stock: does lagged MARKET return predict its NEXT return,
# controlling for its OWN lagged return?
out = []
for s in rets.columns:
    r = rets[s]
    df = pd.DataFrame({'r': r, 'r_own_lag': r.shift(1), 'mkt_lag': mkt_lag}).dropna()
    if len(df) < 3000:
        continue
    # simple conditional: next return when market went up vs down (lagged)
    up = df[df.mkt_lag > 0]['r']; dn = df[df.mkt_lag <= 0]['r']
    out.append(dict(sym=s, up_mean=up.mean()*1e4, dn_mean=dn.mean()*1e4,
                    spread=(up.mean()-dn.mean())*1e4, n=len(df)))

dfo = pd.DataFrame(out)
print(f"market(EW) lead/lag: {len(dfo)} stocks")
print(f"  mean next-ret after mkt UP:   {dfo.up_mean.mean():+.2f}bp")
print(f"  mean next-ret after mkt DOWN: {dfo.dn_mean.mean():+.2f}bp")
print(f"  mean spread (up-down):        {dfo.spread.mean():+.2f}bp  (t={dfo.spread.mean()/dfo.spread.std()*np.sqrt(len(dfo)):.2f})")
print(f"  stocks with positive spread:  {(dfo.spread>0).mean():.0%}")

# does lagged market predict next AFTER controlling for own autocorr? (pooled reg)
big = []
for s in rets.columns:
    r = rets[s]
    d = pd.DataFrame({'r': r, 'own': r.shift(1), 'mkt': mkt.shift(1)}).dropna()
    d['sym'] = s; big.append(d)
pool = pd.concat(big)
import numpy as np
X = pool[['own','mkt']].values
X = np.column_stack([np.ones(len(X)), X])
y = pool['r'].values
beta, *_ = np.linalg.lstsq(X, y, rcond=None)
print(f"\npooled regression: next_ret = {beta[0]*1e4:+.2f}bp + {beta[1]*1e4:+.2f}bp*own_lag + {beta[2]*1e4:+.2f}bp*mkt_lag")
print(f"  -> lagged MARKET coefficient: {beta[2]*1e4:+.3f}bp per 1bp market move")
