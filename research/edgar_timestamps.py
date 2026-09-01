import json, time, urllib.request, xml.etree.ElementTree as ET, io, boto3, pandas as pd, re

H={'User-Agent':'PCnslt Research info@pcnslt.com'}
BUCKET='trading-datalake-920641308584'
s3=boto3.client('s3',region_name='us-east-1')

def get(url):
    req=urllib.request.Request(url,headers=H)
    return urllib.request.urlopen(req,timeout=30).read()

tk=get('https://www.sec.gov/files/company_tickers.json')
t2c={v['ticker']:str(v['cik_str']).zfill(10) for v in json.loads(tk.decode()).values()}

SYMS=['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX','INTC','MU','PLTR','ORCL','CRM','COST','UNH','LLY','JPM','V']
rows=[]
for sym in SYMS:
    cik=t2c.get(sym)
    if not cik: continue
    url=f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=100&output=atom'
    try:
        root=ET.fromstring(get(url))
    except Exception:
        continue
    for e in root.iter('{http://www.w3.org/2005/Atom}entry'):
        acc=filing=items=updated=None
        for c in e.iter('{http://www.w3.org/2005/Atom}content'):
            pass
        # walk all descendants for the fields
        for el in e.iter():
            tag=el.tag.split('}')[-1]
            if tag=='accession-number': acc=el.text
            elif tag=='filing-date': filing=el.text
            elif tag=='items-desc': items=el.text
            elif tag=='updated': updated=el.text
        rows.append({'ticker':sym,'cik':cik,'accession':acc,'filing_date':filing,
                     'items':items,'acceptance':updated})
    time.sleep(0.2)

ev=pd.DataFrame(rows)
ev['acceptance']=pd.to_datetime(ev['acceptance'],errors='coerce',utc=True)
ev=ev.dropna(subset=['acceptance'])
# ET session + during/after hours
et=ev['acceptance'].dt.tz_convert('America/New_York')
ev['hour_et']=et.dt.hour+et.dt.minute/60
print(f'events with exact timestamp: {len(ev)}')
print('hour distribution (ET):')
print(et.dt.hour.value_counts().sort_index().to_string())
print('\nitem-type sample (items-desc):')
print(ev['items'].value_counts().head(12).to_string())
buf=io.BytesIO(); ev.to_parquet(buf)
s3.put_object(Bucket=BUCKET,Key='research/edgar_8k_timestamped.parquet',Body=buf.getvalue())
print('\nsaved research/edgar_8k_timestamped.parquet')
