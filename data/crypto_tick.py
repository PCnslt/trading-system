"""Crypto ticker ingestion (runs every ~10 min for near-live prices).

Writes to DynamoDB (hot) AND S3 (daily JSONL historical append).
Source: Binance.US public ticker (no key). Note: CoinMarketCap key is NOT
present in .env — flagged; if added later, swap the source here.
"""
import os
import json
import time
import datetime as dt

import boto3
import requests
from dotenv import load_dotenv

load_dotenv("/home/ubuntu/trading-system/.env")

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
S3_BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")
CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMO_TABLE)
s3 = boto3.client("s3", region_name=AWS_REGION)


def put_quote(sym, price):
    ts = dt.datetime.now(dt.UTC).isoformat()
    table.put_item(Item={"pk": f"QUOTE#{sym}", "sk": ts, "price": str(price), "ts": int(time.time())})


def append_s3_tick(sym, price):
    """Append one tick line to the day's JSONL object (historical append)."""
    now = dt.datetime.now(dt.UTC)
    key = f"crypto/{sym}/{now.strftime('%Y/%m/%d')}/ticks.jsonl"
    line = json.dumps({"symbol": sym, "price": price, "ts": int(time.time()),
                       "t": now.isoformat()}) + "\n"
    try:
        body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read().decode("utf-8")
    except Exception:
        body = ""
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=(body + line).encode("utf-8"))


def main():
    for sym in CRYPTO:
        try:
            r = requests.get("https://api.binance.us/api/v3/ticker/price", params={"symbol": sym}, timeout=15)
            if r.status_code == 200:
                price = r.json().get("price")
                put_quote(sym, price)
                append_s3_tick(sym, price)
                print(f"{sym}: {price}")
        except Exception as e:
            print(f"{sym}: error {e}")
    print("tick done")


if __name__ == "__main__":
    main()
