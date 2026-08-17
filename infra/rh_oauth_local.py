#!/usr/bin/env python3
"""Robinhood OAuth re-auth — LOCAL runner (no SSH, no VPS, no boto3).

Run this ON YOUR MAC. It completes the OAuth consent in your browser (the
loopback redirect lands on YOUR machine, so no ssh -L tunnel is needed),
exchanges the code for tokens, and prints the token JSON.

Paste that JSON back in chat — the VPS writes it to SSM (single-writer).

Stdlib only: Python 3.7+ with no third-party deps.
"""
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 58245
REG = "https://agent.robinhood.com/oauth/trading/register"
AUTH = "https://robinhood.com/oauth"
TOKEN = "https://api.robinhood.com/oauth2/token/"
SCOPE = "internal"
REDIRECT = f"http://127.0.0.1:{PORT}/callback"


def dcr_register():
    payload = {
        "client_name": "Robinhood Trading",
        "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    req = urllib.request.Request(
        REG, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode())
    client_id = data.get("client_id")
    if not client_id:
        raise RuntimeError(f"DCR returned no client_id: {data}")
    redirect = (data.get("redirect_uris") or [REDIRECT])[0]
    return client_id, redirect


def pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def main():
    client_id, redirect = dcr_register()
    verifier, challenge = pkce_pair()
    state = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")

    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    auth_url = f"{AUTH}?{params}"

    print("=" * 70)
    print("Opening your browser to Robinhood for consent...")
    print("If it doesn't open, copy this URL into your browser:")
    print()
    print(auth_url)
    print()
    print("Log in, approve, and the redirect will land here automatically.")
    print("=" * 70)
    webbrowser.open(auth_url)

    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(q.query)
            if query.get("error"):
                result["error"] = query["error"][0]
                body = b"Authorization failed. You can close this tab."
            else:
                result["code"] = query.get("code", [""])[0]
                result["state"] = query.get("state", [""])[0]
                body = b"Authorized. Close this tab and return to the terminal."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    server.timeout = 600
    deadline = time.time() + 600
    try:
        while "code" not in result and "error" not in result and time.time() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    if "error" in result:
        print(f"\nERROR: authorization failed: {result['error']}")
        return 2
    if "code" not in result:
        print("\nERROR: timed out waiting for consent.")
        return 2
    if result.get("state") != state:
        print("\nERROR: state mismatch (CSRF).")
        return 2

    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": redirect,
        "client_id": client_id,
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(TOKEN, data=body, method="POST",
                                 headers={"Content-Type":
                                          "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    try:
        tok = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    except urllib.error.HTTPError as e:
        print(f"ERROR: token exchange failed (HTTP {e.code}): "
              f"{e.read().decode()[:400]}")
        return 3
    if not tok.get("access_token"):
        print(f"ERROR: no access_token: {str(tok)[:400]}")
        return 3

    print()
    print("=" * 70)
    print("SUCCESS. Copy EVERYTHING between the --- markers and paste it back")
    print("in chat (the VPS will write it to SSM).")
    print("=" * 70)
    print("--- BEGIN TOKEN ---")
    print(json.dumps(tok))
    print("--- END TOKEN ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
