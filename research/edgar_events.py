import json, time, urllib.request, boto3, io, pandas as pd

H={'User-Agent':'PCnslt Research info@pcnslt.com'}
BUCKET='trading-datalake-920641308584'
s3=boto3.client('s3',region_name='us-east-1')

def get(url):
    req=urllib.request.Request(url,headers=H)
    return json.loads(urllib.request.urlopen(req,timeout=30).read())

# ticker -> CIK
tk=get('https://www.sec.gov/files/company_tickers.json')
t2c={v['ticker']:str(v['cik_str']).zfill(10) for v in tk.values()}

SYMS=['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX','INTC','MU','PLTR','ORCL','CRM','COST','UNH','LLY','JPM','V']
rows=[]
for sym in SYMS:
    cik=t2c.get(sym)
    if not cik: continue
    try:
        d=get(f'https://data.sec.gov/submissions/CIK{cik}.json')
        rec=d['filings']['recent']
        df=pd.DataFrame({k:rec[k] for k in ['form','filingDate','accessionNumber','reportDate']})
        k8=df[df['form']=='8-K']
        for _,r in k8.iterrows():
            rows.append({'ticker':sym,'cik':cik,'form':r['form'],
                         'filingDate':r['filingDate'],'accession':r['accessionNumber'],
                         'reportDate':r['reportDate']})
    except Exception as e:
        pass
    time.sleep(0.15)
ev=pd.DataFrame(rows)
print(f'8-K events: {len(ev)} across {ev.ticker.nunique()} tickers')
print(ev.groupby('ticker').size().head(10).to_string())
# save to S3
buf=io.BytesIO(); ev.to_parquet(buf)
s3.put_object(Bucket=BUCKET,Key='research/edgar_8k_events.parquet',Body=buf.getvalue())
print('saved to S3 research/edgar_8k_events.parquet')
