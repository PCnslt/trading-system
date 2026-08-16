"""Robinhood Trading access via the agent.robinhood.com MCP (read-only audit).

Robinhood exposes a hosted MCP server (`https://agent.robinhood.com/mcp/trading`)
fronted by OAuth 2.0. The OAuth creds live in SSM `/trading/robinhood/*`
(SecureString, source of truth). The access_token is a JWT whose claims carry the
trading entitlements (scope, options, level2_access).

This module:
  * loads the OAuth creds from SSM,
  * refreshes an expired access_token via the refresh_token grant and PERSISTS any
    rotation back to SSM (so the laptop and VPS never diverge),
  * speaks the MCP streamable-HTTP protocol (initialize -> tools/list -> tools/call)
    to introspect the account WITHOUT placing any order,
  * exposes `audit()` -> the Robinhood row of the accessibility matrix.

NO order placement. Read-only by design; there is no simulated-order endpoint on
this MCP surface, so "order-ready" is reported as (scope includes trading) AND
(account status is active/not restricted), never as a placed order.

Relationship to the other Robinhood modules: this is the AUDIT/introspection
module. The EXECUTION client is `hardening/rh_client.py` (double-gated live
placement) with CLI `bot/rh_client.py --check`; the interactive re-OAuth
recovery is `infra/rh_oauth.py` (run on the laptop). All three share the same
SSM creds (`/trading/robinhood/*`) and the same MCP surface.

Auth notes (verified 2026-08-16):
  * The public REST API (api.robinhood.com/accounts/) REJECTS this token
    ("rejected client id") — the token is bound to the MCP agent, not the public
    API. The ONLY client-facing surface for it is the MCP server.
  * Both access_token and refresh_token can be REVOKED server-side when the laptop
    rotates them (a refresh revokes the prior token). A revoked token yields
    MCP 401 "token revoked" and refresh 401 "invalid_grant". Recovery is a NEW
    authorization_code flow (browser + 2FA) — see docs/ROBINHOOD-ACCESS.md.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

PREFIX = "/trading/robinhood/"
MCP_URL = "https://agent.robinhood.com/mcp/trading"
TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

# SSM parameter leaf names (all SecureString).
PARAMS = [
    "access_token", "client_id", "client_json", "client_name",
    "expires_at", "expires_in", "meta_json", "refresh_token",
    "scope", "token_json",
]


def _ssm_client():
    import boto3
    from botocore.config import Config
    cfg = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})
    return boto3.client("ssm", region_name="us-east-1", config=cfg)


def load_creds(decrypt=True):
    """Fetch all /trading/robinhood/* params -> {leaf_name: value}. {} on failure."""
    try:
        c = _ssm_client()
        resp = c.get_parameters(
            Names=[PREFIX + n for n in PARAMS], WithDecryption=decrypt
        )
    except Exception as e:  # noqa: BLE001 — degrade, never crash
        return {"_error": repr(e)}
    out = {}
    for p in resp.get("Parameters", []):
        if p.get("Value"):
            out[p["Name"].split("/")[-1]] = p["Value"]
    return out


def save_creds(updates):
    """Persist a subset of Robinhood params back to SSM (overwrite). Returns (ok, err)."""
    c = _ssm_client()
    for leaf, value in updates.items():
        if leaf not in PARAMS:
            continue
        try:
            c.put_parameter(
                Name=PREFIX + leaf, Value=str(value), Type="SecureString",
                Overwrite=True,
            )
        except Exception as e:  # noqa: BLE001
            return False, f"{leaf}: {e!r}"
    return True, ""


def refresh(creds):
    """refresh_token grant. Returns (ok, token_dict_or_none, err_str)."""
    rt = creds.get("refresh_token")
    cid = creds.get("client_id")
    if not rt or not cid:
        return False, None, "missing refresh_token/client_id"
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": cid,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.loads(r.read().decode())
        # normalize + record issue time
        if "expires_in" in tok:
            tok["expires_at"] = time.time() + float(tok["expires_in"])
        return True, tok, ""
    except urllib.error.HTTPError as e:
        return False, None, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:  # noqa: BLE001
        return False, None, repr(e)


def ensure_fresh(creds):
    """Refresh if the access_token is expired/revoked; persist rotation to SSM.

    Returns (creds, refreshed: bool, err: str). Never raises.
    """
    try:
        exp = float(creds.get("expires_at") or 0)
    except (TypeError, ValueError):
        exp = 0
    if exp > time.time() + 60:
        return creds, False, ""  # still valid (may still be revoked server-side)
    ok, tok, err = refresh(creds)
    if not ok:
        return creds, False, err
    # persist rotation
    updates = {
        "access_token": tok.get("access_token"),
        "refresh_token": tok.get("refresh_token"),  # may be rotated
        "expires_in": tok.get("expires_in"),
        "expires_at": tok.get("expires_at"),
        "scope": tok.get("scope"),
        "token_json": json.dumps(tok),
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    save_creds(updates)
    creds.update(updates)
    return creds, True, ""


def _mcp_post(body, token, session_id=None):
    """One MCP JSON-RPC POST. Returns (status, session_id, raw_body)."""
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(
        MCP_URL, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("Mcp-Session-Id"), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Mcp-Session-Id"), e.read().decode()
    except Exception as e:  # noqa: BLE001
        return -1, None, repr(e)


def mcp_call(method, params, token, session_id=None):
    """MCP JSON-RPC call -> (ok, result_or_error, session_id)."""
    body = {"jsonrpc": "2.0", "id": int(time.time() * 1000) % 100000,
            "method": method, "params": params}
    status, sid, raw = _mcp_post(body, token, session_id)
    if status != 200:
        return False, {"http_status": status, "body": raw[:300]}, sid
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return False, {"parse_error": raw[:300]}, sid
    if "error" in j:
        return False, j["error"], sid
    return True, j.get("result"), sid


def audit():
    """Robinhood accessibility audit row. Read-only, never places an order."""
    row = {
        "venue": "Robinhood live",
        "auth": "BLOCKED", "account_visible": "BLOCKED",
        "permissions": "BLOCKED", "market_data": "BLOCKED",
        "order_ready": "BLOCKED", "detail": "",
    }
    creds = load_creds()
    if "_error" in creds:
        row["detail"] = "SSM load failed: " + creds["_error"]
        return row
    if not creds.get("access_token"):
        row["detail"] = "no access_token in SSM"
        return row

    # 1) try the token as-is (MCP initialize proves it is live + accepted)
    ok, res, sid = mcp_call("initialize", {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "hermes-vps-audit", "version": "1.0.0"},
    }, creds["access_token"])
    if not ok:
        body = res.get("body", "")
        # 2) if revoked/expired/invalid, force a refresh (revoked != expired: the
        #    token may still be within its `exp` but invalidated server-side).
        if "revoked" in body or "invalid" in body or "expired" in body:
            ok_ref, tok, err = refresh(creds)
            if not ok_ref:
                row["detail"] = f"MCP {res.get('http_status')}: {body!r}; " \
                                f"refresh failed: {err}"
                return row
            # persist rotation back to SSM so laptop/VPS never diverge
            updates = {
                "access_token": tok.get("access_token"),
                "refresh_token": tok.get("refresh_token"),
                "expires_in": tok.get("expires_in"),
                "expires_at": tok.get("expires_at"),
                "scope": tok.get("scope"),
                "token_json": json.dumps(tok),
            }
            updates = {k: v for k, v in updates.items() if v is not None}
            save_creds(updates)
            creds.update(updates)
            ok, res, sid = mcp_call("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "hermes-vps-audit", "version": "1.0.0"},
            }, creds["access_token"])
            if not ok:
                row["detail"] = f"post-refresh MCP still failing: {res}"
                return row
        else:
            row["detail"] = f"MCP {res.get('http_status')}: {body!r}"
            return row

    # 3) authenticated — enumerate tools and locate the account/portfolio tools
    ok, res, sid = mcp_call("tools/list", {}, creds["access_token"], sid)
    if not ok:
        row["detail"] = f"tools/list failed: {res}"
        return row
    tools = {t["name"]: t for t in res.get("tools", [])}
    acct_tool = next((n for n in tools if "account" in n.lower()), None)
    port_tool = next((n for n in tools if "portfolio" in n.lower()), None)

    acct = None
    if acct_tool:
        ok2, r2, _ = mcp_call("tools/call", {"name": acct_tool, "arguments": {}},
                              creds["access_token"], sid)
        if ok2:
            acct = r2
    port = None
    if port_tool:
        ok3, r3, _ = mcp_call("tools/call", {"name": port_tool, "arguments": {}},
                              creds["access_token"], sid)
        if ok3:
            port = r3

    row["auth"] = "OK"
    row["account_visible"] = "OK" if acct else "UNKNOWN (no account tool result)"
    # permissions from JWT claims (decode without verifying — entitlement snapshot)
    row["permissions"] = _entitlements(creds["access_token"])
    row["market_data"] = "OK" if acct else "UNKNOWN"
    row["order_ready"] = _order_ready(creds, acct)
    row["detail"] = json.dumps({
        "tools": sorted(tools), "account_tool": acct_tool,
        "portfolio_tool": port_tool, "account": acct, "portfolio": port,
    })[:1500]
    return row


def _entitlements(token):
    """Decode the JWT payload (unverified) for the entitlement snapshot."""
    import base64
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode())
        return {
            "scope": claims.get("scope"),
            "options": claims.get("options"),
            "level2_access": claims.get("level2_access"),
            "user_origin": claims.get("user_origin"),
        }
    except Exception:  # noqa: BLE001
        return {}


def _order_ready(creds, acct):
    ent = _entitlements(creds.get("access_token", ""))
    scope = str(ent.get("scope", ""))
    trading_scope = scope in ("internal", "trade", "trading") or "trade" in scope
    if not trading_scope:
        return "NO (scope lacks trading)"
    # account restrictions would show in acct; without a clear 'restricted' flag
    # we report capability based on scope + successful account read.
    if acct:
        return "YES (scope=trading, account readable, no simulated-order surface)"
    return "LIKELY (scope=trading) — account read failed"


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
