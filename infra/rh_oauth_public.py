#!/usr/bin/env python3
"""Robinhood OAuth re-auth — PUBLIC redirect (no SSH, no laptop script).

Binds 0.0.0.0:58245 with redirect_uri = http://<public-ip>:58245/callback so the
browser redirect lands directly on the VPS and the code is exchanged immediately
(avoids the short authorization-code TTL). Requires port 58245 open in the SG.

Single-writer: this VPS writes the fresh token to SSM /trading/robinhood/*.
"""
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import boto3

PUBLIC_IP = os.getenv("RH_PUBLIC_IP", "52.7.95.127")
PORT = 58245
REG = "https://agent.robinhood.com/oauth/trading/register"
AUTH = "https://robinhood.com/oauth"
TOKEN = "https://api.robinhood.com/oauth2/token/"
REDIRECT = f"http://{PUBLIC_IP}:{PORT}/callback"
SSM_PREFIX = "/trading/robinhood/"


def dcr():
    payload = {"client_name": "Robinhood Trading", "redirect_uris": [REDIRECT],
               "token_endpoint_auth_method": "none",
               "grant_types": ["authorization_code", "refresh_token"],
               "response_types": ["code"]}
    req = urllib.request.Request(REG, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json"}, method="POST")
    d = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    return d["client_id"], (d.get("redirect_uris") or [REDIRECT])[0]


def pkce():
    v = base64.urlsafe_b64encode(os.urandom(48)).decode().rstrip("=")
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    return v, c


def persist(tok):
    expires_in = int(tok.get("expires_in", 0) or 0)
    tok["expires_at"] = int(time.time() + expires_in)
    lp = os.path.expanduser("~/.rh-token-backup.json")
    with open(lp, "w") as f:
        json.dump(tok, f)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(lp, 0o600)
    ssm = boto3.client("ssm", region_name="us-east-1")
    writes = {"token_json": json.dumps(tok), "access_token": tok.get("access_token", ""),
              "refresh_token": tok.get("refresh_token", ""),
              "token_type": tok.get("token_type", "Bearer"),
              "scope": tok.get("scope", "internal"),
              "expires_at": str(int(tok.get("expires_at", 0))),
              "expires_in": str(expires_in)}
    for k, v in writes.items():
        if v not in ("", None):
            ssm.put_parameter(Name=SSM_PREFIX + k, Value=str(v),
                              Type="SecureString", Overwrite=True)
    print("persisted to SSM", flush=True)


def main():
    client_id, redirect = dcr()
    verifier, challenge = pkce()
    state = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")
    url = AUTH + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "scope": "internal", "code_challenge": challenge,
        "code_challenge_method": "S256", "state": state})
    print("AUTH_URL_BEGIN")
    print(url)
    print("AUTH_URL_END", flush=True)

    result = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            pq = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if pq.get("error"):
                result["error"] = pq["error"][0]
                body = b"Authorization failed. Close this tab."
            else:
                result["code"] = pq.get("code", [""])[0]
                result["state"] = pq.get("state", [""])[0]
                body = b"Authorized. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("0.0.0.0", PORT), H)
    srv.timeout = 600
    deadline = time.time() + 600
    try:
        while "code" not in result and "error" not in result and time.time() < deadline:
            srv.handle_request()
    finally:
        srv.server_close()

    if "error" in result:
        print("ERROR", result["error"])
        return 2
    if "code" not in result:
        print("TIMEOUT")
        return 2
    if result["state"] != state:
        print("STATE MISMATCH")
        return 2
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": result["code"],
        "redirect_uri": redirect, "client_id": client_id,
        "code_verifier": verifier}).encode()
    req = urllib.request.Request(TOKEN, data=body, method="POST",
                                 headers={"Content-Type":
                                          "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    try:
        tok = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    except urllib.error.HTTPError as e:
        print("EXCHANGE HTTP", e.code, e.read().decode()[:300])
        return 3
    if not tok.get("access_token"):
        print("NO TOKEN", str(tok)[:400])
        return 3
    persist(tok)
    print("SUCCESS - token live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
