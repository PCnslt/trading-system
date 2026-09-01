import boto3, json, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','AVAXUSDT','LINKUSDT','LTCUSDT','BCHUSDT','ADAUSDT','DOTUSDT','UNIUSDT','AAVEUSDT']

def load(s):
    d=json.loads(s3.get_object(Bucket=BUCKET, Key=f'crypto-hist/{s}/daily.json')['Body'].read())['bars']
    df=pd.DataFrame(d); df['date']=pd.to_datetime(df['date']); df=df.set_index('date')
    return df['close']

px=pd.DataFrame({s:load(s) for s in SYMS}).ffill()
px=px[px.notna().sum(axis=1)>=6]
COST=0.002  # 20bp round trip (0.1% taker x2)

print(f"{'L':>2} {'H':>2} {'longOnly net':>14} {'t':>6} {'PF':>6} {'win%':>6} {'n':>6}")
for L in [3,7,14]:
    for H in [3,7]:
        past=px.pct_change(L); fwd=px.pct_change(H).shift(-H)
        rows=[]
        for d in past.index:
            r=past.loc[d].dropna()
            if len(r)<6: continue
            top=r.nlargest(3).index
            f=fwd.loc[d].reindex(top).dropna()
            if len(f)==0: continue
            rows.append((f.mean(), f))
        if not rows: continue
        R=pd.DataFrame([x[0] for x in rows], columns=['r'])
        net=R['r']-COST
        t=net.mean()/net.std()*np.sqrt(len(net))
        wins=pd.concat([x[1] for x in rows],axis=0)
        pf=wins[wins>0].sum()/abs(wins[wins<0].sum()) if (wins<0).any() else 99
        print(f"{L:>2} {H:>2} {net.mean()*1e4:>+13.1f}bp {t:>6.2f} {pf:>6.2f} {(net>0).mean()*100:>5.1f}% {len(net):>6}")
