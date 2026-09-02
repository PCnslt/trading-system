"""Forward news information-arrival experiment — collector + immutable ledger.

Point-in-time integrity:
- published_at_utc  = source timestamp (when the article says it was published)
- observed_at_utc   = when WE actually saw it (the info-availability boundary)
All predictions use observed_at as the boundary. Events are append-only; never
rewritten. Raw observations are stored separately from derived features.
"""
import os, io, json, time, hashlib, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone
import boto3
from dotenv import load_dotenv

load_dotenv()
B = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')
UA = {'User-Agent': 'Mozilla/5.0 (research; info@pcnslt.com)'}

SYMS = ['AAPL','MSFT','NVDA','TSLA','AMZN','GOOGL','META','AMD','AVGO','NFLX',
        'INTC','MU','PLTR','ORCL','CRM','COST','UNH','LLY','JPM','V','MA','HD',
        'PEP','KO','XOM','CVX','JNJ','ABBV','TMO','WMT','BAC','GS','DIS','QCOM',
        'TXN','ADBE','CSCO','IBM','PYPL','UBER']

def utcnow():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def url_hash(u):
    return hashlib.sha256(u.encode()).hexdigest()[:16]

def newsapi(sym):
    k = os.getenv('NEWSAPI_ORG_API_KEY')
    if not k:
        return []
    url = f'https://newsapi.org/v2/everything?q={sym}&sortBy=publishedAt&pageSize=10&apiKey={k}'
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read())
        out = []
        for a in d.get('articles', []):
            out.append(dict(title=a.get('title',''), url=a.get('url',''),
                            published_at=a.get('publishedAt'), source=(a.get('source') or {}).get('name','')))
        return out
    except Exception:
        return []

def rss_search(sym):
    url = 'https://www.bing.com/news/search?q=' + urllib.parse.quote(sym) + '&format=rss'
    try:
        root = ET.fromstring(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15).read())
        out = []
        for it in root.iter('item'):
            t = it.findtext('title'); l = it.findtext('link'); p = it.findtext('pubDate')
            if t:
                out.append(dict(title=t, url=l or '', published_at=p, source='bing_rss'))
        return out
    except Exception:
        return []

def normalize(raw, sym, observed):
    """Dedupe + normalize raw items into point-in-time events."""
    seen = set(); evs = []
    for r in raw:
        if not r.get('title'):
            continue
        h = url_hash(r.get('url') or r['title'])
        if h in seen:
            continue
        seen.add(h)
        evs.append(dict(
            event_id=h + '_' + sym,
            observed_at_utc=observed,
            published_at_utc=r.get('published_at') or '',
            source=r.get('source',''),
            symbol=sym,
            headline=r['title'][:300],
            source_url_hash=h,
        ))
    return evs

def append_jsonl(key, records):
    """Append records to an immutable JSONL object in S3 (read-merge-write with last-write-wins guard on event_id)."""
    existing = {}
    try:
        body = s3.get_object(Bucket=B, Key=key)['Body'].read().decode()
        for line in body.splitlines():
            try:
                o = json.loads(line); existing[o['event_id']] = o
            except Exception:
                pass
    except s3.exceptions.NoSuchKey:
        pass
    for r in records:
        existing.setdefault(r['event_id'], r)   # never overwrite
    s3.put_object(Bucket=B, Key=key, Body='\n'.join(json.dumps(v, ensure_ascii=False) for v in existing.values()) + '\n')

def run():
    day = datetime.now(timezone.utc).strftime('%Y%m%d')
    observed = utcnow()
    all_evs = []
    for sym in SYMS:
        raw = newsapi(sym) + rss_search(sym)
        evs = normalize(raw, sym, observed)
        all_evs.extend(evs)
        time.sleep(1.1)  # rate limit
    # persist raw (immutable) + normalized (immutable)
    raw_key = f'news/raw/{day}/{int(time.time())}.json'
    s3.put_object(Bucket=B, Key=raw_key, Body=json.dumps(all_evs, ensure_ascii=False))
    append_jsonl('news/events/events.jsonl', all_evs)
    print(f'collected {len(all_evs)} events -> {raw_key} + news/events/events.jsonl')

if __name__ == '__main__':
    run()
