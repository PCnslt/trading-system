import os, json, boto3, pandas as pd, numpy as np
from ib_insync import IB, Stock, util

ETFS=['SPY','QQQ','IWM','DIA','MDY','XLK','XLF','XLE','XLV','XLY','XLP','XLI','XLB','XLU','XLRE','XLC','SMH','XBI','XRT','KRE']
BUCKET='trading-datalake-920641308584'; REGION='us-east-1'
s3=boto3.client('s3',region_name=REGION)

ib=IB(); ib.connect('127.0.0.1', 4001, clientId=77, timeout=15)
frames={}
for sym in ETFS:
    c=Stock(sym,'SMART','USD')
    try:
        bars=ib.reqHistoricalData(c,'', '5 Y','1 day','TRADES',useRTH=True,formatDate=2)
        if bars:
            df=util.df(bars); df['date']=pd.to_datetime(df['date'])
            frames[sym]=df.set_index('date')['close']
            print(f"{sym}: {len(df)} days")
    except Exception as e:
        print(f"{sym} fail: {e}")
ib.disconnect()

px=pd.DataFrame(frames)
if not px.empty:
    # save to S3
    buf=px.reset_index().to_parquet(index=False)
    s3.put_object(Bucket=BUCKET, Key='ibkr/etfs/daily.parquet', Body=buf)
    print(f"\nSaved {len(px.columns)} ETFs, {len(px)} rows -> ibkr/etfs/daily.parquet")

    # cross-sectional ETF momentum/reversal test
    print(f"\n{'L':>2} {'H':>2} {'XS-MOM alpha':>13} {'t':>6} {'REV alpha':>10}")
    for L in [5,10,20]:
        for H in [5,10,20]:
            past=px.pct_change(L); fwd=px.pct_change(H).shift(-H)
            rows=[]
            for d in past.index:
                r=past.loc[d].dropna()
                if len(r)<6: continue
                top=r.nlargest(3).index; bot=r.nsmallest(3).index
                m=fwd.loc[d].reindex(top).mean(); l=fwd.loc[d].reindex(bot).mean()
                if pd.notna(m) and pd.notna(l): rows.append((m,l))
            if not rows: continue
            R=pd.DataFrame(rows,columns=['w','l']); mom=R['w']-R['l']
            tm=mom.mean()/mom.std()*np.sqrt(len(mom)); tr=-tm
            print(f"{L:>2} {H:>2} {mom.mean()*1e4:>+12.1f}bp {tm:>6.2f} {(-mom.mean()*1e4):>+9.1f}bp")
