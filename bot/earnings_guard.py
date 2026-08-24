"""Earnings guard — never ENTER a name that reports earnings within the hold window.

Reads the ``RESEARCH#earnings`` feed (written daily ~17:15 ET by
``research/rh_research.py`` from Robinhood's earnings calendar) and returns the
set of symbols reporting within ``[today, today + days_ahead]``. The equity bots
exclude these from NEW entries so no position is ever held naked through an
earnings gap (never-lose-money: an earnings gap blows through a stop).

FAIL-OPEN: a missing / stale / malformed feed returns an EMPTY set (no
exclusion). The guard only ADDS protection when the data is present — a missing
earnings feed must never block the whole lane from trading.
"""
from __future__ import annotations

import datetime as dt
import json


def load_upcoming_earnings(table, today: str | None = None, days_ahead: int = 5) -> set:
    """Set of UPPERCASE symbols with an earnings report in [today, today+days_ahead].

    ``table`` is a boto3 DynamoDB Table resource. ``today`` defaults to the
    current UTC date (matching the RESEARCH#earnings sk convention).
    """
    if today is None:
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    try:
        item = table.get_item(Key={"pk": "RESEARCH#earnings", "sk": today}).get("Item")
        if not item:
            return set()
        events = json.loads(item.get("payload") or "[]")
    except Exception:  # noqa: BLE001 — fail-open, never block the lane
        return set()

    try:
        today_d = dt.date.fromisoformat(today)
    except ValueError:
        return set()

    out: set = set()
    for e in events:
        d = e.get("date")
        if not d:
            continue
        if e.get("eps_act"):  # an actual EPS means it already reported -> not upcoming
            continue
        try:
            ed = dt.date.fromisoformat(d)
        except (ValueError, TypeError):
            continue
        if today_d <= ed <= today_d + dt.timedelta(days=days_ahead):
            sym = (e.get("symbol") or "").strip().upper()
            if sym:
                out.add(sym)
    return out
