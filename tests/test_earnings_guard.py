"""Tests for the earnings guard (bot/earnings_guard.py)."""
import json

from bot.earnings_guard import load_upcoming_earnings


class _FakeTable:
    def __init__(self, item=None, raises=False):
        self._item = item
        self._raises = raises

    def get_item(self, Key):
        if self._raises:
            raise RuntimeError("boom")
        return {"Item": self._item} if self._item else {}


def _events(events):
    return {"pk": "RESEARCH#earnings", "sk": "2026-08-24",
            "payload": json.dumps(events)}


def test_fail_open_on_missing():
    assert load_upcoming_earnings(_FakeTable(None), today="2026-08-24") == set()


def test_fail_open_on_error():
    assert load_upcoming_earnings(_FakeTable(raises=True), today="2026-08-24") == set()


def test_filters_upcoming_within_window():
    t = _FakeTable(_events([
        {"symbol": "INTU", "date": "2026-08-25", "eps_act": None},      # +1d -> in
        {"symbol": "BOX", "date": "2026-08-29", "eps_act": None},       # +5d -> in
        {"symbol": "DKS", "date": "2026-08-30", "eps_act": None},       # +6d -> out
        {"symbol": "PDD", "date": "2026-08-24", "eps_act": "2.85"},     # already reported -> out
        {"symbol": "OLD", "date": "2026-08-23", "eps_act": None},       # past -> out
        {"symbol": "EMPTY", "date": None, "eps_act": None},             # no date -> out
    ]))
    s = load_upcoming_earnings(t, today="2026-08-24", days_ahead=5)
    assert s == {"INTU", "BOX"}


def test_uppercases_symbols():
    t = _FakeTable(_events([{"symbol": "nssc", "date": "2026-08-25", "eps_act": None}]))
    assert load_upcoming_earnings(t, today="2026-08-24") == {"NSSC"}
