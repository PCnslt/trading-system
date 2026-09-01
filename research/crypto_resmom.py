import boto3, json, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','AVAXUSDT','LINKUSDT','LTCUSDT','BCHUSDT','ADAUSDT','DOTUSDT','UNIUSDT','AAVEUSDT']

def load(s):
    d=json.loads(s3.get_object(Bucket=BUCKET, Key=f'crypto-hist/{s}/daily.json')['Body'].read())['bars']
    df=pd.DataFrame(d); df['date']=pd.to_datetime(df['date']); df=df.set_index('date')
    return df['close']

px=pd.DataFrame({s:load(s) for s in SYMS}).ffill()
px=px[px.notna().sum(axis=1)>=6]
ret=px.pct_change()

# rolling beta to BTC (60d) -> residual return
BTC=ret['BTCUSDT']
beta=ret.rolling(60).cov(BTC).div(BTC.rolling(60).var(), axis=0)
resid=ret.sub(beta.mul(BTC, axis=0))

print("Residual momentum (residual after BTC beta): long coins with positive past residual")
print(f"{'L':>2} {'H':>2} {'resMom net':>11} {'basket':>9} {'ALPHA':>9} {'t':>7}")
for L in [7,14,30]:
    for H in [7,14]:
        past_res=resid.rolling(L).sum()      # cumulative residual over L days
        fwd=ret.shift(-H).rolling(H).sum()   # forward H-day TOTAL return
        sig=(past_res>0).astype(float)
        ts=(sig*fwd).mean(axis=1); flip=(sig.diff().abs()).mean(axis=1); cost=flip*0.002
        ts=ts-cost; bk=fwd.mean(axis=1)
        d=pd.DataFrame({'ts':ts,'bk':bk}).dropna()
        a=d['ts']-d['bk']
        t=a.mean()/a.std()*np.sqrt(len(a))
        print(f"{L:>2} {H:>2} {d['ts'].mean()*1e4:>+10.1f}bp {d['bk'].mean()*1e4:>+8.1f}bp {a.mean()*1e4:>+8.1f}bp {t:>6.2f}")

# Compare: RAW momentum alpha (already known ~ -27bp at L14/H7)
print("\n(raw momentum L14/H7 alpha was ~-27bp — residual should differ if beta is the issue)")
