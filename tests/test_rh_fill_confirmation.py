"""Regression tests for the async fill confirmation in place_equity_entry.

Guards the bug that produced ZERO live fills 2026-08-20 -> 2026-08-24: the entry
path read ``state`` once from the order-creation response and demanded 'filled'.
Real Robinhood creation responses come back queued/pending (often state=''), so
every live entry fail-closed with RHOrderError("entry not confirmed filled").
10 valid RSI2 signals were rejected this way on 2026-08-24.
"""
from __future__ import annotations

import pytest

from hardening import rh_client as rc
from hardening.rh_client import RHClient, RHOrderError


class FakeRH(RHClient):
    """Drives place_equity_entry without any network/SSM."""

    def __init__(self, states, *, fill_qty=2.0, cancel_flips_to=None):
        self._states = list(states)          # states returned by successive polls
        self._fill_qty = fill_qty
        self._cancel_flips_to = cancel_flips_to
        self.placed, self.cancelled, self.stops, self.flattened = [], [], [], []

    # --- RHClient surface used by place_equity_entry -------------------------
    def _resolve_account(self, account_number=None):
        return account_number or "ACCT1"

    def place_equity_order(self, symbol, side, order_type, **kw):
        self.placed.append((symbol, side, order_type, kw.get("quantity")))
        return {"id": "OID1", "state": self._states.pop(0) if self._states else ""}

    def list_orders(self, account_number=None, symbol=None, state=None, order_id=None):
        st = self._states.pop(0) if self._states else ""
        return [{"id": "OID1", "state": st, "cumulative_quantity": self._fill_qty}]

    def cancel_order(self, order_id, account_number=None):
        self.cancelled.append(order_id)
        if self._cancel_flips_to:                 # cancel lost the race
            self._states = [self._cancel_flips_to]
        return {"id": order_id, "state": "cancelled"}

    def place_stop(self, symbol, position_side, quantity, stop_price, **kw):
        self.stops.append((symbol, position_side, quantity, float(stop_price)))
        return {"id": "STOP1", "state": "queued"}

    def _stop_is_resting(self, *a, **k):
        return True

    def _flatten(self, symbol, entry_side, **kw):
        self.flattened.append(symbol)
        return {}


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    monkeypatch.setattr(rc, "RH_FILL_POLL_S", 0.0)
    monkeypatch.setattr(rc, "RH_FILL_TIMEOUT_S", 1.0)
    monkeypatch.setattr(rc.time, "sleep", lambda *_: None)


def test_queued_then_filled_is_accepted():
    """THE REGRESSION: queued on creation, filled on a later poll -> must succeed."""
    c = FakeRH(states=["queued", "confirmed", "filled"])
    c.place_equity_entry("BB", "buy", 7.07, quantity="2")
    assert c.stops == [("BB", "long", 2, 7.07)], "protective stop must be rested"
    assert not c.cancelled and not c.flattened


def test_empty_state_then_filled_is_accepted():
    """state='' was the exact production symptom on 2026-08-24."""
    c = FakeRH(states=["", "", "filled"])
    c.place_equity_entry("ONB", "buy", 24.85, quantity="1", )
    assert c.stops and c.stops[0][0] == "ONB"


def test_never_filled_is_cancelled_and_raises():
    """Fail-closed: nothing may be left resting that could fill unprotected."""
    c = FakeRH(states=["queued"] + ["queued"] * 50)
    with pytest.raises(RHOrderError) as e:
        c.place_equity_entry("FHN", "buy", 23.62, quantity="1")
    assert c.cancelled == ["OID1"], "a timed-out entry MUST be cancelled"
    assert not c.stops
    assert "cancelled" in str(e.value)


def test_cancel_race_late_fill_is_protected_not_abandoned():
    """If the cancel loses the race and it filled, protect it instead of raising."""
    c = FakeRH(states=["queued"] + ["queued"] * 50, cancel_flips_to="filled")
    c.place_equity_entry("EBC", "buy", 21.75, quantity="2")
    assert c.cancelled == ["OID1"]
    assert c.stops == [("EBC", "long", 2, 21.75)], "late fill must still get a stop"


def test_rejected_short_circuits_without_cancel():
    c = FakeRH(states=["rejected"])
    with pytest.raises(RHOrderError):
        c.place_equity_entry("VSH", "buy", 10.0, quantity="1")
    assert not c.cancelled and not c.stops


def test_stop_price_zero_still_refused_before_placing():
    c = FakeRH(states=["filled"])
    with pytest.raises(Exception):
        c.place_equity_entry("BB", "buy", 0.0, quantity="1")
    assert not c.placed, "must reject BEFORE sending anything to the broker"
