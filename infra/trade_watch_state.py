#!/usr/bin/env python3
"""Emit a STABLE, deterministic fingerprint of trading-system state.

Used as a cron monitor_script: the scheduler hashes this stdout and only fires the
LLM trade-watch agent when the hash CHANGES (a trade fired, a position opened/closed,
RECONCILE/CONTROL flipped, or a service went down). Output MUST contain no timestamps
and be sorted/deterministic so a quiet system hashes identically tick after tick.

Read-only. Uses the EC2 instance role (no keys on disk). Run via the repo venv
(see ~/.hermes/scripts/trade_watch_state.sh).
"""
import os
import subprocess
from datetime import datetime, timezone

import boto3

TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
REGION = os.getenv("AWS_REGION", "us-east-1")
dyn = boto3.client("dynamodb", region_name=REGION)

SERVICES = [
    "ibgateway", "futures-tick-recorder", "reconcile-daemon",
    "live-index", "live-gold", "live-vwap",
    "live-equities", "live-equities-ibkr", "orderbook-collector",
    "trading-dashboard", "trading-reports",
]


def _s(v, default="?"):
    """Decode a DynamoDB scalar attribute value."""
    if not isinstance(v, dict):
        return default
    if "S" in v:
        return v["S"]
    if "N" in v:
        return v["N"]
    if "BOOL" in v:
        return str(v["BOOL"])
    return default


def get_item(pk, sk):
    r = dyn.get_item(TableName=TABLE, Key={"pk": {"S": pk}, "sk": {"S": sk}})
    return r.get("Item")


def scan_prefix(prefix):
    items = []
    kw = dict(
        TableName=TABLE,
        FilterExpression="begins_with(pk, :p)",
        ExpressionAttributeValues={":p": {"S": prefix}},
    )
    while True:
        r = dyn.scan(**kw)
        items += r.get("Items", [])
        if "LastEvaluatedKey" in r:
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        else:
            break
    return items


lines = []

# 1. CONTROL (kill-switch state)
c = get_item("CONTROL", "system")
lines.append("CONTROL=%s flatten=%s" % (
    _s(c.get("state"), "MISSING") if c else "MISSING",
    _s(c.get("flatten"), "false") if c else "false",
))

# 2. RECONCILE (broker-vs-book state)
r = get_item("RECONCILE", "system")
if r:
    lines.append("RECONCILE=%s streak=%s" % (
        _s(r.get("status")), _s(r.get("mismatch_streak"), "0")))
else:
    lines.append("RECONCILE=MISSING")

# 3. RH open/pending positions (live + paper book)
rh = sorted(
    it["pk"]["S"].split("#", 1)[1]
    for it in scan_prefix("RHPOS#")
    if _s(it.get("status")) in ("OPEN", "PENDING")
)
lines.append("RH_OPEN=" + (",".join(rh) if rh else "none"))

# 4. IBKR/futures/crypto open positions (POSITION# pos != 0)
ib = []
for it in scan_prefix("POSITION#"):
    try:
        pos = float(_s(it.get("pos"), "0"))
    except ValueError:
        pos = 0.0
    if pos != 0.0:
        ib.append(it["pk"]["S"].split("#", 1)[1])
ib.sort()
lines.append("IBKR_OPEN=" + (",".join(ib) if ib else "none"))

# 5. Trades fired today (UTC date key)
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
n_trades = 0
for prefix in ("TRADE#", "RHTRADE#"):
    for it in scan_prefix(prefix):
        if _s(it.get("sk"), "").startswith(today):
            n_trades += 1
lines.append("TRADES_TODAY=%d" % n_trades)

# 6. Service health (systemd is-active, read-only)
svc = []
for s in SERVICES:
    p = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True)
    svc.append("%s:%s" % (s, p.stdout.strip()))
lines.append("SVC=" + ",".join(svc))

print("\n".join(lines))
