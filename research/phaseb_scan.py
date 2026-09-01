import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
P5='ibkr/equities/5min/'

def load5(sym):
    o=s3.get_object(Bucket=BUCKET,Key=P5+sym+'.parquet')['Body'].read()
    df=pd.read_parquet(io.BytesIO(o)); df['date']=pd.to_datetime(df['date'])
    return df.set_index('date').tz_localize(None)

SYMS=['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX','INTC','MU']
frames=[]
for sym in SYMS:
    try: frames.append(load5(sym))
    except: pass
m5=pd.concat(frames)
# resample to 30-min and 60-min returns
r30=m5['close'].resample('30min').last().pct_change().dropna()
r60=m5['close'].resample('60min').last().pct_change().dropna()

# 1. Intraday momentum/reversal: does past 30-min predict next 30-min?
mom=r30.shift(1); nxt=r30
s=pd.DataFrame({'past':mom,'fut':nxt}).dropna()
s['past_dir']=np.sign(s['past'])
cont=(s['past_dir']==np.sign(s['fut'])).mean()
print(f'[30m momentum] P(same sign next 30m) = {cont:.3f}  n={len(s)}')
# conditional: after |past|>0.5%
big=s[s['past'].abs()>0.005]
if len(big)>20:
    c=(big['past_dir']==np.sign(big['fut'])).mean()
    print(f'  after |30m|>0.5%: P(continue)={c:.3f}  next-mean={big["fut"].mean()*10000:.1f}bp  n={len(big)}')

# 2. Volatility shock: abnormal 30-min range -> continuation or reversal
rng=(m5['high'].resample('30min').max()/m5['low'].resample('30min').min()-1)
rng_avg=rng.rolling(20).mean()
shock=rng/rng_avg  # >1 = abnormal range
v=pd.DataFrame({'shock':shock,'ret':r30}).dropna()
vs=v[v['shock']>2.0]
if len(vs)>20:
    cont_v=(np.sign(vs['ret']).shift(1)==np.sign(vs['ret'])).mean()
    print(f'\n[vol shock >2x] next-30m mean={vs["ret"].mean()*10000:.1f}bp  n={len(vs)}')

# 3. Opening range breakout: first 30-min high/low -> breakout continuation
o30=m5['high'].resample('D').first()  # placeholder; proper ORB below
# time-of-day: first 30-min return vs rest of day
day_open=m5['open'].resample('D').first()
first30=m5['close'].resample('D').first()  # approx first bar close
day_close=m5['close'].resample('D').last()
first_ret=first30/day_open-1
rest_ret=day_close/first30-1
tod=pd.DataFrame({'first':first_ret,'rest':rest_ret}).dropna()
cont_tod=(np.sign(tod['first'])==np.sign(tod['rest'])).mean()
print(f'\n[time-of-day] P(rest-of-day same dir as first-5m) = {cont_tod:.3f}  n={len(tod)}')
print(f'  first-5m mean={tod["first"].mean()*10000:.1f}bp  rest mean={tod["rest"].mean()*10000:.1f}bp')
