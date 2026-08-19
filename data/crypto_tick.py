"""Crypto ticker ingestion (runs every ~10 min for near-live prices).

Three writes per tick:
  1. DynamoDB QUOTE#<sym>  (hot, TTL-bounded — see QUOTE_TTL_DAYS)
  2. S3 crypto-tick/<sym>/<Y>/<m>/<d>/<ts>.json   raw tick (cold)
  3. S3 crypto-candles/<sym>/<date>.json          daily OHLC candle (running;
     overwritten each run, finalizes at EOD — the "daily downsample to candles").

crypto_tick.py is the SINGLE writer of QUOTE#<sym> (ingest.py no longer writes
crypto quotes — one writer per pk).
"""
import os
import time
import datetime as dt

import boto3
import requests
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

from s3_archive import archive_quote_tick, archive_crypto_candle

load_dotenv()
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
QUOTE_TTL_DAYS = int(os.getenv("QUOTE_TTL_DAYS", "30"))
CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMO_TABLE)


def _enable_ttl():
    try:
        desc = table.meta.client.describe_time_to_live(TableName=DYNAMO_TABLE)
        status = desc.get('TimeToLiveDescription', {}).get('TimeToLiveStatus')
        if status == 'ENABLED':
            return
        table.meta.client.update_time_to_live(
            TableName=DYNAMO_TABLE,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )
    except Exception as e:
        print(f"TTL enable check failed: {e}")


def put_quote(sym, price):
    now = dt.datetime.now(dt.UTC)
    ts = int(time.time())
    table.put_item(Item={
        "pk": f"QUOTE#{sym}", "sk": now.isoformat(), "price": str(price),
        "ts": ts, "ttl": ts + QUOTE_TTL_DAYS * 86400,
    })
    archive_quote_tick(sym, price, ts)


def daily_candle(sym):
    """Aggregate today's QUOTE#<sym> ticks into a running OHLC candle."""
    day = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    start = f"{day}T00:00:00+00:00"
    r = table.query(
        KeyConditionExpression=Key("pk").eq(f"QUOTE#{sym}") & Key("sk").gte(start),
    )
    items = r.get("Items", [])
    if not items:
        return None
    prices = []
    for it in items:
        try:
            prices.append(float(it["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not prices:
        return None
    return {
        "sym": sym, "date": day,
        "open": prices[0], "high": max(prices), "low": min(prices),
        "close": prices[-1], "ticks": len(prices),
        "first_ts": int(items[0].get("ts", 0)), "last_ts": int(items[-1].get("ts", 0)),
    }


def main():
    _enable_ttl()

    for sym in CRYPTO:
        try:
            r = requests.get(
                "https://api.binance.us/api/v3/ticker/price",
                params={"symbol": sym}, timeout=15,
            )
            if r.status_code == 200:
                price = r.json().get("price")
                if price is None:
                    print(f"{sym}: no price field in response")
                    continue
                put_quote(sym, price)
                print(f"{sym}: {price}")
        except Exception as e:
            print(f"{sym}: error {e}")

    # daily downsample -> candles (running OHLC; overwritten each run, final EOD)
    for sym in CRYPTO:
        try:
            candle = daily_candle(sym)
            if candle:
                archive_crypto_candle(sym, candle)
        except Exception as e:
            print(f"{sym}: candle error {e}")

    print("tick done")


if __name__ == "__main__":
    main()

