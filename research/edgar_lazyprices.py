#!/usr/bin/env python3
"""Lazy Prices (Cohen-Malloy-Nguyen 2020) textual-CHANGE signal — data build.

For each ticker: pull 10-K filing index from SEC submissions API, download the
most recent N 10-K full texts, build 4-gram count vectors, and compute cosine
similarity of each 10-K vs the PRIOR 10-K.  change = 1 - similarity.
Cache raw text locally under research/edgar_text_cache/ so reruns skip network.
Saves events parquet to research/edgar_lazyprices_events.parquet (+ S3).
"""
import json, os, re, time, urllib.request, io, warnings
from collections import Counter
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import boto3

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

H = {'User-Agent': 'PCnslt Research info@pcnslt.com'}
BUCKET = 'trading-datalake-920641308584'
CACHE = os.path.join(os.path.dirname(__file__), 'edgar_text_cache')
os.makedirs(CACHE, exist_ok=True)

# universe: liquid large/mid caps across sectors (small sample, survivorship acknowledged)
SYMS = ['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX',
        'INTC','MU','PLTR','ORCL','CRM','COST','UNH','LLY','JPM','V',
        'WMT','JNJ','PG','KO','PEP','XOM','CVX','BAC','WFC','DIS',
        'NKE','MCD','HD','BA','CAT','GE','IBM','CSCO','QCOM','TXN',
        'ABT','TMO','PFE','MRK','GS','MS','AXP','HON','MMM','UPS']

N_FILINGS = 6  # most recent 10-Ks per name -> N-1 change events each

def getb(url):
    req = urllib.request.Request(url, headers=H)
    return urllib.request.urlopen(req, timeout=90).read()

def getj(url):
    return json.loads(getb(url))

def text_of(html):
    soup = BeautifulSoup(html, 'lxml')
    for t in soup(['script', 'style']):
        t.decompose()
    return re.sub(r'\s+', ' ', soup.get_text(' ')).lower()

def grams4(txt):
    words = re.findall(r"[a-z][a-z0-9'-]*", txt)
    return Counter(tuple(words[i:i+4]) for i in range(len(words)-3))

def cos_sim(v1, v2):
    if not v1 or not v2:
        return np.nan
    common = set(v1) & set(v2)
    num = sum(v1[g] * v2[g] for g in common)
    d1 = np.sqrt(sum(c*c for c in v1.values()))
    d2 = np.sqrt(sum(c*c for c in v2.values()))
    if d1 == 0 or d2 == 0:
        return np.nan
    return num / (d1 * d2)

# ticker -> cik
t2c = {v['ticker']: str(v['cik_str']).zfill(10) for v in getj('https://www.sec.gov/files/company_tickers.json').values()}

rows = []
for sym in SYMS:
    cik = t2c.get(sym)
    if not cik:
        print(f'{sym}: no CIK'); continue
    try:
        d = getj(f'https://data.sec.gov/submissions/CIK{cik}.json')
    except Exception as e:
        print(f'{sym}: submissions fail {e}'); continue
    rec = d['filings']['recent']
    df = pd.DataFrame({k: rec[k] for k in ['form','filingDate','accessionNumber','primaryDocument','reportDate']})
    k10 = df[df['form'] == '10-K'].head(N_FILINGS)
    if len(k10) < 2:
        print(f'{sym}: only {len(k10)} 10-Ks'); continue
    # fetch texts (oldest -> newest order for consecutive pairing)
    texts = []
    for acc, doc in zip(k10['accessionNumber'], k10['primaryDocument']):
        fp = os.path.join(CACHE, f'{cik}_{acc}.txt')
        if os.path.exists(fp) and os.path.getsize(fp) > 1000:
            txt = open(fp, encoding='utf-8').read()
        else:
            try:
                url = f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace("-","")}/{doc}'
                html = getb(url)
                txt = text_of(html)
                open(fp, 'w', encoding='utf-8').write(txt)
            except Exception as e:
                print(f'  {sym} {acc} fetch fail: {e}')
                txt = None
            time.sleep(0.2)
        texts.append(txt)
    # build vectors + consecutive similarity
    vecs = [grams4(t) if t else None for t in texts]
    dates = k10['filingDate'].tolist()
    for i in range(1, len(vecs)):
        sim = cos_sim(vecs[i-1], vecs[i]) if (vecs[i-1] and vecs[i]) else np.nan
        rows.append({'ticker': sym, 'cik': cik,
                     'filing_date': dates[i], 'prev_filing_date': dates[i-1],
                     'accession': k10['accessionNumber'].iloc[i],
                     'sim': sim, 'change': 1.0 - sim if not np.isnan(sim) else np.nan})
    print(f'{sym}: {len(k10)} 10-Ks -> {len(k10)-1} change events (latest sim={rows[-1]["sim"] if rows else None})')

ev = pd.DataFrame(rows)
ev = ev.dropna(subset=['sim'])
ev['filing_date'] = pd.to_datetime(ev['filing_date'])
ev = ev.sort_values('filing_date').reset_index(drop=True)
print(f'\nTOTAL change events: {len(ev)} across {ev.ticker.nunique()} tickers, '
      f'{ev.filing_date.min().date()} .. {ev.filing_date.max().date()}')
print('sim stats:', ev['sim'].describe().round(4).to_dict())

ev.to_parquet(os.path.join(os.path.dirname(__file__), 'edgar_lazyprices_events.parquet'))
buf = io.BytesIO(); ev.to_parquet(buf)
try:
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.put_object(Bucket=BUCKET, Key='research/edgar_lazyprices_events.parquet', Body=buf.getvalue())
    print('saved to S3 research/edgar_lazyprices_events.parquet')
except Exception as e:
    print('S3 save skipped:', e)
print('done')
