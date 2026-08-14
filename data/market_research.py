"""Market research loop — fetch financial news, log to the data lake.

Runs on cron (every 30 min). v1 = fetch + log. v2 = HF sentiment (FinBERT)
added to the `sentiment()` hook once the model spec is finalized.

Sources: Serper news + NewsAPI. Logs to DynamoDB pk NEWS#<YYYY-MM-DD>.
"""
import os
import time
import json
import datetime as dt
import urllib.request

import boto3
from dotenv import load_dotenv

load_dotenv('/home/ubuntu/trading-system/.env')

SERPER = os.getenv('SERPER_API_KEY')
NEWSAPI = os.getenv('NEWSAPI_ORG_API_KEY')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

# Market-moving topics to track. Add tickers/sectors as the system grows.
TOPICS = [
    'stock market S&P 500',
    'Nasdaq technology stocks',
    'Federal Reserve interest rate',
    'market moving earnings',
]


def serper_news(q, n=8):
    body = json.dumps({'q': q, 'num': n}).encode()
    req = urllib.request.Request(
        'https://google.serper.dev/news', data=body,
        headers={'X-API-KEY': SERPER, 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode()).get('news', [])


def sentiment(text: str) -> float:
    """v2 hook: return a score in [-1, 1] via free HF FinBERT. Stub = 0."""
    return 0.0


def main():
    table = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)
    now = int(time.time())
    day = dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')
    total = 0
    for topic in TOPICS:
        try:
            articles = serper_news(topic)
        except Exception as e:
            print(f'{topic}: fetch error {e}')
            continue
        for a in articles:
            title = (a.get('title') or '')[:200]
            if not title:
                continue
            table.put_item(Item={
                'pk': f'NEWS#{day}',
                'sk': f'{now}#{topic}#{total}',
                'topic': topic,
                'title': title,
                'source': a.get('source', ''),
                'date': a.get('date', ''),
                'link': a.get('link', ''),
                'sentiment': str(sentiment(title)),
                'ts': now,
            })
            total += 1
    print(f'[{dt.datetime.now(dt.UTC).isoformat()}] logged {total} headlines')


if __name__ == '__main__':
    main()
