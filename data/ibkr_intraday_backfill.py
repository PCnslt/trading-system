import time, boto3, pandas as pd
from ib_insync import IB, Stock, util

SYMS=['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX','INTC','MU','PLTR','ORCL','CRM','COST','UNH','LLY','V','MA','JPM','XOM','JNJ','WMT','PG','HD','KO','PEP','TMO','ABT','CSCO','ADBE','QCOM','TXN','ACN','NKE','MCD','DIS','BA','GE']
BUCKET='trading-datalake-920641308584'; REGION='us-east-1'
s3=boto3.client('s3',region_name=REGION)

ib=IB(); ib.connect('127.0.0.1',4001,clientId=80,timeout=20)

def fetch_5min(sym, days=400):
    c=Stock(sym,'SMART','USD')
    allbars=[]
    end=''
    for _ in range(8):
        b=ib.reqHistoricalData(c, end or '', '1 M', '5 mins', 'TRADES', useRTH=True, formatDate=1)
        if not b: break
        allbars=b+allbars
        # formatDate=1 -> .date is a datetime; endDateTime wants 'YYYYMMDD HH:MM:SS'
        end=b[0].date.strftime('%Y%m%d %H:%M:%S')
        time.sleep(0.5)
        if len(b)<1000: break
    if not allbars: return None
    return util.df(allbars)

ok=0
for sym in SYMS:
    try:
        df=fetch_5min(sym)
        if df is not None and len(df)>1000:
            df['date']=pd.to_datetime(df['date'])
            buf=df.to_parquet(index=False)
            s3.put_object(Bucket=BUCKET, Key=f'ibkr/equities/5min/{sym}.parquet', Body=buf)
            ok+=1
            print(f"{sym}: {len(df)} bars {df['date'].min().date()}..{df['date'].max().date()}")
        else:
            print(f"{sym}: insufficient")
    except Exception as e:
        print(f"{sym}: fail {type(e).__name__}")
    time.sleep(0.3)
ib.disconnect()
print(f"\nDone: {ok}/{len(SYMS)} symbols saved")
