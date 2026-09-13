#!/usr/bin/env python3
"""Stage 1 of the 24h-market overnight-hold study: resumable local OHLC cache.

Downloads daily OHLCV parquet for the union of
  (a) research/smallcap_universe_full.json  (524 sub-$50, ADV>=$50M names)
  (b) STOCKS in bot/live_equities.py        (189-190 liquid large-caps)
from s3://<bucket>/ibkr/equities/daily/<SYM>.parquet into a local cache dir so
the analysis stage never re-hits S3.  Read-only w.r.t. S3.

Run: ./venv/bin/python -u research/overnight_24h_fetch.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time

import boto3
import pandas as pd
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"))

BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
PREFIX = "ibkr/equities/daily/"
CACHE_DIR = os.path.join(_ROOT, "research", ".ohlc_cache")
MANIFEST = os.path.join(CACHE_DIR, "_manifest.json")


def smallcap_universe() -> list[str]:
    d = json.load(open(os.path.join(_ROOT, "research", "smallcap_universe_full.json")))
    return list(dict.fromkeys(d["symbols"]))


def largecap_universe() -> list[str]:
    text = open(os.path.join(_ROOT, "bot", "live_equities.py"), encoding="utf-8").read()
    m = re.search(r"^STOCKS\s*=\s*\[(.*?)\]\n", text, re.S | re.M)
    if not m:
        raise RuntimeError("could not parse STOCKS list from bot/live_equities.py")
    return list(dict.fromkeys(re.findall(r"'([^']+)'", m.group(1))))


def main() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    sc = smallcap_universe()
    lc = largecap_universe()
    union = list(dict.fromkeys(sc + lc))
    print(f"[universe] smallcap={len(sc)} largecap={len(lc)} union={len(union)}")

    s3 = boto3.client("s3", region_name=AWS_REGION)
    missing, ok = [], []
    t0 = time.time()
    for i, sym in enumerate(union):
        dst = os.path.join(CACHE_DIR, f"{sym}.parquet")
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            ok.append(sym)
            continue
        try:
            obj = s3.get_object(Bucket=BUCKET, Key=PREFIX + sym + ".parquet")
            raw = obj["Body"].read()
            df = pd.read_parquet(io.BytesIO(raw))
            need = {"date", "open", "high", "low", "close", "volume"}
            if not need.issubset(df.columns):
                missing.append(sym)
                continue
            with open(dst, "wb") as fh:
                fh.write(raw)
            ok.append(sym)
        except Exception:  # noqa: BLE001
            missing.append(sym)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(union)} ok={len(ok)} missing={len(missing)} "
                  f"({time.time()-t0:.0f}s)", flush=True)

    manifest = {
        "smallcap": [s for s in sc if s in set(ok)],
        "largecap": [s for s in lc if s in set(ok)],
        "smallcap_requested": len(sc),
        "largecap_requested": len(lc),
        "missing": missing,
    }
    json.dump(manifest, open(MANIFEST, "w"), indent=2)
    print(f"\n[done] cached={len(ok)} missing={len(missing)}")
    print(f"[done] smallcap available={len(manifest['smallcap'])}/{len(sc)} "
          f"largecap available={len(manifest['largecap'])}/{len(lc)}")
    if missing:
        print(f"[missing] {missing}")
    print(f"wrote {MANIFEST}")


if __name__ == "__main__":
    main()
