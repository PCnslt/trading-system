import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'
px = {}
for o in s3.list_objects_v2(Bucket=B, Prefix='ibkr/equities/daily/')['Contents']:
    sym = o['Key'].split('/')[-1].split('.')[0]
    d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read()))
    d['date'] = pd.to_datetime(d['date'])
    px[sym] = d.set_index('date')['close']

ret = pd.DataFrame({s: p.pct_change() for s, p in px.items()}).dropna(how='all')
mkt = ret.mean(axis=1)  # equal-weight market proxy (1000 stocks)

# volatility-managed: scale = target_vol / trailing realized vol, capped at 1
rv = mkt.rolling(22).std() * np.sqrt(252)
target = 0.15  # 15% annualized target vol
scale = (target / rv).clip(upper=1.0)
strat = (scale.shift(1) * mkt).fillna(0)

def stats(r):
    r = r.dropna()
    ann = r.mean()*252; vol = r.std()*np.sqrt(252); sharpe = ann/vol if vol>0 else 0
    dd = (1+r).cumprod(); mdd = (dd/dd.cummax()-1).min()
    return ann, vol, sharpe, mdd

print("=== BUY-AND-HOLD vs VOL-MANAGED (1000-stock EW, 2006-2026) ===")
for name, r in [('buy-hold', mkt), ('vol-managed', strat)]:
    a, v, s, dd = stats(r)
    print(f"{name:12s}: ann={a*100:6.2f}%  vol={v*100:6.2f}%  Sharpe={s:5.2f}  maxDD={dd*100:6.2f}%")

# subperiods
print("\n=== by subperiod (Sharpe: buy-hold vs vol-managed) ===")
for lo, hi in [('2006','2013'),('2013','2019'),('2019','2026')]:
    b = stats(mkt.loc[lo:hi])[2]; v = stats(strat.loc[lo:hi])[2]
    print(f"{lo}-{hi}: buy-hold Sharpe={b:5.2f}  vol-managed={v:5.2f}")
