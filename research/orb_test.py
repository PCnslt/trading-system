import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'
P5 = 'ibkr/equities/5min/'

def load5(sym):
    d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=P5+sym+'.parquet')['Body'].read()))
    d['date'] = pd.to_datetime(d['date']); d = d.set_index('date'); d.index = d.index.tz_localize(None)
    return d[['open','high','low','close','volume']]

rows = []
for sym in ['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX',
            'INTC','MU','PLTR','ORCL','CRM','COST','UNH','LLY','JPM','V',
            'MA','WMT','HD','PG','JNJ','BAC','XOM','CVX','KO','PEP',
            'DIS','NFLX','ADBE','QCOM','TXN','CSCO','ABT','TMO','MRK','PFE']:
    try:
        m5 = load5(sym)
    except Exception:
        continue
    dg = m5.groupby(m5.index.date)
    for day, g in dg:
        if len(g) < 60:  # need a full session
            continue
        op = g.iloc[0]
        first30 = g[g.index < g.index[0] + pd.Timedelta(minutes=30)]
        if len(first30) < 5:
            continue
        rng_hi = first30['high'].max(); rng_lo = first30['low'].min()
        # breakout above range high after 30 min
        after = g[g.index >= g.index[0] + pd.Timedelta(minutes=30)]
        if len(after) < 5:
            continue
        entry = None
        for ts, bar in after.iterrows():
            if bar['high'] > rng_hi:  # breakout up
                entry = min(bar['close'], rng_hi + 0.01)  # conservative: enter at range high
                break
        if entry is None:
            continue
        close = g['close'].iloc[-1]
        vol_confirm = after['volume'].mean() > first30['volume'].mean() * 1.2
        ret = close/entry - 1
        rows.append(dict(sym=sym, day=day, ret=ret*10000, vol_confirm=vol_confirm))

df = pd.DataFrame(rows)
print(f"ORB long (break above first-30m high): {len(df)} trades")
print(f"  all:          mean={df['ret'].mean():+.1f}bp  med={df['ret'].median():+.1f}bp  win={(df['ret']>0).mean():.1%}")
print(f"  vol-confirmed: mean={df[df.vol_confirm]['ret'].mean():+.1f}bp  n={(df.vol_confirm).sum()}  win={(df[df.vol_confirm]['ret']>0).mean():.1%}")
print(f"  no-vol:        mean={df[~df.vol_confirm]['ret'].mean():+.1f}bp  n={(~df.vol_confirm).sum()}")
# per-day clustered mean
dmean = df.groupby('day')['ret'].mean()
print(f"  day-clustered t = {dmean.mean()/dmean.std()*np.sqrt(len(dmean)):+.2f}  (n_days={len(dmean)})")
