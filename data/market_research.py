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
import hashlib
import datetime as dt
import urllib.request

import boto3
from dotenv import load_dotenv

load_dotenv('/home/ubuntu/trading-system/.env')
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

from s3_archive import archive_news_batch

SERPER = os.getenv('SERPER_API_KEY')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
SENTIMENT_MODEL = os.getenv(
    'SENTIMENT_MODEL',
    'mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis',
)
NEWS_TTL_DAYS = int(os.getenv('NEWS_TTL_DAYS', '30'))  # DynamoDB hot-window retention

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


def _enable_ttl(table):
    """Ensure DynamoDB TTL is on for the 'ttl' attribute (idempotent, quiet).

    Only items carrying a 'ttl' attribute are ever deleted — everything else
    (signals, positions, control) is untouched. TTL is best-effort: AWS purges
    expired items within ~48h, which is fine for bounding NEWS/QUOTE growth.
    """
    try:
        desc = table.meta.client.describe_time_to_live(TableName=table.table_name)
        status = desc.get('TimeToLiveDescription', {}).get('TimeToLiveStatus')
        if status == 'ENABLED':
            return
        table.meta.client.update_time_to_live(
            TableName=table.table_name,
            TimeToLiveSpecification={'Enabled': True, 'AttributeName': 'ttl'},
        )
    except Exception as e:
        print(f'TTL enable check failed: {e}')


def main():
    table = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)
    now = int(time.time())
    day = dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')

    _enable_ttl(table)

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

    # 3. log to DynamoDB (hot, TTL-bounded) + archive to S3 (cold)
    batches = {}  # topic -> list of item dicts (pk/sk stripped)
    for (topic, title, source, date, link), s in zip(articles, scores):
        item = {
            'pk': f'NEWS#{day}',
            'sk': f'{now}#{topic}#{hashlib.md5(title.encode()).hexdigest()}',
            'topic': topic, 'title': title, 'source': source, 'date': date,
            'link': link, 'sentiment': s['label'], 'score': str(s['score']),
            'ts': now, 'ttl': now + NEWS_TTL_DAYS * 86400,
        }
        table.put_item(Item=item)
        batches.setdefault(topic, []).append(
            {k: v for k, v in item.items() if k not in ('pk', 'sk')})

    for topic, items in batches.items():
        try:
            archive_news_batch(topic, items)
        except Exception as e:
            print(f'news archive failed [{topic}]: {e}')

    pos = sum(1 for s in scores if s['label'] == 'positive')
    neg = sum(1 for s in scores if s['label'] == 'negative')
    print(f'[{dt.datetime.now(dt.UTC).isoformat()}] logged {len(articles)} headlines (pos {pos} / neg {neg} / neu {len(articles)-pos-neg})')


if __name__ == '__main__':
    main()

