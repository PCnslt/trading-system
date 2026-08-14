"""Market research loop — fetch financial news, score sentiment (HF), log to data lake.

Runs on cron (every 30 min). Sentiment = local `mrm8488/distilroberta-finetuned-
financial-news-sentiment-analysis` (82M params, ~98% acc, fp16, CPU) — fits the
VPS's ~1GB spare. Falls back to neutral (still fetches + logs) if the model is
unavailable/OOM so the loop never dies.

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
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
SENTIMENT_MODEL = os.getenv(
    'SENTIMENT_MODEL',
    'mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis',
)

# Market-moving topics to track. Add tickers/sectors as the system grows.
TOPICS = [
    'stock market S&P 500',
    'Nasdaq technology stocks',
    'Federal Reserve interest rate',
    'market moving earnings',
]

# ---- sentiment (lazy load, cache the pipeline) ----
_pipe = None


def _load_pipeline():
    global _pipe
    if _pipe is None:
        try:
            import torch
            from transformers import pipeline
            _pipe = pipeline(
                'sentiment-analysis', model=SENTIMENT_MODEL, tokenizer=SENTIMENT_MODEL,
                device=-1, dtype=torch.float16, truncation=True, max_length=128,
            )
        except Exception as e:
            print(f'sentiment model unavailable ({e}) — logging without scores')
            _pipe = False  # sentinel: disabled
    return _pipe


def score_batch(texts):
    """Return list of {label, score} aligned to texts. Falls back to neutral."""
    pipe = _load_pipeline()
    clean = [t.strip() for t in texts if t and t.strip()]
    if pipe is False or not clean:
        return [{'label': 'neutral', 'score': 0.0} for _ in texts]
    try:
        out = pipe(clean, batch_size=32)
    except Exception as e:
        print(f'sentiment inference error ({e}) — logging without scores')
        return [{'label': 'neutral', 'score': 0.0} for _ in texts]
    # map results back (pipeline returns in order, but guard length)
    res = []
    for r in out:
        label = r.get('label', 'neutral').lower()
        # normalize: this repo's id2label is 0=negative 1=neutral 2=positive
        if label.startswith('lab'):
            idx = int(label.split('_')[-1])
            label = {0: 'negative', 1: 'neutral', 2: 'positive'}.get(idx, 'neutral')
        res.append({'label': label, 'score': round(float(r.get('score', 0.0)), 4)})
    while len(res) < len(texts):
        res.append({'label': 'neutral', 'score': 0.0})
    return res


def serper_news(q, n=8):
    body = json.dumps({'q': q, 'num': n}).encode()
    req = urllib.request.Request(
        'https://google.serper.dev/news', data=body,
        headers={'X-API-KEY': SERPER, 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode()).get('news', [])


def main():
    table = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)
    now = int(time.time())
    day = dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')

    # 1. fetch all headlines
    articles = []  # list of (topic, title, source, date, link)
    for topic in TOPICS:
        try:
            for a in serper_news(topic):
                title = (a.get('title') or '').strip()[:200]
                if title:
                    articles.append((topic, title, a.get('source', ''), a.get('date', ''), a.get('link', '')))
        except Exception as e:
            print(f'{topic}: fetch error {e}')

    # 2. batch sentiment
    scores = score_batch([t for _, t, *_ in articles])

    # 3. log
    for (topic, title, source, date, link), s in zip(articles, scores):
        table.put_item(Item={
            'pk': f'NEWS#{day}',
            'sk': f'{now}#{topic}#{abs(hash(title)) % 100000}',
            'topic': topic, 'title': title, 'source': source, 'date': date,
            'link': link, 'sentiment': s['label'], 'score': str(s['score']), 'ts': now,
        })

    pos = sum(1 for s in scores if s['label'] == 'positive')
    neg = sum(1 for s in scores if s['label'] == 'negative')
    print(f'[{dt.datetime.now(dt.UTC).isoformat()}] logged {len(articles)} headlines (pos {pos} / neg {neg} / neu {len(articles)-pos-neg})')


if __name__ == '__main__':
    main()
