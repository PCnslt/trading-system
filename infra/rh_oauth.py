#!/usr/bin/env python3
"""Robinhood OAuth — VPS-owned re-authentication (SINGLE-WRITER token store).

WHY (see research/ROBINHOOD_IBKR_RESEARCH.md):
  The Robinhood ``refresh_token`` is SINGLE-USE / rotating — every refresh issues
  a new refresh_token and immediately revokes the old access_token too. Two
  processes sharing one token store therefore poison each other. The fix is
  SINGLE-WRITER discipline: ONLY this VPS holds/rotates the live token under
  ``/trading/robinhood/*``. The laptop MCP is RETIRED for trading and may only
  READ SSM to confirm state.

  The initial consent needs a desktop browser ONCE (Robinhood login + 2FA), which
  is owner-gated. This script runs the OAuth *client* side on the VPS: it
  DCR-registers (see below), prints the authorization URL + an ``ssh -L``
  port-forward command so the OWNER can complete consent from the laptop browser,
  and listens on the loopback port for the redirect. It NEVER opens a browser or
  performs the login itself.

DCR — SINGLETON CLIENT (verified 2026-08-16):
  POST https://agent.robinhood.com/oauth/trading/register returns the SAME
  well-known ``client_id`` (``LtLiNmbs9owbYfWgBlC68Z2VujIPuvGoAiSYr8xW``) no matter
  what client_name/redirect_uri you send — Robinhood's hosted MCP has ONE shared
  OAuth client. It DOES echo back the caller's ``redirect_uri``, so the loopback
  port is caller-chosen. This script therefore re-registers (idempotent) on every
  reauth and uses the returned redirect_uri, never assuming a stale SSM value.

CLI:
  python3 infra/rh_oauth.py --check                    # read-only token/client state
  python3 infra/rh_oauth.py --reauth [--port 58245]    # DCR + PKCE + loopback listener
      (--check is the default when no flag is given; --reauth requires the flag)

Token persistence (single-writer, crash-safe): LOCAL file first
(``~/.rh-token-backup.json``), THEN SSM — so a partial SSM write can never strand
a rotated token. ``expires_at`` is stored as a plain integer-seconds string.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

RH_SSM_PREFIX = "/trading/robinhood/"
LOCAL_TOKEN_FILE = os.path.expanduser("~/.rh-token-backup.json")

DEFAULT_PORT = 58245                      # distinct from the retired laptop's 58244
REGISTRATION_ENDPOINT = "https://agent.robinhood.com/oauth/trading/register"
AUTH_ENDPOINT = "https://robinhood.com/oauth"
TOKEN_ENDPOINT = "https://api.robinhood.com/oauth2/token/"
MCP_URL = "https://agent.robinhood.com/mcp/trading"
SCOPE = "internal"
VPS_HOST = os.getenv("RH_SSH_HOST", "ubuntu@52.7.95.127")

# Dynamic token fields (rotate on refresh) — written back together.
TOKEN_FIELDS = ("access_token", "refresh_token", "token_type", "scope",
                "expires_at", "expires_in", "token_json")
# Static OAuth client fields (do not rotate).
STATIC_FIELDS = ("client_id", "client_name", "client_json", "meta_json")


def ssm_client(region=None):
    import boto3
    from botocore.config import Config
    cfg = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
    return boto3.client("ssm", region_name=region or os.getenv("AWS_REGION", "us-east-1"),
                        config=cfg)


def load_ssm(keys, region=None):
    """Read /trading/robinhood/<key> params -> {leaf: value}. {} on failure."""
    ssm = ssm_client(region)
    names = [RH_SSM_PREFIX + k for k in keys]
    out = {}
    try:
        for i in range(0, len(names), 10):
            r = ssm.get_parameters(Names=names[i:i + 10], WithDecryption=True)
            for p in r.get("Parameters", []):
                if p.get("Value"):
                    out[p["Name"].removeprefix(RH_SSM_PREFIX)] = p["Value"]
    except Exception as e:  # noqa: BLE001
        print(f"[rh_oauth] SSM read failed ({e!r})", flush=True)
    return out


def save_ssm(writes: dict, region=None) -> None:
    """Write {leaf: value} to SSM SecureString (overwrite). Raises on failure."""
    ssm = ssm_client(region)
    for key, value in writes.items():
        if value in ("", None):
            continue
        ssm.put_parameter(Name=RH_SSM_PREFIX + key, Value=str(value),
                          Type="SecureString", Overwrite=True)


def _save_local_token(token: dict) -> None:
    d = os.path.dirname(LOCAL_TOKEN_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(LOCAL_TOKEN_FILE, "w", encoding="utf-8") as fh:
        json.dump(token, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(LOCAL_TOKEN_FILE, 0o600)


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def dcr_register(port: int) -> dict:
    """DCR-register (idempotent singleton client) with a loopback redirect_uri.

    Returns the registration response (client_id, client_name, redirect_uris, …).
    Robinhood's hosted MCP always returns the SAME well-known client_id; the
    redirect_uri is echoed back from our request (so the loopback port is ours).
    """
    payload = {
        "client_name": "Robinhood Trading",
        "redirect_uris": [f"http://127.0.0.1:{port}/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    req = urllib.request.Request(
        REGISTRATION_ENDPOINT, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode())
    if not data.get("client_id"):
        raise RuntimeError(f"DCR returned no client_id: {data}")
    return data


def build_authorize_url(client_id: str, redirect_uri: str, scope: str,
                        challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def exchange_code(client_id: str, redirect_uri: str, code: str, verifier: str) -> dict:
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(TOKEN_ENDPOINT, data=body, method="POST",
                                 headers={"Content-Type":
                                          "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def persist_token(token: dict) -> None:
    """Write the fresh token: LOCAL file first, then SSM (single-writer)."""
    expires_in = int(token.get("expires_in", 0) or 0)
    token["expires_at"] = int(time.time() + expires_in)
    _save_local_token(token)
    writes = {
        "token_json": json.dumps(token),
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
        "token_type": token.get("token_type", "Bearer"),
        "scope": token.get("scope", SCOPE),
        "expires_at": str(int(token.get("expires_at", 0))),
        "expires_in": str(expires_in),
    }
    save_ssm(writes)
    print("  [persist] token written to local file + SSM (VPS single-writer)", flush=True)


def _mcp_live(access_token: str) -> str:
    """Read-only MCP initialize probe -> 'live' | 'revoked' | 'expired' | error."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "trading-vps", "version": "1.0"}}}
    req = urllib.request.Request(
        MCP_URL, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + access_token,
                 "Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return "live" if resp.status == 200 else f"http {resp.status}"
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        if "revoked" in detail:
            return "revoked"
        if "expired" in detail or "invalid" in detail:
            return "expired/invalid"
        return f"http {e.code}: {detail}"
    except Exception as e:  # noqa: BLE001
        return f"error: {e!r}"


def check() -> int:
    """Read-only diagnostics: token + client state, MCP liveness, next step."""
    creds = load_ssm(list(TOKEN_FIELDS + STATIC_FIELDS))
    at = creds.get("access_token", "")
    rt = creds.get("refresh_token", "")
    cid = creds.get("client_id", "")
    client_json = json.loads(creds.get("client_json", "{}")) if creds.get("client_json") else {}
    exp = creds.get("expires_at", "")

    print("=" * 72)
    print("Robinhood token store — read-only check (single-writer = this VPS)")
    print("=" * 72)
    print(f"  client_id      : {cid[:8]}...{cid[-4:] if len(cid) > 14 else cid}")
    print(f"  redirect_uris  : {client_json.get('redirect_uris')}")
    print(f"  access_token   : {'present (len=' + str(len(at)) + ')' if at else 'MISSING'}")
    print(f"  refresh_token  : {'present (len=' + str(len(rt)) + ')' if rt else 'MISSING'}")
    print(f"  expires_at     : {exp or 'MISSING'}"
          + (f" (expired {int((float(exp) - time.time()) // 3600)}h ago)" if exp else ""))

    if not at:
        print("\n  STATUS: no access_token — re-auth required.")
        print("  NEXT  : python3 infra/rh_oauth.py --reauth")
        return 1
    live = _mcp_live(at)
    print(f"  MCP initialize : {live}")
    if live == "live":
        print("\n  STATUS: token is LIVE. Single-writer token store is healthy.")
        return 0
    print("\n  STATUS: token is NOT live (revoked/expired) — re-auth required.")
    print("  NEXT  : python3 infra/rh_oauth.py --reauth")
    return 1


def reauth(port: int) -> int:
    """DCR + PKCE + loopback listener. Prints URL + ssh port-forward; waits for consent.

    Does NOT run a browser — the owner completes consent from the laptop via:
        ssh -L <port>:127.0.0.1:<port> ubuntu@52.7.95.127
    """
    print("=" * 72)
    print("Robinhood re-auth (VPS single-writer) — DCR + PKCE + loopback")
    print("=" * 72)

    # 1. DCR-register (idempotent singleton client) -> canonical client_id + redirect.
    print(f"[1/5] DCR-registering client (loopback redirect :{port}) ...")
    reg = dcr_register(port)
    client_id = reg["client_id"]
    redirect_uri = (reg.get("redirect_uris") or [f"http://127.0.0.1:{port}/callback"])[0]
    print(f"      client_id    = {client_id}")
    print(f"      redirect_uri = {redirect_uri}")

    # Record the (single-writer) client registration in SSM so the store is coherent.
    try:
        save_ssm({
            "client_id": client_id,
            "client_name": reg.get("client_name", "Robinhood Trading"),
            "client_json": json.dumps(reg),
            "meta_json": json.dumps({
                "issuer": MCP_URL,
                "authorization_endpoint": AUTH_ENDPOINT,
                "token_endpoint": TOKEN_ENDPOINT,
                "registration_endpoint": REGISTRATION_ENDPOINT,
                "scopes_supported": [SCOPE],
            }),
        })
        print("      client registration written to SSM (VPS single-writer)")
    except Exception as e:  # noqa: BLE001
        print(f"      WARNING: could not persist client registration to SSM: {e!r}")

    # 2. PKCE + state.
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_url = build_authorize_url(client_id, redirect_uri, SCOPE, challenge, state)
    cb_path = urllib.parse.urlparse(redirect_uri).path
    cb_port = urllib.parse.urlparse(redirect_uri).port or port

    # 3. Loopback listener (catches the redirect after the owner consents).
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(q.query)
            if q.path != cb_path:
                self.send_response(404)
                self.end_headers()
                return
            if query.get("error"):
                result["error"] = query["error"][0]
                body = b"Authorization failed. You can close this tab."
            else:
                result["code"] = query.get("code", [""])[0]
                result["state"] = query.get("state", [""])[0]
                body = b"Authorized. You can close this tab and return to the terminal."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence request logs
            pass

    # 4. Print the owner-facing instructions.
    print()
    print("[2/5] OWNER ACTION — complete consent from the LAPTOP (not this VPS):")
    print("      Step 1: open a terminal on the laptop and run the port-forward:")
    print(f"          ssh -L {cb_port}:127.0.0.1:{cb_port} {VPS_HOST}")
    print("      Step 2: in the laptop's browser, open this URL and log in:")
    print()
    print(f"          {auth_url}")
    print()
    print(f"[3/5] Listening on {redirect_uri} for the redirect ...")
    print(f"      (timeout 10 min; press Ctrl-C to abort)")
    print("=" * 72)

    server = HTTPServer(("127.0.0.1", cb_port), Handler)
    server.timeout = 600  # 10 min
    deadline = time.time() + 600
    try:
        while "code" not in result and "error" not in result and time.time() < deadline:
            server.handle_request()
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    finally:
        server.server_close()

    if "error" in result:
        print(f"\nERROR: authorization failed: {result['error']}")
        return 2
    if "code" not in result:
        print("\nERROR: timed out waiting for consent — re-run --reauth.")
        return 2
    if result.get("state") != state:
        print("\nERROR: state mismatch (CSRF) — aborting. Re-run --reauth.")
        return 2

    # 5. Exchange code -> tokens, persist local-first then SSM.
    print("[4/5] Got authorization code. Exchanging for tokens ...")
    try:
        tok = exchange_code(client_id, redirect_uri, result["code"], verifier)
    except urllib.error.HTTPError as e:
        print(f"ERROR: token exchange failed (HTTP {e.code}): {e.read().decode()[:400]}")
        return 3
    if not tok.get("access_token"):
        print(f"ERROR: token exchange returned no access_token: {str(tok)[:400]}")
        return 3

    token = {
        "access_token": tok["access_token"],
        "token_type": tok.get("token_type", "Bearer"),
        "expires_in": int(tok.get("expires_in", 0) or 0),
        "scope": tok.get("scope", SCOPE),
        "refresh_token": tok.get("refresh_token", ""),
        "expires_at": int(time.time() + int(tok.get("expires_in", 0) or 0)),
    }
    persist_token(token)
    print("[5/5] Re-auth complete. Fresh token written to local file + SSM.")
    print(f"      client_id = {client_id}")
    print("      The VPS client (hardening/rh_client.py) picks it up on next run.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Robinhood VPS single-writer OAuth")
    ap.add_argument("--check", action="store_true", help="read-only token/client state (default)")
    ap.add_argument("--reauth", action="store_true", help="DCR + PKCE + loopback; owner consents from laptop")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"loopback port (default {DEFAULT_PORT})")
    args = ap.parse_args()

    if args.reauth:
        return reauth(args.port)
    return check()


if __name__ == "__main__":
    sys.exit(main())
