"""Robinhood research collector — leverages Robinhood's curated research surface.

Pulls three feeds from the Robinhood trading MCP (already authenticated) that this
system was NOT using, and persists them to DynamoDB + S3 for signal generation:

  1. Earnings calendar (next N days, high-market-cap filter) — the catalyst feed.
     Enables an earnings-avoidance guard (never hold a name through a naked gap).
  2. Robinhood screener presets (DAILY_GAINERS / DAILY_LOSERS) — Robinhood's own
     momentum picks (the closest programmatic proxy for Robinhood "AI advice").
  3. (Optional) fundamentals join for a symbol list.

READ-ONLY with respect to orders — no equity/crypto order is ever placed here.
`create_scan` does persist a saved scan on the Robinhood account (a harmless,
reusable screener definition), documented as a side effect.

Persistence:
  DynamoDB  RESEARCH#earnings/<date>  +  RESEARCH#scan/<date>
  S3        research/rh-research/<date>.json

Run:  ./venv/bin/python -u research/rh_research.py [--days 7] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

import boto3
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"))

from hardening.rh_client import RHClient  # noqa: E402

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")

SCAN_PRESETS = ("DAILY_GAINERS", "DAILY_LOSERS")


def pull_earnings(client: RHClient, days: int) -> dict:
    raw = client.get_earnings_calendar(days=days, high_market_cap=True)
    results = ((raw.get("data") or {}).get("results")) or []
    events = []
    for r in results:
        events.append({
            "symbol": r.get("symbol"),
            "date": (r.get("report") or {}).get("date"),
            "timing": (r.get("report") or {}).get("timing"),
            "verified": (r.get("report") or {}).get("verified"),
            "eps_est": (r.get("eps") or {}).get("estimate"),
            "eps_act": (r.get("eps") or {}).get("actual"),
        })
    # upcoming (no actual yet) first, then by date
    events.sort(key=lambda e: (e["date"] or "", e["symbol"] or ""))
    return {"source": "robinhood-earnings-calendar", "ts": int(time.time()),
            "days": days, "count": len(events), "events": events}


def pull_scans(client: RHClient) -> list[dict]:
    """Robinhood screener presets (DAILY_GAINERS/DAILY_LOSERS) → momentum picks.

    Reuses a previously-created saved scan (run_scan) to avoid accumulating a new
    saved scan every run; only create_scan when no matching scan exists yet.
    """
    existing = client.get_scans() or []
    out = []
    for preset in SCAN_PRESETS:
        try:
            scan_id = None
            needle = preset.lower().replace("_", " ")
            for s in existing:
                title = (s.get("title") or s.get("scan_title") or "").lower()
                if needle in title:
                    scan_id = s.get("scan_id")
                    break
            if scan_id:
                res = client.run_scan(scan_id)
                d = res.get("data") or res
                result = d.get("result") or d
                rows = result.get("results") or d.get("results") or []
            else:
                created = client.create_scan(preset=preset)
                d = created.get("data") or created
                result = d.get("result") or d
                scan_id = result.get("scan_id")
                rows = result.get("results") or []
            norm = []
            for r in rows:
                cols = r.get("columns") or {}
                norm.append({
                    "symbol": cols.get("Symbol") or r.get("ticker"),
                    "name": cols.get("Name"),
                    "change_pct": cols.get("% Change"),
                    "market_cap": cols.get("Market cap"),
                    "volume": cols.get("Volume"),
                    "relative_volume": cols.get("Relative volume"),
                })
            out.append({"preset": preset, "scan_id": scan_id,
                        "count": len(norm), "results": norm[:50]})
        except Exception as e:  # noqa: BLE001 — degrade, never crash the lane
            out.append({"preset": preset, "error": repr(e)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-scans", action="store_true", help="skip the screener presets")
    args = ap.parse_args()

    client = RHClient()
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    earnings = pull_earnings(client, args.days)
    scans = [] if args.no_scans else pull_scans(client)

    payload = {"lane": "rh-research", "date": today, "ts": int(time.time()),
               "earnings": earnings, "scans": scans}

    # ---- persist ----
    table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(DYNAMO_TABLE)
    if not args.dry_run:
        table.put_item(Item={"pk": "RESEARCH#earnings", "sk": today,
                             "ts": int(time.time()), "days": args.days,
                             "count": earnings["count"],
                             "payload": json.dumps(earnings["events"])})
        table.put_item(Item={"pk": "RESEARCH#scan", "sk": today,
                             "ts": int(time.time()),
                             "payload": json.dumps(scans)})
        try:
            s3 = boto3.client("s3", region_name=AWS_REGION)
            s3.put_object(Bucket=S3_BUCKET,
                          Key=f"research/rh-research/{today}.json",
                          Body=json.dumps(payload, default=str))
        except Exception as e:  # noqa: BLE001
            print(f"  S3 archive failed: {e!r}")

    # ---- digest ----
    upcoming = [e for e in earnings["events"] if not e["eps_act"]]
    print(f"Robinhood research — {earnings['count']} earnings events "
          f"({len(upcoming)} upcoming) over {args.days}d")
    for e in upcoming[:15]:
        print(f"  {e['date']} {e['timing'] or '--':2s}  {e['symbol']:<6s} "
              f"est {e['eps_est'] or '—'}")
    for s in scans:
        if "error" in s:
            print(f"  scan[{s['preset']}] ERROR: {s['error'][:80]}")
        else:
            print(f"  scan[{s['preset']}] {s['count']} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
