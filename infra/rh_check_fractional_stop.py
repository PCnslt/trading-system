#!/usr/bin/env python3
"""Empirical fractional-stop check — READ-ONLY (places NO order).

Settles the whole-share-vs-fractional sizing question with DATA, not assumption:
Robinhood's `review_equity_order` MCP tool SIMULATES an order (returns the quote +
pre-trade alerts) without placing it. This runner builds the VPS single-writer
client and calls `RHClient.check_fractional_stop()` — a SELL `stop_market` for a
FRACTIONAL dollar_amount AND a fractional share quantity — and logs whether
Robinhood accepts a protective stop on a sub-1-share position.

If either variant is accepted, fractional positions CAN carry a broker stop and
the `place_equity_entry` whole-share-only guard can be relaxed. If both are
rejected, the guard stands (sub-1-share = no broker stop = fail-closed reversal).

Read-only by design: `review_equity_order` is the MCP simulate path; no order is
ever placed. Requires a LIVE token (re-auth first if revoked):
    python3 infra/rh_oauth.py --check
    python3 infra/rh_oauth.py --reauth   # owner-gated browser consent

Usage:
    python3 infra/rh_check_fractional_stop.py [--symbol SPY] [--stop-pct 0.02] \
        [--dollar-amount 1.00] [--quantity 0.5]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only fractional-stop verification (no order)")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--dollar-amount", default="1.00", help="fractional $ to test (default 1.00)")
    ap.add_argument("--quantity", default="0.5", help="fractional share count to test (default 0.5)")
    ap.add_argument("--stop-price", type=float, default=None,
                    help="stop price; default = 98%% of last trade (quote-derived)")
    args = ap.parse_args()

    from hardening.rh_client import RHClient

    try:
        client = RHClient()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({
            "result": "BLOCKED",
            "reason": f"RHClient init failed (token dead/revoked?): {e!r}",
            "next": "python3 infra/rh_oauth.py --check ; python3 infra/rh_oauth.py --reauth",
        }, indent=2))
        return 1

    stop_price = args.stop_price
    if stop_price is None:
        q = client.get_quote(args.symbol)
        last = q.get("last_trade_price") or q.get("close")
        if not last:
            print(json.dumps({"result": "BLOCKED", "reason": "no quote for stop-price default"},
                             indent=2))
            return 1
        stop_price = round(float(last) * 0.98, 4)  # 2% below last, a plausible stop

    result = client.check_fractional_stop(
        args.symbol, stop_price,
        dollar_amount=args.dollar_amount, quantity=args.quantity)

    print(json.dumps(result, indent=2))
    return 0 if result.get("conclusion") in ("ACCEPTED", "REJECTED") else 1


if __name__ == "__main__":
    sys.exit(main())
