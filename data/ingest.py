"""Data ingestion pipeline: pull from free APIs → DynamoDB (hot) + S3 parquet (cold).

$0 data lake core. Run on a schedule (cron) or ad-hoc.
Reads secrets from .env (never committed).
"""
import os
import json
import time
import datetime as dt
from decimal import Decimal

import boto3
import requests
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
S3_BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")
ALPHAVANTAGE_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
s3 = boto3.client("s3", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMO_TABLE)


def _to_decimal(x):
    """DynamoDB requires Decimal for numbers."""
    try:
        return Decimal(str(x))
    except Exception:
        return None


def put_item(entity: str, key: str, payload: dict):
    """Write one record to DynamoDB using the single-table pk/sk design.

    pk = entity type (e.g. 'OHLCV#AAPL'), sk = sortable key (e.g. ISO timestamp).
    """
    item = {"pk": entity, "sk": key, "ts": int(time.time())}
    for k, v in payload.items():
        if isinstance(v, float):
            item[k] = _to_decimal(v)
        elif isinstance(v, (int, str, bool)) or v is None:
            item[k] = v
        else:
            item[k] = str(v)
    table.put_item(Item=item)
    return item


def archive_parquet(obj, symbol, kind):
    """Save a JSON blob to S3 (cold archive). Parquet conversion can come later."""
    today = dt.datetime.utcnow().strftime("%Y/%m/%d")
    key = f"{kind}/{symbol}/{today}/{int(time.time())}.json"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(obj))
    return f"s3://{S3_BUCKET}/{key}"


def fetch_alphavantage_daily(symbol: str) -> dict:
    """Daily OHLCV from AlphaVantage (free tier)."""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": "compact",
        "apikey": ALPHAVANTAGE_KEY,
    }
    r = requests.get(url, params=params, timeout=30)
    data = r.json()
    series = data.get("Time Series (Daily)", {})
    if not series:
        print(f"  [warn] AlphaVantage empty for {symbol}: {list(data.keys())}")
        return {}
    return series


def ingest_equity_daily(symbols):
    """Pull daily bars for each symbol → DynamoDB + S3."""
    for i, sym in enumerate(symbols):
        if i > 0:
            time.sleep(16)  # AlphaVantage free tier: ~5 req/min
        print(f"Ingesting {sym} daily...")
        series = fetch_alphavantage_daily(sym)
        for date_str, bar in series.items():
            entity = f"OHLCV#{sym}"
            # sk = date (ISO sortable)
            payload = {
                "date": date_str,
                "open": float(bar["1. open"]),
                "high": float(bar["2. high"]),
                "low": float(bar["3. low"]),
                "close": float(bar["4. close"]),
                "volume": int(bar["5. volume"]),
            }
            put_item(entity, date_str, payload)
        archive_parquet(series, sym, "ohlcv-daily")
        print(f"  {len(series)} bars written for {sym}")


def fetch_binance_ticker(symbols):
    """Current price from Binance.US (public, no auth needed)."""
    out = {}
    for sym in symbols:
        r = requests.get(
            "https://api.binance.us/api/v3/ticker/price",
            params={"symbol": sym},
            timeout=15,
        )
        if r.status_code == 200:
            out[sym] = r.json()
    return out


if __name__ == "__main__":
    # Symbols to track (expandable). Start small.
    EQUITIES = ["AAPL", "MSFT", "SPY", "MCD"]
    CRYPTO = ["BTCUSDT", "ETHUSDT"]

    print("=== Equity daily (AlphaVantage) ===")
    ingest_equity_daily(EQUITIES)

    print("=== Crypto tickers (Binance.US) ===")
    tickers = fetch_binance_ticker(CRYPTO)
    for sym, t in tickers.items():
        put_item(f"QUOTE#{sym}", dt.datetime.utcnow().isoformat(), {"price": t.get("price")})
        print(f"  {sym}: {t.get('price')}")

    print("Done.")
