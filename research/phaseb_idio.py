import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
P5='ibkr/equities/5min/'
def load5(sym):
    o=s3.get_object(Bucket=BUCKET,Key=P5+sym+'.parquet')['Body'].read()
    df=pd.read_parquet(io.BytesIO(o)); df['date']=pd.to_datetime(df['date'])
    return df.set_index('date').tz_localize(None)

# discover completed symbols
import subprocess
done=[l.split(':')[0].strip() for l in open('/tmp/intraday_backfill.log') if 'bars 2026' in l]
print(f'symbols: {len(done)}')

# 30-min returns per symbol, then build market (equal-weight) panel
rets={}
for sym in done:
    try:
        m5=load5(sym)
        r=m5['close'].resample('30min').last().pct_change()
        rets[sym]=r
    except: pass
panel=pd.DataFrame(rets)
mkt=panel.mean(axis=1)  # equal-weight market proxy
idio=panel.sub(mkt,axis=0)  # idiosyncratic return

# idiosyncratic shock: |idio|>0.5% -> does idiosyncratic continue or revert?
shock=idio.shift(1)
nxt=idio
s=pd.DataFrame({'past':shock.stack(),'fut':nxt.stack()}).dropna()
s=s[s['past'].abs()>0.005]
cont=(np.sign(s['past'])==np.sign(s['fut'])).mean()
print(f'\n[idiosyncratic shock |past|>0.5%] P(continue) = {cont:.3f}  n={len(s)}')
print(f'  next-30m idio mean = {s["fut"].mean()*10000:.1f}bp  (positive=continuation, negative=reversal)')

# by direction
for label,sub in [('pos shock',s[s['past']>0]),('neg shock',s[s['past']<0])]:
    m=sub['fut'].mean()*10000
    print(f'  {label}: n={len(sub)} next-mean={m:.1f}bp')
