"""Crypto ticker ingestion (runs every ~10 min for near-live prices).

Writes to DynamoDB (hot) only — high-frequency data, not archived to S3
(archive daily candles instead of every tick).
"""
import os
import time
import datetime as dt

import boto3
import requests
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMO_TABLE)


def put_quote(sym, price):
    ts = dt.datetime.now(dt.UTC).isoformat()
    table.put_item(Item={"pk": f"QUOTE#{sym}", "sk": ts, "price": str(price), "ts": int(time.time())})


def main():
    for sym in CRYPTO:
        try:
            r = requests.get("https://api.binance.us/api/v3/ticker/price", params={"symbol": sym}, timeout=15)
            if r.status_code == 200:
                price = r.json().get("price")
                put_quote(sym, price)
                print(f"{sym}: {price}")
        except Exception as e:
            print(f"{sym}: error {e}")
    print("tick done")


if __name__ == "__main__":
    main()
