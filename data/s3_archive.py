"""S3 cold-archive helpers — the analytical copy of DynamoDB's hot data.

Data-lake split: DynamoDB `trading-data` = hot/operational (signals, positions,
latest quotes, control state); S3 `trading-datalake-*` = cold/analytical
(bars, news, ticks, scan results). These helpers write the cold side so the
hot table does not grow unbounded.

Format: JSON throughout. Parquet is a future optimization — adding pyarrow is
not worth the dependency yet, so `archive_json` (renamed from the old
`archive_parquet`, which never actually emitted parquet) is the honest name.

S3 prefixes:
  ohlcv-daily/<sym>/<Y>/<m>/<d>/<ts>.json            equity daily bars
  futures-bars/daily/<sym>/<date>.json               ES/NQ/ZB/ZN daily bars
  futures-bars/intraday/<sym>/<barsize>/<date>.json  MES 5m/15m bars
  news-archive/<topic>/<Y>/<m>/<d>/<ts>.json         news batch per topic/run
  crypto-tick/<sym>/<Y>/<m>/<d>/<ts>.json            raw quote ticks
  crypto-candles/<sym>/<date>.json                   daily OHLC candle
  research/scan-results/<name>/<Y>/<m>/<d>/<ts>.json strategy scan outputs
"""
import os
import json
import datetime as dt

import boto3
from dotenv import load_dotenv

# Always resolve the repo .env regardless of CWD (scripts run from repo root,
# but be robust to ad-hoc invocations).
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

_s3 = None


def s3():
    """Cached boto3 S3 client (lazy, so importing the module is cheap)."""
    global _s3
    if _s3 is None:
        _s3 = boto3.client('s3', region_name=AWS_REGION)
    return _s3


def _utcnow():
    return dt.datetime.now(dt.timezone.utc)


def _json_default(o):
    """Serialize numpy numerics as floats; fall back to str for the rest."""
    try:
        return float(o)
    except (TypeError, ValueError):
        return str(o)


def put_json(obj, key):
    s3().put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(obj, default=_json_default))
    return f's3://{S3_BUCKET}/{key}'


def put_bytes(data, key):
    s3().put_object(Bucket=S3_BUCKET, Key=key, Body=data)
    return f's3://{S3_BUCKET}/{key}'


def archive_json(obj, symbol, kind):
    """Generic JSON blob -> s3://<bucket>/<kind>/<symbol>/<Y>/<m>/<d>/<ts>.json.

    (Renamed from `archive_parquet`, which always wrote JSON.)
    """
    now = _utcnow()
    key = f"{kind}/{symbol}/{now.strftime('%Y/%m/%d')}/{int(now.timestamp())}.json"
    return put_json(obj, key)


# ---- news ----
def _topic_slug(topic):
    slug = ''.join(c if c.isalnum() else '-' for c in topic.lower())
    slug = '-'.join(p for p in slug.split('-') if p)[:80]
    return slug or 'topic'


def archive_news_batch(topic, items):
    """One batch of news items for a topic -> news-archive/<topic>/<Y>/<m>/<d>/<ts>.json."""
    now = _utcnow()
    key = f"news-archive/{_topic_slug(topic)}/{now.strftime('%Y/%m/%d')}/{int(now.timestamp())}.json"
    return put_json({'topic': topic, 'ts': int(now.timestamp()), 'items': items}, key)


# ---- crypto ----
def archive_quote_tick(sym, price, ts):
    now = _utcnow()
    key = f"crypto-tick/{sym}/{now.strftime('%Y/%m/%d')}/{ts}.json"
    return put_json({'sym': sym, 'price': price, 'ts': ts}, key)


def archive_crypto_candle(sym, candle):
    key = f"crypto-candles/{sym}/{candle['date']}.json"
    return put_json(candle, key)


# ---- futures bars ----
def archive_daily_bar(sym, bar):
    """One daily OHLCV bar -> futures-bars/daily/<sym>/<date>.json (idempotent)."""
    key = f"futures-bars/daily/{sym}/{bar['date']}.json"
    return put_json(bar, key)


def archive_intraday_bars(sym, barsize, date, records):
    """RTH intraday bars -> futures-bars/intraday/<sym>/<barsize>/<date>.json.

    Overwrites the same <date> key each run, so the object always holds the
    latest full window for that session (bounded: one object/day/barsize).
    """
    key = f"futures-bars/intraday/{sym}/{barsize}/{date}.json"
    return put_json({'sym': sym, 'barsize': barsize, 'date': date, 'bars': records}, key)


# ---- scan results ----
def archive_scan_results(name, payload):
    now = _utcnow()
    key = f"research/scan-results/{name}/{now.strftime('%Y/%m/%d')}/{int(now.timestamp())}.json"
    return put_json(payload, key)
