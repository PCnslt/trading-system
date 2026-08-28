"""Robinhood broker client (execution-hardening, equities lane).

The ONLY component that talks to Robinhood from this VPS. A strategy never
touches Robinhood directly — it expresses intent and this client is the single
submitter, mirroring `hardening/exec_manager.py`'s role for IBKR.

TRANSPORT (verified 2026-08-16, ground truth):
  The SSM credentials under ``/trading/robinhood/*`` are OAuth tokens minted for
  the **Robinhood MCP gateway**, NOT the public REST API. The public REST
  endpoints at ``api.robinhood.com`` reject this client_id ("rejected client id").
  The correct surface is the Streamable-HTTP MCP server:

      https://agent.robinhood.com/mcp/trading   (server "robinhood-trading" 1.1.4)

  The MCP exposes the trading tools this client wraps (get_accounts,
  get_equity_positions, get_equity_quotes, place_equity_order, get_equity_orders,
  cancel_equity_order, review_equity_order, …). Responses are SSE
  (``event: message`` / ``data: <json>``) and each ``tools/call`` result is
  ``{"content":[{"type":"text","text":"<inner JSON string>"}]}`` — the inner
  string is itself JSON and is unwrapped here.

TOKEN OWNERSHIP — SINGLE WRITER (owner lock, 2026-08-16):
  The Robinhood ``refresh_token`` is SINGLE-USE / rotating: every refresh mints a
  NEW refresh_token and immediately REVOKES the old access token too. Two
  processes sharing one token store therefore poison each other. **ONLY this VPS
  may hold a live Robinhood token** under ``/trading/robinhood/*``. The laptop MCP
  is **RETIRED for trading** — the laptop may only READ SSM to confirm state,
  never refresh or write. (Robinhood's hosted MCP exposes a SINGLE well-known
  OAuth ``client_id`` — DCR cannot mint a per-process client — so single-writer
  discipline is enforced in code here, not by credential separation. See
  research/ROBINHOOD_IBKR_RESEARCH.md.)

TOKEN LIFECYCLE (source of truth = SSM; this VPS owns it):
  - ``token_endpoint`` (``meta_json``) = ``https://api.robinhood.com/oauth2/token/``.
  - Public client, ``token_endpoint_auth_method=none`` → NO client_secret.
  - ``refresh_token`` **ROTATES on use** (verified: a successful refresh returns a
    NEW refresh_token and immediately REVOKES the old one — and the old access
    token too: "token revoked"). Therefore the refresh + writeback MUST be atomic
    and crash-safe (see ``_refresh_and_persist``): persist the new token to the
    LOCAL fallback file FIRST, then to SSM, before returning. A failed SSM write
    must never strand the (now-rotated) token.
  - Refresh is single-flight (thread lock) and also triggered proactively when
    ``expires_at - now < REFRESH_MARGIN`` and on any 401.

FAIL-CLOSED RULES (mirror exec_manager):
  - ``place_equity_entry`` REQUIRES ``stop_price > 0`` (reject otherwise —
    never-lose-money), places the entry, then IMMEDIATELY rests a protective stop
    and VERIFIES it is resting. If the stop cannot be rested (incl. a fractional
    fill that rounds to <1 whole share — Robinhood stops are whole-share only),
    the client FLATTENS the just-filled entry and raises — it never leaves a
    naked position.
  - Idempotency: every placement carries a deterministic ``ref_id`` (UUIDv5 from a
    stable ``client_order_ref``), so a re-send of the same intent is deduped
    upstream instead of double-filling.

This module imports boto3 and ib_insync NEITHER at module scope — it is safe to
import from the Streamlit dashboard (no asyncio event loop) and to unit-test with
fakes. It talks HTTP via stdlib urllib.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# ---- constants (verified against SSM + live MCP 2026-08-16) ----
RH_MCP_URL = "https://agent.robinhood.com/mcp/trading"
RH_MCP_PROTOCOL = "2025-06-18"
RH_SSM_PREFIX = "/trading/robinhood/"
RH_TOKEN_ENDPOINT_DEFAULT = "https://api.robinhood.com/oauth2/token/"
# Async fill confirmation. Robinhood returns queued/pending on order creation and
# fills arrive later, so a protected entry must POLL before resting its stop.
RH_FILL_TIMEOUT_S = float(os.getenv("RH_FILL_TIMEOUT_S", "45"))
RH_FILL_POLL_S = float(os.getenv("RH_FILL_POLL_S", "2"))

# Dynamic token fields (rotate on refresh) — must all be written back together.
TOKEN_FIELDS = ("access_token", "refresh_token", "token_type", "scope",
                "expires_at", "expires_in", "token_json")
# Static OAuth client fields (do not rotate; never rewritten by refresh).
STATIC_FIELDS = ("client_id", "client_name", "client_json", "meta_json")
ALL_FIELDS = TOKEN_FIELDS + STATIC_FIELDS

# Local fallback cache (gitignored): written BEFORE SSM on refresh so a partial
# SSM failure can never strand a rotated token.
LOCAL_TOKEN_FILE = os.path.expanduser("~/.rh-token-backup.json")

# Refresh proactively when the access token has less than this much life left.
REFRESH_MARGIN_S = 12 * 3600  # 12h

# Double-refresh race guard: after a successful refresh, a second thread that was
# already waiting on the lock (e.g. it also caught a 401 with the SAME dead token)
# reuses the first thread's fresh token instead of rotating the refresh_token a
# second time. Windows longer than this are treated as a genuine new refresh.
REFRESH_RACE_COOLDOWN_S = 30

# Robinhood's protective-stop order types are whole-share only (fractional qty is
# accepted for MARKET orders in regular hours; stop_market/stop_limit need integer
# share counts). A sub-1-share position therefore CANNOT carry a broker stop.
STOP_TYPES = ("stop_market", "stop_limit")


class RHError(Exception):
    """Base Robinhood client error."""


class RHConfigError(RHError):
    """Credentials missing/unreadable from SSM AND the local fallback."""


class RHAuthError(RHError):
    """401 / invalid_grant / revoked token — requires re-OAuth."""


class RHOrderError(RHError):
    """Order rejected by the broker (or an MCP tool error)."""


class RHStopRequired(RHError):
    """Entry submitted with stop_price <= 0 (never-lose-money)."""


class RHStopPlacementFailed(RHError):
    """A protective stop could not be rested — entry was flattened (fail-closed)."""


class RHNakedPosition(RHError):
    """A filled entry has no protective stop and could not be flattened."""


# --------------------------------------------------------------------------
# Token store (SSM source of truth + local fallback cache)
# --------------------------------------------------------------------------
def _ssm_client(region=None):
    import boto3
    from botocore.config import Config
    cfg = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
    return boto3.client("ssm", region_name=region or os.getenv("AWS_REGION", "us-east-1"),
                        config=cfg)


def _load_local_token() -> dict | None:
    try:
        with open(LOCAL_TOKEN_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save_local_token(token: dict) -> None:
    d = os.path.dirname(LOCAL_TOKEN_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(LOCAL_TOKEN_FILE, "w", encoding="utf-8") as fh:
        json.dump(token, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(LOCAL_TOKEN_FILE, 0o600)


def _load_ssm_creds(region=None) -> dict:
    """Read all /trading/robinhood/* params -> {param_key: value}.

    Never raises: returns {} on any failure (caller falls back to local file).
    get_parameters caps at 10 names, so chunk.
    """
    ssm = _ssm_client(region)
    names = [RH_SSM_PREFIX + k for k in ALL_FIELDS]
    out = {}
    try:
        for i in range(0, len(names), 10):
            resp = ssm.get_parameters(Names=names[i:i + 10], WithDecryption=True)
            for p in resp.get("Parameters", []):
                key = p["Name"].removeprefix(RH_SSM_PREFIX)
                if p.get("Value"):
                    out[key] = p["Value"]
    except Exception as e:  # noqa: BLE001 — fall back to local cache
        print(f"[rh_client] SSM read failed ({e!r}); using local fallback", flush=True)
    return out


def _save_ssm_token(token: dict, region=None) -> None:
    """Write the rotated token_json + the 6 dynamic fields back to SSM.

    Raises on failure so the caller knows the writeback did not land (the local
    file is already updated by then — the token is never stranded).
    """
    ssm = _ssm_client(region)
    token_json = json.dumps(token)
    writes = {
        "token_json": token_json,
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
        "token_type": token.get("token_type", "Bearer"),
        "scope": token.get("scope", "internal"),
        "expires_at": str(int(token.get("expires_at", 0) or 0)),
        "expires_in": str(int(token.get("expires_in", 0))),
    }
    for key, value in writes.items():
        if value in ("", None):
            continue
        ssm.put_parameter(Name=RH_SSM_PREFIX + key, Value=str(value),
                          Type="SecureString", Overwrite=True)


# --------------------------------------------------------------------------
# MCP transport (Streamable HTTP + SSE)
# --------------------------------------------------------------------------
class _McpTransport:
    """Minimal Streamable-HTTP MCP client over stdlib urllib.

    Manages the ``mcp-session-id`` header and parses SSE responses. Duck-typed
    and injectable so tests can run without network.
    """

    def __init__(self, access_token: str, url: str = RH_MCP_URL, opener=None):
        self.access_token = access_token
        self.url = url
        self.session_id = None
        self._id = 0
        self._opener = opener  # injectable urllib opener (tests)

    def _open(self, payload: dict):
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        opener = self._opener or urllib.request.build_opener()
        with opener.open(req, timeout=30) as resp:
            if resp.headers.get("mcp-session-id"):
                self.session_id = resp.headers["mcp-session-id"]
            return resp.read().decode()

    @staticmethod
    def _parse_sse(text: str) -> list[dict]:
        """Parse an SSE body into a list of JSON messages (data: lines)."""
        msgs = []
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    msgs.append(json.loads(line[6:]))
                except ValueError:
                    continue
        if not msgs:
            # Some servers answer a single JSON body (no SSE framing).
            try:
                msgs.append(json.loads(text))
            except ValueError:
                pass
        return msgs

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        rid = self._id
        body = {"jsonrpc": "2.0", "id": rid, "method": method,
                "params": params or {}}
        try:
            raw = self._open(body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (401, 403):
                raise RHAuthError(f"MCP auth rejected ({e.code}): {detail}") from e
            raise RHError(f"MCP HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, OSError) as e:
            raise RHError(f"MCP transport error: {e!r}") from e

        for msg in self._parse_sse(raw):
            if msg.get("id") == rid:
                if "error" in msg:
                    err = msg["error"]
                    raise RHError(f"MCP error {err.get('code')}: {err.get('message')}")
                return msg.get("result", {})
        return {}

    def notify(self, method: str, params: dict | None = None) -> None:
        """Fire-and-forget MCP notification (no ``id``, no response expected).

        The MCP protocol REJECTS a notification that carries an ``id`` (the
        server answers ``invalid request: unexpected id for <method>``), so this
        must NOT go through ``rpc``. ``notifications/initialized`` is the one
        handshake notification sent after ``initialize``.
        """
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        try:
            self._open(body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (401, 403):
                raise RHAuthError(f"MCP auth rejected ({e.code}): {detail}") from e
            raise RHError(f"MCP HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, OSError) as e:
            raise RHError(f"MCP transport error: {e!r}") from e

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool; return the UNWRAPPED inner JSON (the ``data`` dict).

        The MCP result is ``{"content":[{"type":"text","text":"<inner JSON>"}]}``.
        Unwrap ``content[0].text`` and json-decode it; raise on ``isError``.
        """
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            text = ""
            c = result.get("content") or []
            if c:
                text = c[0].get("text", "")
            raise RHOrderError(text[:500] or f"tool {name} returned isError")
        content = result.get("content") or []
        if not content:
            return {}
        text = content[0].get("text", "")
        try:
            return json.loads(text)
        except ValueError:
            return {"__text__": text}


def initialize_transport(transport: _McpTransport) -> None:
    """MCP handshake: initialize (RPC) + notifications/initialized (notification).

    ``notifications/initialized`` is a one-way notification, NOT a request — it
    must be sent without an ``id`` and no response is expected (the server
    rejects it with ``invalid request: unexpected id`` if sent via ``rpc``).
    """
    transport.rpc("initialize", {
        "protocolVersion": RH_MCP_PROTOCOL,
        "capabilities": {},
        "clientInfo": {"name": "trading-vps", "version": "1.0"},
    })
    notify = getattr(transport, "notify", None)
    if notify is not None:
        notify("notifications/initialized")
    else:  # legacy/test transports without a notify() — keep the old path
        transport.rpc("notifications/initialized")


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------
_REF_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # stable namespace


def make_ref_id(*parts) -> str:
    """Deterministic UUIDv5 idempotency key from a stable identity string."""
    canon = "|".join(str(p) for p in parts if p not in (None, ""))
    return str(uuid.uuid5(_REF_NS, canon))


def _num(v):
    """Safe positive-float parse. Treats '', None, '0', '0.000000' as missing (None).

    Robinhood returns cumulative_quantity='0.000000' and average_price=0.0 on the
    creation response until the fill settles; plain float('0.000000')==0.0 and is
    truthy, so it must be treated as missing, not zero."""
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _pos_qty(p):
    """Position quantity as a positive float, or 0.0."""
    try:
        f = float(p.get("quantity") or 0)
        return f if f > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------
class RHClient:
    """Robinhood broker client (equities, MCP transport).

    Loads OAuth creds from SSM (local-file fallback), keeps the token fresh via
    refresh+writeback, and wraps the MCP trading tools. All order methods are
    fail-closed and idempotent.
    """

    def __init__(self, account_number: str | None = None, region=None,
                 transport_factory=None, now=None, refresh_margin=None):
        self._region = region
        self._transport_factory = transport_factory or _McpTransport
        self._now = now or time.time
        self._refresh_margin = refresh_margin if refresh_margin is not None \
            else REFRESH_MARGIN_S
        self._lock = threading.Lock()
        self._refreshed_at = None  # last successful refresh epoch (race guard)
        self._token = self._load_token()
        self._ssm = _load_ssm_creds(region)  # static fields (client_id, meta, …)
        self._token_endpoint = self._resolve_token_endpoint()
        self.account_number = account_number

        at = self._ensure_fresh_token()
        self._transport = self._transport_factory(at)
        initialize_transport(self._transport)
        self._account = None

    # ---- token lifecycle ----
    def _resolve_token_endpoint(self) -> str:
        try:
            meta = json.loads(self._ssm.get("meta_json", "{}"))
            return meta.get("token_endpoint") or RH_TOKEN_ENDPOINT_DEFAULT
        except (ValueError, TypeError):
            return RH_TOKEN_ENDPOINT_DEFAULT

    def _load_token(self) -> dict:
        ssm = _load_ssm_creds(self._region)
        tok = None
        if ssm.get("token_json"):
            try:
                tok = json.loads(ssm["token_json"])
            except ValueError:
                tok = None
        if not tok:
            tok = _load_local_token()
        if not tok or not tok.get("access_token"):
            raise RHConfigError(
                "no Robinhood token in SSM or local fallback — run infra/rh_oauth.py "
                "to re-authenticate")
        return tok

    def _ensure_fresh_token(self) -> str:
        """Return a valid access_token, refreshing if expiring. Fail-closed."""
        expires_at = float(self._token.get("expires_at", 0) or 0)
        if expires_at and (expires_at - self._now()) > self._refresh_margin:
            return self._token["access_token"]
        return self.refresh()

    def refresh(self) -> str:
        """Refresh the access token and atomically persist the (rotated) token.

        FAIL-CLOSED / CRASH-SAFE: the refresh ROTATES the refresh_token and
        revokes the old access token, so the new token is persisted to the LOCAL
        fallback file FIRST, then to SSM, before this returns. A failed SSM write
        still leaves the token on disk (never stranded). Single-flight via a lock.
        """
        with self._lock:
            # Race guard: if another thread already refreshed while we waited on
            # the lock, reuse its (fresh) token instead of rotating the
            # refresh_token a second time. Two threads can both hit a 401 with
            # the SAME dead token — only the first should rotate it. (A raw
            # expires_at re-check is WRONG here: a revoked token can still be
            # within its exp window, so freshness is judged by the last-refresh
            # marker, not the clock.)
            if self._refreshed_at is not None and \
                    (self._now() - self._refreshed_at) < REFRESH_RACE_COOLDOWN_S:
                return self._token["access_token"]
            rt = self._token.get("refresh_token")
            if not rt:
                raise RHAuthError("no refresh_token — re-OAuth required")
            cid = self._client_id()
            body = urllib.parse.urlencode({
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": cid,
            }).encode()
            req = urllib.request.Request(self._token_endpoint, data=body,
                                         method="POST",
                                         headers={"Content-Type":
                                                  "application/x-www-form-urlencoded",
                                                  "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:300]
                raise RHAuthError(f"token refresh rejected ({e.code}): {detail}") from e
            except (urllib.error.URLError, OSError, ValueError) as e:
                raise RHError(f"token refresh transport error: {e!r}") from e

            at = data.get("access_token")
            if not at:
                raise RHAuthError("token refresh returned no access_token")

            new_token = {
                "access_token": at,
                "token_type": data.get("token_type", "Bearer"),
                "expires_in": int(data.get("expires_in", 0) or 0),
                "scope": data.get("scope", "internal"),
                "refresh_token": data.get("refresh_token", rt),
                "expires_at": self._now() + int(data.get("expires_in", 0) or 0),
            }
            # 1. local fallback first (the rotated token is recoverable on disk).
            _save_local_token(new_token)
            # 2. SSM (source of truth). Failure here is non-fatal: token is on disk.
            try:
                _save_ssm_token(new_token, self._region)
            except Exception as e:  # noqa: BLE001
                print(f"[rh_client] WARNING: SSM writeback failed (token on local "
                      f"file only): {e!r}", flush=True)
            self._token = new_token
            self._refreshed_at = self._now()
            return at

    def _client_id(self) -> str:
        cid = self._ssm.get("client_id") or self._token.get("client_id")
        if not cid:
            try:
                cid = json.loads(self._ssm.get("client_json", "{}")).get("client_id")
            except (ValueError, TypeError):
                cid = None
        if not cid:
            raise RHConfigError("no Robinhood client_id — re-OAuth required")
        return cid

    # ---- account resolution ----
    def _resolve_account(self, account_number: str | None = None) -> str:
        if account_number:
            return account_number
        if self.account_number:
            return self.account_number
        acct = self.get_account()
        return acct["account_number"]

    def _tool(self, name: str, **args) -> dict:
        """Call an MCP tool; on 401, refresh once and retry (token may have expired)."""
        try:
            return self._transport.call_tool(name, args)
        except RHAuthError:
            at = self.refresh()
            self._transport = self._transport_factory(at)
            initialize_transport(self._transport)
            return self._transport.call_tool(name, args)

    # ---- read-only ----
    def get_account(self, account_number: str | None = None) -> dict:
        """Return the (agentic) account dict, or a specific one.

        Prefers the ``agentic_allowed=true`` account when no number is given.
        """
        raw = self._tool("get_accounts")
        accounts = ((raw.get("data") or {}).get("accounts") or [])
        if not accounts:
            raise RHConfigError("get_accounts returned no accounts")
        if account_number:
            for a in accounts:
                if a.get("account_number") == account_number:
                    return a
            raise RHConfigError(f"account {account_number} not found")
        for a in accounts:
            if a.get("agentic_allowed"):
                return a
        return accounts[0]

    def get_positions(self, account_number: str | None = None) -> list[dict]:
        acct = self._resolve_account(account_number)
        raw = self._tool("get_equity_positions", account_number=acct)
        return ((raw.get("data") or {}).get("positions") or [])

    def get_quote(self, symbol: str) -> dict:
        raw = self._tool("get_equity_quotes", symbols=[symbol.upper()])
        results = ((raw.get("data") or {}).get("results") or [])
        if not results:
            return {}
        q = results[0].get("quote", {})
        q["close"] = results[0].get("close", {})
        return q

    def get_quotes(self, symbols: list[str]) -> list[dict]:
        raw = self._tool("get_equity_quotes", symbols=[s.upper() for s in symbols])
        return ((raw.get("data") or {}).get("results") or [])

    # ---- research (Robinhood MCP research surface — Cortex-adjacent) ----
    def get_earnings_calendar(self, start_date: str | None = None, days: int = 7,
                              high_market_cap: bool = False) -> dict:
        """Upcoming/prior earnings across the market over a date window."""
        args: dict = {"days": days}
        if start_date:
            args["start_date"] = start_date
        if high_market_cap:
            args["filter"] = "high_market_cap"
        return self._tool("get_earnings_calendar", **args)

    def get_earnings_results(self, symbol: str) -> dict:
        return self._tool("get_earnings_results", symbol=symbol.upper())

    def get_equity_fundamentals(self, symbols: list[str], bounds: str = "regular") -> dict:
        return self._tool("get_equity_fundamentals",
                          symbols=[s.upper() for s in symbols], bounds=bounds)

    def get_financials(self, symbols: list[str], period: str = "quarterly",
                       limit: int = 4) -> dict:
        return self._tool("get_financials", symbols=[s.upper() for s in symbols],
                          period=period, limit=limit)

    def get_equity_historicals(self, symbols: list[str], start_time: str,
                               end_time: str | None = None, interval: str | None = None,
                               bounds: str = "regular") -> dict:
        args: dict = {"symbols": [s.upper() for s in symbols],
                      "start_time": start_time, "bounds": bounds}
        if end_time:
            args["end_time"] = end_time
        if interval:
            args["interval"] = interval
        return self._tool("get_equity_historicals", **args)

    def get_equity_technical_indicators(self, symbol: str, type: str, interval: str,
                                        start_time: str, end_time: str | None = None,
                                        bounds: str = "regular") -> dict:
        args: dict = {"symbol": symbol.upper(), "type": type, "interval": interval,
                      "start_time": start_time, "bounds": bounds}
        if end_time:
            args["end_time"] = end_time
        return self._tool("get_equity_technical_indicators", **args)

    def get_scans(self) -> list[dict]:
        raw = self._tool("get_scans")
        return ((raw.get("data") or {}).get("scans") or raw.get("scans") or [])

    def run_scan(self, scan_id: str) -> dict:
        return self._tool("run_scan", scan_id=scan_id)

    def create_scan(self, preset: str | None = None, filters: list | None = None,
                    columns: list | None = None) -> dict:
        args: dict = {}
        if preset:
            args["preset"] = preset
        if filters:
            args["filters"] = filters
        if columns:
            args["columns"] = columns
        return self._tool("create_scan", **args)

    def list_orders(self, account_number: str | None = None, symbol: str | None = None,
                    state: str | None = None, order_id: str | None = None) -> list[dict]:
        acct = self._resolve_account(account_number)
        args = {"account_number": acct}
        if symbol:
            args["symbol"] = symbol.upper()
        if state:
            args["state"] = state
        if order_id:
            args["order_id"] = order_id
        raw = self._tool("get_equity_orders", **args)
        return ((raw.get("data") or {}).get("orders") or [])

    # ---- order placement ----
    def place_equity_order(self, symbol: str, side: str, order_type: str,
                           account_number: str | None = None, quantity: str | None = None,
                           dollar_amount: str | None = None, limit_price: str | None = None,
                           stop_price: str | None = None, time_in_force: str = "gfd",
                           market_hours: str = "regular_hours", ref_id: str | None = None,
                           client_order_ref: str | None = None) -> dict:
        """Place a real equity order (market/limit/stop_market/stop_limit).

        This is the RAW placement — it does NOT enforce the protective-stop rule;
        use ``place_equity_entry`` for protected entries. Fractional ``dollar_amount``
        is supported for MARKET orders only.
        """
        if side not in ("buy", "sell"):
            raise RHOrderError(f"invalid side {side!r}")
        if order_type not in ("market", "limit", "stop_market", "stop_limit"):
            raise RHOrderError(f"invalid order type {order_type!r}")
        if order_type in ("stop_market", "stop_limit") and not stop_price:
            raise RHStopRequired("stop order requires stop_price > 0")

        acct = self._resolve_account(account_number)
        args = {"account_number": acct, "symbol": symbol.upper(), "side": side,
                "type": order_type}
        if quantity:
            args["quantity"] = str(quantity)
        if dollar_amount:
            args["dollar_amount"] = str(dollar_amount)
        if limit_price:
            args["limit_price"] = str(limit_price)
        if stop_price:
            args["stop_price"] = str(stop_price)
        args["time_in_force"] = time_in_force
        args["market_hours"] = market_hours
        if ref_id is None and client_order_ref:
            ref_id = make_ref_id("equity", acct, symbol, side, order_type,
                                 client_order_ref)
        if ref_id:
            args["ref_id"] = ref_id
        raw = self._tool("place_equity_order", **args)
        data = raw.get("data") or raw
        return data

    def place_stop(self, symbol: str, position_side: str, quantity: int | str,
                   stop_price: float | str, stop_limit_price: float | str | None = None,
                   account_number: str | None = None, time_in_force: str = "gtc",
                   client_order_ref: str | None = None, ref_id: str | None = None) -> dict:
        """Rest a protective stop (stop_market, or stop_limit when a limit is given).

        ``position_side`` is the side of the POSITION being protected ('long' →
        SELL stop, 'short' → BUY stop). Whole-share quantity only (Robinhood
        constraint). ``stop_price`` must be > 0.
        """
        sp = float(stop_price)
        if sp <= 0:
            raise RHStopRequired("protective stop requires stop_price > 0")
        if position_side not in ("long", "short"):
            raise RHOrderError(f"invalid position_side {position_side!r}")
        order_side = "sell" if position_side == "long" else "buy"
        order_type = "stop_limit" if stop_limit_price is not None else "stop_market"
        acct = self._resolve_account(account_number)
        args = {"account_number": acct, "symbol": symbol.upper(), "side": order_side,
                "type": order_type, "quantity": str(quantity),
                "stop_price": f"{sp:.4f}", "time_in_force": time_in_force,
                "market_hours": "regular_hours"}
        if stop_limit_price is not None:
            args["limit_price"] = f"{float(stop_limit_price):.4f}"
        if ref_id is None and client_order_ref:
            ref_id = make_ref_id("stop", acct, symbol, position_side, client_order_ref)
        if ref_id:
            args["ref_id"] = ref_id
        raw = self._tool("place_equity_order", **args)
        return raw.get("data") or raw

    def cancel_order(self, order_id: str, account_number: str | None = None) -> dict:
        acct = self._resolve_account(account_number)
        return self._tool("cancel_equity_order", account_number=acct, order_id=order_id)

    # ---- fail-closed protected entry ----
    def place_equity_entry(self, symbol: str, side: str, stop_price: float,
                           account_number: str | None = None, dollar_amount: str | None = None,
                           quantity: str | None = None, order_type: str = "market",
                           limit_price: str | None = None, time_in_force: str = "gfd",
                           market_hours: str = "regular_hours",
                           stop_limit_price: float | None = None,
                           stop_time_in_force: str = "gtc",
                           client_order_ref: str | None = None) -> dict:
        """Fail-closed protected entry: entry + immediately-verified protective stop.

        1. REJECT if ``stop_price <= 0`` (never-lose-money) BEFORE placing anything.
        2. Place the entry (market/limit; fractional via ``dollar_amount`` for market).
        3. Confirm a fill (state ``filled`` or ``partially_filled``).
        4. Rest a protective stop sized to the FILLED quantity (whole shares).
        5. VERIFY the stop is resting (open stop order present). If it cannot be
           rested — including a fractional fill that rounds to <1 share — FLATTEN
           the entry and raise RHStopPlacementFailed. Never leave a naked position.
        """
        sp = float(stop_price)
        if sp <= 0:
            raise RHStopRequired("place_equity_entry requires stop_price > 0")

        acct = self._resolve_account(account_number)
        sym = symbol.upper()
        entry = self.place_equity_order(
            sym, side, order_type, account_number=acct, quantity=quantity,
            dollar_amount=dollar_amount, limit_price=limit_price,
            time_in_force=time_in_force, market_hours=market_hours,
            client_order_ref=client_order_ref)

        # Confirm the fill by POLLING — Robinhood fills are ASYNCHRONOUS.
        #
        # ROOT CAUSE OF ZERO LIVE FILLS 2026-08-20 → 2026-08-24: this used to read
        # entry['state'] ONCE from the creation response and demand 'filled'. A real
        # order's creation response comes back queued/pending (often with NO state
        # field at all -> state=''), so every single live entry raised
        # RHOrderError("entry not confirmed filled (state='')") and fail-closed.
        # 10 valid RSI2 signals were rejected this way on 2026-08-24 alone.
        #
        # Never-naked guarantee on timeout: an order left resting could fill LATER,
        # after we've given up, leaving a position with no protective stop. So on
        # timeout we CANCEL and then re-check — and if the cancel lost the race and
        # it actually filled, we fall through and protect it instead of abandoning it.
        order_id = str(entry.get("id") or entry.get("order_id") or "")
        state = (entry.get("state") or "").lower()
        TERMINAL = ("filled", "partially_filled", "rejected", "cancelled", "canceled",
                    "failed")

        # The MCP creation response can come back with NEITHER an id NOR a state.
        # Without an id the poll loop below is skipped entirely, the order is
        # reported "not confirmed", and the cancel branch has nothing to cancel —
        # while the order is LIVE at the broker and fills seconds later. That is
        # exactly how 9 unprotected positions were opened on 2026-08-25.
        # Recover the id by matching the newest order for this symbol.
        if not order_id:
            for _ in range(4):
                try:
                    recent = self.list_orders(account_number=acct, symbol=sym) or []
                except Exception:  # noqa: BLE001 - transient read, retry
                    recent = []
                cands = [o for o in recent
                         if (o.get("side") == side
                             and o.get("stop_price") in (None, "", "0", "0.000000"))]
                if cands:
                    cands.sort(key=lambda o: o.get("created_at") or "", reverse=True)
                    entry = cands[0]
                    order_id = str(entry.get("id") or "")
                    state = (entry.get("state") or "").lower()
                    if order_id:
                        break
                time.sleep(RH_FILL_POLL_S)

        def _refresh() -> str:
            """Re-read the order; returns the latest lowercase state."""
            nonlocal entry
            if not order_id:
                return state
            try:
                latest = self.list_orders(account_number=acct, order_id=order_id)
            except Exception:  # noqa: BLE001 - transient read, keep polling
                return (entry.get("state") or "").lower()
            for o in latest or []:
                if str(o.get("id") or o.get("order_id") or "") == order_id:
                    entry = o
                    break
            else:
                if latest:
                    entry = latest[0]
            return (entry.get("state") or "").lower()

        deadline = time.monotonic() + RH_FILL_TIMEOUT_S
        while state not in TERMINAL and order_id and time.monotonic() < deadline:
            time.sleep(RH_FILL_POLL_S)
            state = _refresh()

        if state in ("filled", "partially_filled") and order_id:
            # Re-read the settled order to get the real cumulative_quantity/average_price
            # — but ONLY when the creation response's fill qty is suspect ("0.000000"/
            # empty, the known gap). A healthy creation response already carries the real
            # numbers; re-reading unconditionally can overwrite `entry` with the wrong
            # order (list_orders(order_id=…) may not match).
            if _num(entry.get("cumulative_quantity")) is None:
                state = _refresh()
        else:
            if order_id and state not in ("rejected", "cancelled", "canceled", "failed"):
                try:
                    self.cancel_order(order_id, account_number=acct)
                except Exception:  # noqa: BLE001 - cancel best-effort; re-check decides
                    pass
                time.sleep(RH_FILL_POLL_S)
                state = _refresh()
            if state not in ("filled", "partially_filled"):
                if order_id:
                    raise RHOrderError(
                        f"{sym}: entry not confirmed filled within {RH_FILL_TIMEOUT_S:.0f}s "
                        f"(state={state!r}, order_id={order_id}) — cancelled")
                # No order_id: we could neither cancel nor verify — the order may be
                # LIVE and fill seconds later. Check whether a position now exists and
                # protect it; otherwise raise UNKNOWN (never claim "cancelled").
                try:
                    held = self.get_positions(account_number=acct) or []
                except Exception:  # noqa: BLE001
                    held = []
                for hp in held:
                    if ((hp.get("symbol") or "").upper() == sym.upper()
                            and _pos_qty(hp) > 0):
                        entry = {"symbol": sym, "state": "filled",
                                 "cumulative_quantity": hp.get("quantity"),
                                 "average_price": (hp.get("average_buy_price")
                                                   or hp.get("average_price"))}
                        state = "filled"
                        break
                if state not in ("filled", "partially_filled"):
                    raise RHOrderError(
                        f"{sym}: entry UNKNOWN — order_id unrecoverable and no position "
                        f"visible; VERIFY positions manually (possible live exposure)")

        filled_qty = _num(entry.get("cumulative_quantity")) \
            or _num(entry.get("quantity")) or 0.0
        position_side = "long" if side == "buy" else "short"
        stop_qty = int(filled_qty)
        # A sub-1-share OR non-whole-share fill cannot carry a whole-share stop
        # that fully protects it (floor(qty) would leave the remainder naked).
        # Reverse the entry instead (never-lose-money).
        if filled_qty < 1 or filled_qty != float(stop_qty):
            self._flatten(sym, side, account_number=acct, client_order_ref=client_order_ref,
                          qty=filled_qty, dollar_amount=dollar_amount)
            raise RHStopPlacementFailed(
                f"{sym}: fractional fill {filled_qty} cannot carry a whole-share protective "
                f"stop — entry reversed (fail-closed, never naked)")

        try:
            stop = self.place_stop(sym, position_side, stop_qty, sp,
                                   stop_limit_price=stop_limit_price,
                                   account_number=acct,
                                   time_in_force=stop_time_in_force,
                                   client_order_ref=client_order_ref)
        except Exception as e:  # noqa: BLE001
            self._flatten(sym, side, account_number=acct, client_order_ref=client_order_ref,
                          qty=filled_qty)
            raise RHStopPlacementFailed(
                f"{sym}: protective stop placement failed — entry reversed: {e!r}") from e

        if not self._stop_is_resting(sym, position_side, account_number=acct):
            self._flatten(sym, side, account_number=acct, client_order_ref=client_order_ref,
                          qty=filled_qty)
            raise RHStopPlacementFailed(
                f"{sym}: protective stop not resting after placement — entry reversed")

        return {"entry": entry, "stop": stop, "stop_qty": stop_qty}

    def _stop_is_resting(self, symbol: str, position_side: str,
                         account_number: str | None = None) -> bool:
        """True if a protective stop for ``symbol`` rests at the broker.

        Robinhood identifies a stop order by the presence of ``stop_price`` —
        it returns ``type='market'`` (with ``trigger='stop'``), NOT
        ``type='stop_market'``. Matching on STOP_TYPES therefore NEVER matched,
        so this returned False for a perfectly good resting stop and the caller
        reversed the entry. Verified against live orders 2026-08-25:
        ``{type: 'market', state: 'confirmed', stop_price: '25.520000'}``.
        A resting order's state is 'confirmed' (there is no 'open' state).
        """
        orders = self.list_orders(account_number=account_number, symbol=symbol)
        want_side = "sell" if position_side == "long" else "buy"
        for o in orders:
            has_stop = (o.get("stop_price") not in (None, "", "0", "0.000000")
                        or o.get("type") in STOP_TYPES)
            if (o.get("side") == want_side and has_stop
                    and (o.get("state") or "").lower() in ("confirmed", "queued",
                                                           "unconfirmed", "new",
                                                           "partially_filled")):
                return True
        return False

    def _flatten(self, symbol: str, entry_side: str, account_number: str | None = None,
                 client_order_ref: str | None = None, qty: float | None = None,
                 dollar_amount: str | None = None):
        """Emergency market-close of a just-filled (unprotected) entry.

        MUST carry a size: a market order with neither ``quantity`` nor
        ``dollar_amount`` is under-specified and would be rejected, stranding
        the position naked. ``qty`` (whole shares, >=1) closes via ``quantity``;
        a fractional fill closes via ``dollar_amount``.
        """
        close_side = "sell" if entry_side == "buy" else "buy"
        kw = {}
        if qty is not None and float(qty) >= 1:
            kw["quantity"] = str(int(float(qty)))
        elif dollar_amount:
            kw["dollar_amount"] = str(dollar_amount)
        else:
            raise RHNakedPosition(
                f"{symbol}: cannot flatten — no size (qty/dollar_amount) supplied")
        try:
            self.place_equity_order(symbol, close_side, "market",
                                    account_number=account_number,
                                    client_order_ref=client_order_ref, **kw)
        except Exception as e:  # noqa: BLE001
            raise RHNakedPosition(
                f"{symbol}: unable to flatten unprotected entry: {e!r}") from e

    # ---- safe simulate (verification path — places NO order) ----
    def review_equity_order(self, symbol: str, side: str, order_type: str,
                            account_number: str | None = None, quantity: str | None = None,
                            dollar_amount: str | None = None, limit_price: str | None = None,
                            stop_price: str | None = None,
                            time_in_force: str = "gfd",
                            market_hours: str = "regular_hours") -> dict:
        """Simulate an order WITHOUT placing it (returns quote + pre-trade alerts)."""
        acct = self._resolve_account(account_number)
        args = {"account_number": acct, "symbol": symbol.upper(), "side": side,
                "type": order_type, "time_in_force": time_in_force,
                "market_hours": market_hours}
        if quantity:
            args["quantity"] = str(quantity)
        if dollar_amount:
            args["dollar_amount"] = str(dollar_amount)
        if limit_price:
            args["limit_price"] = str(limit_price)
        if stop_price:
            args["stop_price"] = str(stop_price)
        raw = self._tool("review_equity_order", **args)
        return raw.get("data") or raw

    # ---- empirical fractional-stop check (READ-ONLY — places NO order) ----
    def check_fractional_stop(self, symbol: str, stop_price: float,
                              account_number: str | None = None,
                              dollar_amount: str | None = "1.00",
                              quantity: str | None = "0.5",
                              time_in_force: str = "gfd") -> dict:
        """Empirically settle whole-share-vs-fractional stops — places NO order.

        Calls ``review_equity_order`` (Robinhood's SIMULATE path) with a SELL
        ``stop_market`` for BOTH a fractional ``dollar_amount`` AND a fractional
        share ``quantity`` and reports whether the broker accepts a protective
        stop on a sub-1-share position. This is data, not assumption — the whole
        point of ``place_equity_entry`` reversing sub-1-share fills is the
        (previously unverified) claim that Robinhood stops are whole-share only.

        Returns a structured dict:
            {"symbol", "side": "sell", "order_type": "stop_market", "stop_price",
             "checks": [{label, accepted, review|detail}, ...],
             "conclusion": "ACCEPTED" | "REJECTED" | "UNKNOWN"}
        Never places an order; any MCP tool error is captured as ``accepted=False``.
        """
        sp = float(stop_price)
        checks = []
        for label, kw in (("dollar_amount", {"dollar_amount": dollar_amount}),
                          ("fractional_qty", {"quantity": quantity})):
            entry = {"label": label, "accepted": None}
            try:
                r = self.review_equity_order(
                    symbol, "sell", "stop_market", account_number=account_number,
                    stop_price=f"{sp:.4f}", time_in_force=time_in_force, **kw)
                entry["accepted"] = True
                entry["review"] = r
            except (RHOrderError, RHError) as e:  # simulate-path rejection
                entry["accepted"] = False
                entry["detail"] = str(e)[:400]
            checks.append(entry)

        accepted = [c for c in checks if c.get("accepted") is True]
        rejected = [c for c in checks if c.get("accepted") is False]
        if accepted:
            conclusion = "ACCEPTED"
        elif rejected and len(rejected) == len(checks):
            conclusion = "REJECTED"
        else:
            conclusion = "UNKNOWN"
        return {"symbol": symbol.upper(), "side": "sell", "order_type": "stop_market",
                "stop_price": sp, "checks": checks, "conclusion": conclusion}
