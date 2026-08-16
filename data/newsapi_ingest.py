"""NewsAPI daily headline ingest — traded symbols + macro (no sentiment).

Runs daily (cron). Queries NewsAPI.org `everything` (sortBy=publishedAt) for the
traded ETF proxies (SPY/QQQ) + futures/macro terms. Writes DynamoDB (pk
NEWSAPI#<date>) + S3 (historical append, one blob/run).

No NLP/sentiment here — that's the future research-enhancement track (FinBERT etc.).
"""
import os
import json
import time
import hashlib
import datetime as dt

import boto3
import requests
from dotenv import load_dotenv

load_dotenv("/home/ubuntu/trading-system/.env")
# --- SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb
_sb()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
S3_BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")
NEWS_KEY = os.getenv("NEWSAPI_ORG_API_KEY", "")

# traded symbols + macro terms (lean; free plan = 100 req/day)
QUERIES = [
    "SPY",
    "QQQ",
    "S&P 500 futures",
    "Nasdaq",
    "Federal Reserve",
    "E-mini S&P",
]

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
s3 = boto3.client("s3", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMO_TABLE)


def fetch(query, page_size=10):
    r = requests.get(
        "https://newsapi.org/v2/everything",
        params={"q": query, "sortBy": "publishedAt", "pageSize": page_size,
                "language": "en", "apiKey": NEWS_KEY},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        print(f"  [warn] {query}: {data.get('message')}")
        return []
    return data.get("articles", [])


def main():
    if not NEWS_KEY:
        print("NEWSAPI_ORG_API_KEY missing — abort")
        return
    now = int(time.time())
    day = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    all_articles = []
    for q in QUERIES:
        try:
            arts = fetch(q)
        except Exception as e:
            print(f"  {q}: fetch error {e}")
            continue
        for a in arts:
            title = (a.get("title") or "").strip()[:300]
            if not title:
                continue
            src = (a.get("source") or {}).get("name", "")
            item = {
                "pk": f"NEWSAPI#{day}",
                "sk": f"{now}#{q}#{hashlib.md5(title.encode()).hexdigest()}",
                "query": q,
                "title": title,
                "source": src,
                "publishedAt": a.get("publishedAt", ""),
                "url": a.get("url", ""),
                "description": (a.get("description") or "").strip()[:300],
                "ts": now,
            }
            table.put_item(Item=item)
            all_articles.append(item)
        time.sleep(1)  # be gentle to the API
    key = f"newsapi/{dt.datetime.now(dt.UTC).strftime('%Y/%m/%d')}/{now}.json"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(all_articles))
    print(f"newsapi ingest: {len(all_articles)} headlines -> s3://{S3_BUCKET}/{key}")


if __name__ == "__main__":
    main()

