"""Unit tests for hardening.rh_client — fail-closed rules + token lifecycle.

No network: the SSM loader, local token file, and urllib opener are faked, and the
MCP transport is a stub. The fail-closed behaviour under test is the thing that
matters: stop required, fractional-fill reversal (never naked), idempotent ref_id,
and crash-safe refresh writeback (local file BEFORE SSM — the rotation is
irreversible, so ordering matters).
"""
import json
import time

import pytest

from hardening import rh_client
from hardening.rh_client import (
    RHClient,
    RHOrderError,
    RHStopPlacementFailed,
    RHStopRequired,
    make_ref_id,
)

FUTURE = time.time() + 86400 * 30  # token won't trigger a constructor refresh


def _token(rt="old_rt", expires_at=None):
    return {
        "access_token": "old_at",
        "token_type": "Bearer",
        "expires_in": 335466,
        "scope": "internal",
        "refresh_token": rt,
        "expires_at": expires_at if expires_at is not None else FUTURE,
    }


class FakeTransport:
    """Stub MCP transport: routes tools/call to per-name handlers."""

    def __init__(self, access_token, handlers=None):
        self.access_token = access_token
        self.handlers = handlers or {}
        self.tool_calls = []

    def rpc(self, method, params=None):
        return {}

    def call_tool(self, name, arguments):
        self.tool_calls.append((name, arguments))
        if name in self.handlers:
            return self.handlers[name](arguments)
        raise AssertionError(f"unexpected tool call: {name} {arguments}")


@pytest.fixture
def ssm_and_token(monkeypatch):
    """Fake SSM (client_id + meta_json, no token_json) + local token file."""
    def fake_ssm(region=None):
        return {
            "client_id": "cid123",
            "meta_json": json.dumps(
                {"token_endpoint": "https://api.robinhood.com/oauth2/token/"}),
        }
    monkeypatch.setattr(rh_client, "_load_ssm_creds", fake_ssm)
    monkeypatch.setattr(rh_client, "_load_local_token", lambda: _token())


def make_client(handlers, **kw):
    def factory(at):
        return FakeTransport(at, handlers)
    return RHClient(account_number="515821577", transport_factory=factory, **kw)


# ---- idempotency key ----
def test_ref_id_is_deterministic():
    a = make_ref_id("equity", "515821577", "SPY", "buy", "market", "t1")
    b = make_ref_id("equity", "515821577", "SPY", "buy", "market", "t1")
    assert a == b
    assert make_ref_id("equity", "515821577", "SPY", "sell", "market", "t1") != a


# ---- stop required (fail-closed) ----
def test_entry_rejects_zero_stop_before_any_order(ssm_and_token):
    c = make_client({})
    with pytest.raises(RHStopRequired):
        c.place_equity_entry("SPY", "buy", 0.0, dollar_amount="100.00")
    assert c._transport.tool_calls == []   # never touched the broker


def test_place_stop_requires_positive_price(ssm_and_token):
    c = make_client({})
    with pytest.raises(RHStopRequired):
        c.place_stop("SPY", "long", 1, 0.0)


def test_stop_order_requires_stop_price(ssm_and_token):
    c = make_client({})
    with pytest.raises(RHStopRequired):
        c.place_equity_order("SPY", "sell", "stop_market", quantity="1")


# ---- fractional fill reversal (never naked) ----
def test_entry_fractional_fill_is_reversed(ssm_and_token):
    def place(args):
        side = args["side"]
        if side == "buy":
            return {"data": {"id": "o1", "state": "filled", "quantity": "0.5",
                             "cumulative_quantity": "0.5", "average_price": "100.0"}}
        return {"data": {"id": "o3", "state": "filled"}}  # flatten sell
    c = make_client({"place_equity_order": place})
    with pytest.raises(RHStopPlacementFailed):
        c.place_equity_entry("SPY", "buy", 95.0, dollar_amount="50.00",
                             client_order_ref="t1")
    calls = [a for name, a in c._transport.tool_calls if name == "place_equity_order"]
    sides = [a["side"] for a in calls]
    assert sides == ["buy", "sell"]   # entry then reversal (never left naked)
    sell = calls[1]
    # the reversal MUST carry a size (a size-less order would be rejected -> naked)
    assert sell.get("dollar_amount") == "50.00"


# ---- happy path: entry + resting stop ----
def test_entry_happy_path_places_and_verifies_stop(ssm_and_token):
    def place(args):
        if args["side"] == "buy":
            return {"data": {"id": "o1", "state": "filled", "quantity": "1",
                             "cumulative_quantity": "1", "average_price": "100.0"}}
        return {"data": {"id": "o2", "state": "confirmed", "type": "stop_market"}}

    def orders(args):
        return {"data": {"orders": [
            {"side": "sell", "type": "stop_market", "state": "confirmed", "id": "o2"}]}}

    c = make_client({"place_equity_order": place, "get_equity_orders": orders})
    r = c.place_equity_entry("SPY", "buy", 95.0, dollar_amount="100.00",
                             client_order_ref="t1")
    assert r["entry"]["id"] == "o1"
    assert r["stop"]["id"] == "o2"
    assert r["stop_qty"] == 1


