#!/usr/bin/env python3
"""Robinhood re-OAuth recovery — interactive authorization_code (PKCE) flow.

WHY: the refresh_token ROTATES on use and revokes the old access token too.
If a refresh's writeback is ever lost (or the token expires past re-auth), the
credential is unrecoverable non-interactively — the ONLY way back is a fresh
authorization_code grant, which requires the owner to log into Robinhood in a
browser.

Run this on a machine with a BROWSER and the owner's Robinhood login (the laptop,
not this headless VPS). It reuses the EXISTING client_id + redirect_uri already in
SSM (still valid — only the tokens died), generates PKCE, opens the authorization
URL, catches the redirect, exchanges the code, and writes the fresh tokens back to
SSM (and a local backup file).

Usage (on the laptop, with boto3 creds that can write /trading/robinhood/*):
    python3 infra/rh_oauth.py
    # then log in at the printed Robinhood URL and approve the access.

After this completes, the VPS client (hardening/rh_client.py) owns the token
lifecycle again (refresh + atomic SSM writeback) and stays valid indefinitely.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

RH_SSM_PREFIX = "/trading/robinhood/"
LOCAL_TOKEN_FILE = os.path.expanduser("~/.rh-token-backup.json")


def ssm_client(region=None):
    import boto3
    from botocore.config import Config
    cfg = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
    return boto3.client("ssm", region_name=region or os.getenv("AWS_REGION", "us-east-1"),
                        config=cfg)


def load_ssm(keys):
    ssm = ssm_client()
    names = [RH_SSM_PREFIX + k for k in keys]
    out = {}
    for i in range(0, len(names), 10):
        r = ssm.get_parameters(Names=names[i:i + 10], WithDecryption=True)
        for p in r.get("Parameters", []):
            out[p["Name"].removeprefix(RH_SSM_PREFIX)] = p["Value"]
    return out


def pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def build_authorize_url(auth_endpoint, client_id, redirect_uri, scope, challenge, state):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{auth_endpoint}?{urllib.parse.urlencode(params)}"


def exchange_code(token_endpoint, client_id, redirect_uri, code, verifier):
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(token_endpoint, data=body, method="POST",
                                 headers={"Content-Type":
                                          "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def persist(token: dict):
    """Write token_json + the 6 dynamic fields to SSM and the local backup."""
    expires_in = int(token.get("expires_in", 0) or 0)
    now = time.time()
    token.setdefault("expires_at", now + expires_in)
    token_json = json.dumps(token)

    with open(LOCAL_TOKEN_FILE, "w") as fh:
        json.dump(token, fh)
    os.chmod(LOCAL_TOKEN_FILE, 0o600)

    ssm = ssm_client()
    writes = {
        "token_json": token_json,
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
        "token_type": token.get("token_type", "Bearer"),
        "scope": token.get("scope", "internal"),
        "expires_at": repr(token.get("expires_at", 0.0)),
        "expires_in": str(expires_in),
    }
    for k, v in writes.items():
        if v in ("", None):
            continue
        ssm.put_parameter(Name=RH_SSM_PREFIX + k, Value=str(v),
                          Type="SecureString", Overwrite=True)
        print(f"  SSM {k}: <written len={len(str(v))}>")


def main():
    creds = load_ssm(["client_json", "meta_json", "client_id", "scope"])
    client = json.loads(creds.get("client_json", "{}"))
    meta = json.loads(creds.get("meta_json", "{}"))
    client_id = creds.get("client_id") or client.get("client_id")
    redirect_uri = (client.get("redirect_uris") or ["http://127.0.0.1:58244/callback"])[0]
    auth_endpoint = meta.get("authorization_endpoint", "https://robinhood.com/oauth")
    token_endpoint = meta.get("token_endpoint", "https://api.robinhood.com/oauth2/token/")
    scope = creds.get("scope") or meta.get("scopes_supported", ["internal"])[0]

    if not client_id:
        print("ERROR: no client_id in SSM. Re-register the client first.")
        sys.exit(1)

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    port = int(urllib.parse.urlparse(redirect_uri).port or 58244)
    auth_url = build_authorize_url(auth_endpoint, client_id, redirect_uri, scope,
                                   challenge, state)

    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(q.query)
            if q.path != urllib.parse.urlparse(redirect_uri).path:
                self.send_response(404); self.end_headers(); return
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

    print("=" * 72)
    print("Robinhood re-OAuth (PKCE). Open this URL in your browser and log in:")
    print()
    print("  ", auth_url)
    print()
    print("Waiting for the redirect callback on", redirect_uri, "...")
    print("=" * 72)

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 300  # 5 min to complete login
    while "code" not in result and "error" not in result:
        server.handle_request()

    if "error" in result:
        print("ERROR: authorization failed:", result["error"])
        sys.exit(2)
    if result.get("state") != state:
        print("ERROR: state mismatch (CSRF) — aborting.")
        sys.exit(2)

    code = result["code"]
    print("Got authorization code. Exchanging for tokens...")
    status, tok = exchange_code(token_endpoint, client_id, redirect_uri, code, verifier)
    if status != 200 or not isinstance(tok, dict) or not tok.get("access_token"):
        print(f"ERROR: token exchange failed ({status}): {str(tok)[:500]}")
        sys.exit(3)

    # Normalize to the canonical token_json shape (mirrors the original 6 fields).
    token = {
        "access_token": tok["access_token"],
        "token_type": tok.get("token_type", "Bearer"),
        "expires_in": int(tok.get("expires_in", 0) or 0),
        "scope": tok.get("scope", scope),
        "refresh_token": tok.get("refresh_token", ""),
        "expires_at": time.time() + int(tok.get("expires_in", 0) or 0),
    }
    persist(token)
    print("\nRe-OAuth complete. Fresh tokens written to SSM +", LOCAL_TOKEN_FILE)
    print("The VPS client (hardening/rh_client.py) will pick them up on next run.")


if __name__ == "__main__":
    main()
