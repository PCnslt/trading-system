"""Tests for the Robinhood Crypto Trading API client (infra/rh_crypto.py).

Signing follows Robinhood's current reference implementation
(message = f"{api_key}{timestamp}{path}{method}{body}"; body = json.dumps,
empty for GET). The docs' static example vector is STALE (predates the current
scheme — verified 2026-08-24 by brute-forcing every field permutation), so we
test determinism + structure rather than that vector.
"""
import base64
import json

import pytest

from infra.rh_crypto import RHCryptoClient, RHCryptoError, RHCryptoNotConfigured, sign_message

PRIV = base64.b64encode(b"x" * 32).decode()  # 32-byte Ed25519 seed


def test_sign_message_deterministic_and_varies():
    a = sign_message("rh-api-x", PRIV, 1698708981, "GET", "/p", "")
    b = sign_message("rh-api-x", PRIV, 1698708981, "GET", "/p", "")
    assert a == b and isinstance(a, str)
    assert sign_message("rh-api-x", PRIV, 1698708982, "GET", "/p", "") != a


def test_sign_message_embeds_body_and_path():
    assert sign_message("k", PRIV, 1, "GET", "/a", "") != sign_message("k", PRIV, 1, "GET", "/b", "")
    assert sign_message("k", PRIV, 1, "POST", "/a", "{}") != sign_message("k", PRIV, 1, "POST", "/a", "")


def test_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(RHCryptoClient, "_load_ssm", lambda self: (None, None))
    c = RHCryptoClient()
    assert not c.configured
    with pytest.raises(RHCryptoNotConfigured):
        c._headers("GET", "/p", "")


def test_place_order_body_structure(monkeypatch):
    monkeypatch.setattr(RHCryptoClient, "_load_ssm", lambda self: ("rh-api-x", PRIV))
    captured = {}

    def fake_request(self, method, path, body=None):
        captured["method"] = method
        captured["path"] = path
        captured["body"] = body
        return {"ok": True}

    monkeypatch.setattr(RHCryptoClient, "_request", fake_request)
    c = RHCryptoClient()
    c.place_order("ACC", "BTC-USD", "buy", "market", {"asset_quantity": "0.1"},
                  client_order_id="cid-123")
    assert captured["method"] == "POST"
    assert "account_number=ACC" in captured["path"]
    b = captured["body"]
    assert b["client_order_id"] == "cid-123"
    assert b["side"] == "buy" and b["type"] == "market" and b["symbol"] == "BTC-USD"
    assert b["market_order_config"] == {"asset_quantity": "0.1"}


def test_protected_entry_rejects_no_stop(monkeypatch):
    monkeypatch.setattr(RHCryptoClient, "_load_ssm", lambda self: ("rh-api-x", PRIV))
    c = RHCryptoClient()
    with pytest.raises(RHCryptoError):
        c.place_protected_entry("ACC", "BTC-USD", "buy", "market",
                                {"asset_quantity": "0.1"}, "0")
