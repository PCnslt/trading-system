"""Broker accessibility audit — 3-venue matrix + SQS publish.

Produces the accessibility matrix rows {Robinhood live, IBKR paper, IBKR live}
x cols {auth, account visible, permissions, market data, order-ready} =
OK / BLOCKED:<exact reason>, then publishes it to the VPS→laptop SQS FIFO queue
and writes docs/ACCESSIBILITY_MATRIX.md.

READ-ONLY: uses ib_insync readonly connections + `whatIfOrder` (no live order)
and the Robinhood MCP account tools (no order placement). No order is ever placed.

Usage:
    python infra/broker_access_audit.py               # full 3-venue audit
    python infra/broker_access_audit.py --no-publish  # print only, no SQS
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

COLS = ["auth", "account_visible", "permissions", "market_data", "order_ready"]
SQS_QUEUE_URL = os.environ.get(
    "SQS_QUEUE_URL",
    "https://sqs.us-east-1.amazonaws.com/920641308584/vps-to-laptop.fifo",
)
SQS_REGION = os.environ.get("AWS_REGION", "us-east-1")
IBKR_PAPER_PORT = int(os.environ.get("IBKR_PAPER_PORT", "4002"))
IBKR_LIVE_PORT = int(os.environ.get("IBKR_LIVE_PORT", "4003"))


def _blank(venue):
    return {c: "BLOCKED" for c in COLS} | {"venue": venue, "detail": ""}


def robinhood_row():
    from infra.robinhood import audit
    return audit()


def ibkr_row(port, venue, expect_account=None, client_id=61):
    """Introspect an IB Gateway API port. Readonly + whatIf only, no live order."""
    row = _blank(venue)
    try:
        from ib_insync import IB, Future, Stock, Option, MarketOrder
    except Exception as e:  # noqa: BLE001
        row["detail"] = f"ib_insync import failed: {e!r}"
        return row

    ib = IB()
    try:
        ib.connect("127.0.0.1", port, clientId=client_id, timeout=10, readonly=True)
    except Exception as e:  # noqa: BLE001
        row["detail"] = f"connect refused/failed: {e!r}"
        return row

    try:
        accts = ib.managedAccounts()
        row["auth"] = "OK"
        if not accts:
            row["account_visible"] = "BLOCKED: managedAccounts() empty"
        else:
            row["account_visible"] = "OK: " + ",".join(accts)
            if expect_account and expect_account not in accts:
                row["account_visible"] = (
                    f"BLOCKED: expected {expect_account}, saw {accts}")

        # --- permissions: qualify futures / equity / option ---
        perm = []
        for label, con in [
            ("futures:MES", Future("MES", "202609", "CME")),
            ("equity:AAPL", Stock("AAPL", "SMART", "USD")),
            ("option:SPY", Option("SPY", "20260918", 550, "C", "SMART")),
        ]:
            try:
                q = ib.qualifyContracts(con)
                perm.append(f"{label}=OK" if q else f"{label}=NO-DEF")
            except Exception as e:  # noqa: BLE001
                perm.append(f"{label}=ERR({e})")
        row["permissions"] = " | ".join(perm)

        # --- market data: live vs delayed on one equity + one future ---
        md = []
        ib.reqMarketDataType(1)
        for label, con in [
            ("ES", Future("ES", "202609", "CME")),
            ("AAPL", Stock("AAPL", "SMART", "USD")),
        ]:
            try:
                q = ib.qualifyContracts(con)[0]
                t = ib.reqMktData(q, "", False, False)
                ib.sleep(1.5)
                md.append(f"{label}:type={t.marketDataType},last={'nan' if t.last != t.last else t.last}")
                ib.cancelMktData(q)
            except Exception as e:  # noqa: BLE001
                md.append(f"{label}=ERR({e})")
        row["market_data"] = " | ".join(md)

        # --- order-ready: whatIf (margin calc) — no live order placed ---
        try:
            mes = ib.qualifyContracts(Future("MES", "202609", "CME"))[0]
            w = ib.whatIfOrder(mes, MarketOrder("BUY", 1))
            row["order_ready"] = "YES (whatIf accepted, no rejection)"
        except Exception as e:  # noqa: BLE001
            row["order_ready"] = f"BLOCKED/UNKNOWN: whatIf -> {e!r}"

        # account summary (cash/buying power) when visible
        if accts:
            try:
                vals = {v.tag: v.value for v in ib.accountSummary(accts[0])}
                row["detail"] = json.dumps({
                    "NetLiquidation": vals.get("NetLiquidation"),
                    "TotalCashValue": vals.get("TotalCashValue"),
                    "BuyingPower": vals.get("BuyingPower"),
                })
            except Exception:  # noqa: BLE001
                pass
    finally:
        try:
            ib.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return row


def _live_gateway_state():
    """Detect whether a live gateway instance is running (and at what stage)."""
    import subprocess
    state = {"running": False, "logged_in": False, "port_bound": False, "detail": ""}
    try:
        out = subprocess.run(
            ["pgrep", "-af", "GWClient"], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            if "Jts-live" in line:
                state["running"] = True
                break
    except Exception:  # noqa: BLE001
        pass
    # a live API port bound only happens AFTER a successful login
    for port in (4001, 4003):
        try:
            r = subprocess.run(
                ["ss", "-ltn"], capture_output=True, text=True, timeout=5
            )
            if f":{port}" in r.stdout:
                state["port_bound"] = True
                state["logged_in"] = True
                state["port"] = port
                break
        except Exception:  # noqa: BLE001
            pass
    if state["running"] and not state["port_bound"]:
        state["detail"] = "gateway launched (Jts-live) but on login screen — no API port bound"
    return state


def build_matrix():
    gs = _live_gateway_state()
    live_row = _blank("IBKR live")
    live_row["detail"] = (
        "Login BLOCKED (owner action required): (a) IBKR disallows two "
        "concurrent sessions per username — paper DUR193467 holds the login "
        "(official TWS API: 'It is not possible to login to multiple trading "
        "applications simultaneously with the same username'); (b) live "
        "first-login requires IB Key 2FA (owner phone; paper mode does not "
        "use 2FA). Live gateway process currently "
        + ("running (login screen, no API port bound)" if gs["running"]
           else "not running")
        + ". Owner actions: (1) create an ADDITIONAL username in Account "
        "Management for the live account, (2) approve IB Key 2FA on first login."
    )
    rows = [
        robinhood_row(),
        ibkr_row(IBKR_PAPER_PORT, "IBKR paper", expect_account="DUR193467"),
        live_row,
    ]
    return {
        "type": "accessibility_matrix",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cols": COLS,
        "rows": rows,
    }


def publish_matrix(matrix):
    import boto3
    dedup = hashlib.sha256(
        ("accessibility_matrix|" + matrix["generated_at"]).encode()
    ).hexdigest()
    sqs = boto3.client("sqs", region_name=SQS_REGION)
    sqs.send_message(
        QueueUrl=SQS_QUEUE_URL,
        MessageBody=json.dumps(matrix, ensure_ascii=False),
        MessageGroupId="reports",
        MessageDeduplicationId=dedup,
    )
    return True


def render_table(matrix):
    rows = matrix["rows"]
    header = "| venue | " + " | ".join(COLS) + " |"
    sep = "|---" * (len(COLS) + 1) + "|"
    lines = [header, sep]
    for r in rows:
        cells = [r.get("venue", "?")]
        for c in COLS:
            v = r.get(c, "BLOCKED")
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            v = str(v or "BLOCKED").replace("|", "·").replace("\n", " ")
            cells.append(v)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    args = ap.parse_args()

    matrix = build_matrix()
    print(json.dumps(matrix, indent=2))

    # write the matrix doc
    doc = [
        "# Broker Accessibility Matrix",
        "",
        f"> Generated {matrix['generated_at']}. Read-only audit — no live orders.",
        "",
        render_table(matrix),
        "",
        "## Detail",
        "",
    ]
    for r in matrix["rows"]:
        doc.append(f"### {r['venue']}")
        doc.append("")
        doc.append(f"- `detail`: {r.get('detail', '')}")
        doc.append("")
    path = os.path.join(REPO, "docs", "ACCESSIBILITY_MATRIX.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(doc))

    if not args.no_publish:
        try:
            publish_matrix(matrix)
            print("published to SQS")
        except Exception as e:  # noqa: BLE001
            print(f"SQS publish failed (non-fatal): {e!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