def test_entry_no_confirmed_fill_raises(ssm_and_token):
    def place(args):
        return {"data": {"id": "o1", "state": "queued", "quantity": "1"}}
    c = make_client({"place_equity_order": place})
    with pytest.raises(Exception):
        c.place_equity_entry("SPY", "buy", 95.0, dollar_amount="100.00")


# ---- read-only shapes ----
def test_get_quote_unwraps(ssm_and_token):
    def quotes(args):
        return {"data": {"results": [{"quote": {"symbol": "SPY",
                                                "last_trade_price": "776.31"}}]}}
    c = make_client({"get_equity_quotes": quotes})
    q = c.get_quote("spy")
    assert q["symbol"] == "SPY"
    assert q["last_trade_price"] == "776.31"


def test_get_account_prefers_agentic(ssm_and_token):
    def accts(args):
        return {"data": {"accounts": [
            {"account_number": "A1", "agentic_allowed": False},
            {"account_number": "515821577", "agentic_allowed": True}]}}
    c = make_client({"get_accounts": accts})
    assert c.get_account()["account_number"] == "515821577"


# ---- refresh rotation + crash-safe writeback ----
def test_refresh_persists_local_before_ssm(ssm_and_token, monkeypatch):
    c = make_client({})
    order = []
    ssm_writes = []

    def fake_urlopen(req, timeout=None):
        body = json.dumps({
            "access_token": "new_at",
            "token_type": "Bearer",
            "expires_in": 335466,
            "scope": "internal",
            "refresh_token": "new_rt",
            "user_uuid": "u",
        }).encode()

        class R:
            def read(self):
                return body
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return R()

    monkeypatch.setattr(rh_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(rh_client, "_save_local_token",
                        lambda t: order.append("local"))
    monkeypatch.setattr(rh_client, "_save_ssm_token",
                        lambda t, region=None: (order.append("ssm"),
                                                ssm_writes.append(t)))

    at = c.refresh()

    assert at == "new_at"
    assert c._token["refresh_token"] == "new_rt"          # rotation captured
    assert order == ["local", "ssm"]                      # local FIRST (crash-safe)
    assert ssm_writes[0]["refresh_token"] == "new_rt"     # SSM got the rotated token
    assert ssm_writes[0]["expires_at"] > time.time()      # expires_at recomputed


# ---- refresh race guard (double-refresh on two threads racing a 401) ----
def test_refresh_race_guard_skips_redundant_rotation(ssm_and_token, monkeypatch):
    c = make_client({})
    urlopen_calls = []

    def fake_urlopen(req, timeout=None):
        urlopen_calls.append(1)
        body = json.dumps({
            "access_token": "new_at",
            "token_type": "Bearer",
            "expires_in": 335466,
            "scope": "internal",
            "refresh_token": "new_rt",
        }).encode()

        class R:
            def read(self):
                return body
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return R()

    monkeypatch.setattr(rh_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(rh_client, "_save_local_token", lambda t: None)
    monkeypatch.setattr(rh_client, "_save_ssm_token", lambda t, region=None: None)

    at1 = c.refresh()
    at2 = c.refresh()  # immediate second call (racing thread) — must NOT rotate again

    assert at1 == "new_at"
    assert at2 == "new_at"                 # reused the first thread's fresh token
    assert len(urlopen_calls) == 1         # only ONE token rotation


# ---- empirical fractional-stop check (read-only, no order) ----
def test_check_fractional_stop_accepted(ssm_and_token):
    def review(args):
        return {"data": {"quote": {}, "alerts": []}}
    c = make_client({"review_equity_order": review})
    r = c.check_fractional_stop("SPY", 100.0)
    assert r["conclusion"] == "ACCEPTED"
    assert all(ch["accepted"] is True for ch in r["checks"])
    # read-only: the only tool touched is review_equity_order, never placement
    assert {name for name, _ in c._transport.tool_calls} == {"review_equity_order"}


def test_check_fractional_stop_rejected(ssm_and_token):
    def review(args):
        raise RHOrderError("stop orders require whole shares")
    c = make_client({"review_equity_order": review})
    r = c.check_fractional_stop("SPY", 100.0)
    assert r["conclusion"] == "REJECTED"
    assert all(ch["accepted"] is False for ch in r["checks"])
    assert {name for name, _ in c._transport.tool_calls} == {"review_equity_order"}
