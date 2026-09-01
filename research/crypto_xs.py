import boto3, io, json, pandas as pd, numpy as np

s3 = boto3.client('s3', region_name='us-east-1'); BUCKET='trading-datalake-920641308584'
SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','AVAXUSDT','LINKUSDT','LTCUSDT','BCHUSDT','ADAUSDT','DOTUSDT','UNIUSDT','AAVEUSDT']

def load(s):
    o=s3.get_object(Bucket=BUCKET, Key=f'crypto-hist/{s}/daily.json')['Body'].read()
    d=json.loads(o)['bars']
    df=pd.DataFrame(d); df['date']=pd.to_datetime(df['date']); df=df.set_index('date')
    return df['close']

closes={s:load(s) for s in SYMS}
px=pd.DataFrame(closes).ffill().dropna(how='all')
# restrict to window where >=6 coins have data
px=px[px.notna().sum(axis=1)>=6]

for L in [3,7,14]:   # lookback days
    for H in [1,3,7]: # hold days
        past=px.pct_change(L)           # past L-day return
        fwd=px.pct_change(H).shift(-H)  # forward H-day return
        rows=[]
        for d in past.index:
            r=past.loc[d].dropna()
            if len(r)<6: continue
            top=r.nlargest(3).index      # winners
            bot=r.nsmallest(3).index     # losers
            fm=fwd.loc[d].dropna()
            m=fm.reindex(top).mean(); l=fm.reindex(bot).mean()
            if pd.notna(m) and pd.notna(l): rows.append((m-l,m,l))
        if not rows: continue
        R=pd.DataFrame(rows,columns=['mom','mom_win','mom_lose'])
        t_mom=R['mom'].mean()/R['mom'].std()*np.sqrt(len(R))
        t_rev=-R['mom'].mean()/R['mom'].std()*np.sqrt(len(R))
        print(f"L{L} H{H}: MOM(long-short) {R['mom'].mean()*1e4:+.1f}bp (t={t_mom:.2f}, PF_mom_wins={(R['mom_win']>0).mean():.2f}) | REV { -R['mom'].mean()*1e4:+.1f}bp (t={t_rev:.2f}) n={len(R)}")
