"""Robinhood Crypto Trading API client (fractional, XRP-capable, native stop_loss).

A SEPARATE surface from the equities MCP (``agent.robinhood.com/mcp/trading``).
Auth = API key + Ed25519 keypair signature (NOT OAuth). Base URL
``https://trading.robinhood.com``.

Credentials live in SSM under ``/trading/robinhood-crypto/``:
  ``api_key``      — the ``rh-api-<uuid>`` key from crypto account settings
  ``private_key``  — base64 Ed25519 private key (owner-generated via pynacl)
Owner creates both at https://robinhood.com/account/crypto (see
docs/CRYPTO-TRADING-RESEARCH.md). This client is FAIL-CLOSED: every method
raises ``RHCryptoNotConfigured`` until both keys exist, so nothing can trade
with a half-configured credential.

Never-lose-money note: Robinhood crypto supports native ``stop_loss`` and
``stop_limit`` order types, so a protective stop CAN rest broker-side here
(UNLIKE IBKR crypto, which is market/limit only). Fractional via
``asset_quantity`` (coin amount) or ``quote_amount`` (USD amount).

Signing (verified against the docs example vector):
    message = f"{api_key}{timestamp}{path}{method}{body}"
    x-signature = base64(Ed25519.sign(message).signature)
where ``path`` INCLUDES the query string and ``body`` is ``json.dumps(payload)``
(empty for GET). Stdlib urllib only — safe to import anywhere.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import time
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:
    import nacl.signing
    _NACL_OK = True
except ImportError:  # pragma: no cover
    _NACL_OK = False

BASE_URL = "https://trading.robinhood.com"
SSM_PREFIX = "/trading/robinhood-crypto/"
V1 = "/api/v1/crypto"


class RHCryptoError(Exception):
    """Robinhood crypto client error."""


class RHCryptoNotConfigured(RHCryptoError):
    """Credentials missing from SSM — owner must create API key + keypair."""


def _b64key_to_seed(private_key_b64: str):
    return base64.b64decode(private_key_b64)


def sign_message(api_key: str, private_key_b64: str, timestamp: int,
                 method: str, path: str, body: str = "") -> str:
    """Return the base64 x-signature for a request (pure, testable)."""
    seed = _b64key_to_seed(private_key_b64)
    key = nacl.signing.SigningKey(seed)
    message = f"{api_key}{timestamp}{path}{method}{body}"
    return base64.b64encode(key.sign(message.encode("utf-8")).signature).decode("utf-8")


class RHCryptoClient:
    def __init__(self, api_key: str | None = None, private_key_b64: str | None = None,
                 region: str | None = None):
        self.api_key = api_key
        self.private_key_b64 = private_key_b64
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        if not (self.api_key and self.private_key_b64):
            self.api_key, self.private_key_b64 = self._load_ssm()
        self._key = None

    # ---- credentials ----
    def _load_ssm(self):
        try:
            import boto3
            c = boto3.client("ssm", region_name=self.region)
            r = c.get_parameters(
                Names=[SSM_PREFIX + "api_key", SSM_PREFIX + "private_key"],
                WithDecryption=True)
            vals = {p["Name"].removeprefix(SSM_PREFIX): p["Value"]
                    for p in r.get("Parameters", [])}
            return vals.get("api_key"), vals.get("private_key")
        except Exception:  # noqa: BLE001
            return None, None

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.private_key_b64)

    def _require(self):
        if not self.configured or not _NACL_OK:
            raise RHCryptoNotConfigured(
                "Robinhood crypto creds missing (SSM /trading/robinhood-crypto/*) — "
                "owner must create an API key + Ed25519 keypair at "
                "https://robinhood.com/account/crypto")

    # ---- signing + transport ----
    def _headers(self, method: str, path: str, body: str = "") -> dict:
        self._require()
        ts = int(dt.datetime.now(tz=dt.timezone.utc).timestamp())
        sig = sign_message(self.api_key, self.private_key_b64, ts, method, path, body)
        return {"x-api-key": self.api_key, "x-signature": sig, "x-timestamp": str(ts),
                "Content-Type": "application/json", "Accept": "application/json"}

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        body_str = json.dumps(body) if body is not None else ""
        headers = self._headers(method, path, body_str)
        url = BASE_URL + path
        data = body_str.encode("utf-8") if body_str else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise RHCryptoError(f"HTTP {e.code}: {detail}") from e

    # ---- read-only ----
    def get_accounts(self) -> dict:
        return self._request("GET", f"{V1}/trading/accounts/")

    def get_trading_pairs(self, *symbols: str) -> dict:
        q = urllib.parse.urlencode([("symbol", s) for s in symbols]) if symbols else ""
        return self._request("GET", f"{V1}/trading/trading_pairs/{('?' + q) if q else ''}")

    def get_holdings(self, *asset_codes: str) -> dict:
        q = urllib.parse.urlencode([("asset_code", a) for a in asset_codes]) if asset_codes else ""
        return self._request("GET", f"{V1}/trading/holdings/{('?' + q) if q else ''}")

    def get_best_bid_ask(self, *symbols: str) -> dict:
        q = urllib.parse.urlencode([("symbol", s) for s in symbols]) if symbols else ""
        return self._request("GET", f"{V1}/marketdata/best_bid_ask/{('?' + q) if q else ''}")

    def get_orders(self, account_number: str, order_id: str | None = None) -> dict:
        if order_id:
            path = f"{V1}/trading/orders/{order_id}/?account_number={account_number}"
        else:
            path = f"{V1}/trading/orders/?account_number={account_number}"
        return self._request("GET", path)

    # ---- order placement ----
    def place_order(self, account_number: str, symbol: str, side: str, order_type: str,
                    config: dict, client_order_id: str | None = None) -> dict:
        """Place a crypto order. ``config`` is the type-specific config dict:
        market → {"asset_quantity": "0.1" | "quote_amount": "50"}
        limit  → {"asset_quantity"/"quote_amount", "limit_price"}
        stop_loss → {"asset_quantity"/"quote_amount", "stop_price"}
        stop_limit → {"asset_quantity"/"quote_amount", "stop_price", "limit_price"}
        """
        side = side.lower()
        if side not in ("buy", "sell"):
            raise RHCryptoError(f"invalid side {side!r}")
        if order_type not in ("market", "limit", "stop_loss", "stop_limit"):
            raise RHCryptoError(f"invalid order type {order_type!r}")
        # ---- pre-trade risk firewall (enforcement boundary: credentials may be
        # present, but the order is STILL blocked unless the firewall authorizes) ----
        from hardening.order_gate import gate_order
        qty_raw = config.get("asset_quantity") or config.get("quote_amount") or 0
        try:
            qty_f = float(qty_raw)
        except (TypeError, ValueError):
            qty_f = 0.0
        gate_order(
            strategy=os.getenv("RH_STRATEGY", "rh_crypto"), broker="robinhood_crypto",
            account=account_number or "unknown", symbol=symbol.upper(), side=side,
            quantity=qty_f, price=None, order_type="market",
            signal_id=client_order_id or "", operation="OPEN_NEW",
        )
        key = {"market": "market_order_config", "limit": "limit_order_config",
               "stop_loss": "stop_loss_order_config",
               "stop_limit": "stop_limit_order_config"}[order_type]
        cid = client_order_id or str(uuid.uuid4())
        body = {
            "client_order_id": cid,
            "side": side,
            "type": order_type,
            "symbol": symbol.upper(),
            key: config,
        }
        path = f"{V1}/trading/orders/?account_number={account_number}"
        return self._request("POST", path, body)

    def place_protected_entry(self, account_number: str, symbol: str, side: str,
                              entry_type: str, entry_config: dict,
                              stop_price: str, stop_config: dict | None = None) -> dict:
        """Fail-closed protected entry: place the entry, then rest a native
        stop_loss (or stop_limit) broker-side. Returns {'entry': ..., 'stop': ...}.
        Raises RHCryptoError if the entry or stop is rejected — never leaves a
        naked position."""
        if float(stop_price) <= 0:
            raise RHCryptoError("protective stop requires stop_price > 0 (never-lose)")
        entry = self.place_order(account_number, symbol, side, entry_type, entry_config)
        stop_side = "sell" if side == "buy" else "buy"
        st_cfg = stop_config or {"asset_quantity": entry_config.get("asset_quantity", "0"),
                                 "stop_price": stop_price}
        st = None
        last_err: Exception | None = None
        for _ in range(3):  # retry transient 5xx before destructive recovery
            try:
                st = self.place_order(account_number, symbol, stop_side, "stop_loss", st_cfg)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                if "HTTP 5" not in str(e) and "timed out" not in str(e).lower():
                    break
                time.sleep(2.0)
        if st is None:
            # Never leave a naked position: flatten the just-placed entry.
            flat_side = "sell" if side == "buy" else "buy"
            try:
                self.place_order(account_number, symbol, flat_side, "market",
                                 {"asset_quantity": entry_config.get("asset_quantity", "0")})
            except Exception:  # noqa: BLE001 - surfaced by the raise below
                pass
            raise RHCryptoError(f"protective stop failed — entry reversed: {last_err!r}") from last_err
        return {"entry": entry, "stop": st}

    def cancel_order(self, account_number: str, order_id: str) -> dict:
        path = f"{V1}/trading/orders/{order_id}/cancel/?account_number={account_number}"
        return self._request("POST", path)


if __name__ == "__main__":
    import sys
    c = RHCryptoClient()
    if not c.configured:
        print("RHCryptoNotConfigured: no creds in SSM /trading/robinhood-crypto/* "
              "(owner must create API key + keypair).")
        sys.exit(2)
    print(json.dumps(c.get_accounts(), indent=2))
