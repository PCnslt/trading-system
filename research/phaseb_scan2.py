import boto3, io, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
P5='ibkr/equities/5min/'
def load5(sym):
    o=s3.get_object(Bucket=BUCKET,Key=P5+sym+'.parquet')['Body'].read()
    df=pd.read_parquet(io.BytesIO(o)); df['date']=pd.to_datetime(df['date'])
    return df.set_index('date').tz_localize(None)
SYMS=['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX','INTC','MU']

# per-symbol 30-min momentum
cont=[]; big_cont=[]; big_mean=[]
tod=[]; first_ret=[]; rest_ret=[]
for sym in SYMS:
    try: m5=load5(sym)
    except: continue
    c=m5['close']
    r30=c.resample('30min').last().pct_change().dropna()
    past=r30.shift(1); fut=r30
    s=pd.DataFrame({'past':past,'fut':fut}).dropna()
    cont.append((np.sign(s['past'])==np.sign(s['fut'])).mean())
    big=s[s['past'].abs()>0.005]
    if len(big)>15:
        big_cont.append((np.sign(big['past'])==np.sign(big['fut'])).mean())
        big_mean.append(big['fut'].mean()*10000)
    # time-of-day: first 5-min close -> last close (per symbol)
    o=m5['open'].resample('D').first(); cl=m5['close'].resample('D').last()
    f5=m5['close'].resample('D').first()
    fr=(f5/o-1); rr=(cl/f5-1)
    d=pd.DataFrame({'first':fr,'rest':rr}).dropna()
    tod.append((np.sign(d['first'])==np.sign(d['rest'])).mean())
    first_ret.append(d['first'].mean()*10000); rest_ret.append(d['rest'].mean()*10000)

print(f'[30m momentum] P(continue) = {np.mean(cont):.3f}  (per-symbol avg)')
print(f'[after |30m|>0.5%] P(continue) = {np.mean(big_cont):.3f}  next-mean={np.mean(big_mean):.1f}bp')
print(f'[time-of-day] P(rest same dir as first-5m) = {np.mean(tod):.3f}')
print(f'  first-5m mean={np.mean(first_ret):.1f}bp  rest mean={np.mean(rest_ret):.1f}bp')
