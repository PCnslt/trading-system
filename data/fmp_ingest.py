"""FMP daily ingest — quote/profile (fundamentals) for a small watchlist + macro.

Runs daily (cron). Watchlist = traded ETF proxies (SPY/QQQ), index proxies for
ES/NQ/MNQ (^GSPC/^IXIC), and vol/macro (^VIX). Writes DynamoDB (operational/
latest via sk=date) + S3 (historical append).

Free-tier note (verified): FMP `stable/quote` works for SPY + indexes but is
premium-gated for QQQ (402); `stable/profile` works for both ETFs and carries
price/marketCap/beta/sector/industry, so we merge quote→profile with profile as
fallback. `stable/key-metrics`, `stable/ratios`, `stable/income-statement`, and
`stable/treasury` return [] (paid); the script probes them and merges any non-empty
results, so upgrading the key auto-enriches. Treasury yield series (^TNX/^FVX/^TYX)
are premium-only on FMP — flagged, not ingested here.
"""
import os
import json
import time
import datetime as dt
from decimal import Decimal

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
FMP_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE = "https://financialmodelingprep.com/stable"

ETFS = ["SPY", "QQQ"]          # traded ETF proxies (fundamentals available)
INDEXES = ["^GSPC", "^IXIC"]   # ES proxy · NQ/MNQ proxy
VOL = ["^VIX"]                 # macro / vol

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
s3 = boto3.client("s3", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMO_TABLE)


def _dec(x):
    try:
        return Decimal(str(x))
    except Exception:
        return None


def _get(endpoint, **params):
    params["apikey"] = FMP_KEY
    try:
        r = requests.get(f"{FMP_BASE}/{endpoint}", params=params, timeout=30)
    except Exception as e:
        print(f"    [net] {endpoint} {params.get('symbol')}: {e}")
        return None
    if r.status_code != 200:
        print(f"    [{r.status_code}] {endpoint} {params.get('symbol')}: {r.text[:120]}")
        return None
    data = r.json()
    if isinstance(data, (dict, str)):
        if isinstance(data, dict) and "Error Message" in data:
            return None
        if isinstance(data, str):
            return None
    return data


def _first(data):
    return data[0] if isinstance(data, list) and data else {}


def put_record(pk, sk, payload):
    item = {"pk": pk, "sk": sk, "ts": int(time.time())}
    for k, v in payload.items():
        if isinstance(v, float):
            item[k] = _dec(v)
        elif isinstance(v, bool) or v is None:
            item[k] = v
        elif isinstance(v, (int, str)):
            item[k] = v
        else:
            item[k] = str(v)
    table.put_item(Item=item)


def archive(sym, obj):
    now = dt.datetime.now(dt.UTC)
    key = f"fmp/{sym}/{now.strftime('%Y/%m/%d')}/{int(time.time())}.json"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(obj, default=str))
    return key


def ingest_symbol(sym, with_profile=True):
    date = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    quote = _first(_get("quote", symbol=sym))
    prof = _first(_get("profile", symbol=sym)) if with_profile else {}
    # merge: quote wins where present, profile fills gaps (incl. price when quote gated)
    rec = dict(quote)
    for k, v in prof.items():
        rec.setdefault(k, v)
    if not rec:
        print(f"  [skip] {sym}: no data")
        return
    if rec.get("description"):
        rec["description"] = rec["description"][:300]
    # Probe paid-tier endpoints; merge if non-empty (auto-enrich on key upgrade).
    for ep, tag in (("key-metrics", "metrics"), ("ratios", "ratios")):
        m = _first(_get(ep, symbol=sym, period="annual", limit=1))
        if m:
            rec[tag] = m
    rec["fetchedAt"] = dt.datetime.now(dt.UTC).isoformat()
    put_record(f"FMP#{sym}", date, rec)
    key = archive(sym, rec)
    print(f"  {sym}: price={rec.get('price')} -> s3://{S3_BUCKET}/{key}")


def main():
    if not FMP_KEY:
        print("FMP_API_KEY missing — abort")
        return
    for sym in ETFS:
        ingest_symbol(sym, with_profile=True)
    for sym in INDEXES + VOL:
        ingest_symbol(sym, with_profile=False)
    print("fmp ingest done")


if __name__ == "__main__":
    main()

