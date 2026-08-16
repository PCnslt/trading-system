"""Return-channel report server — GET /reports pull endpoint for the laptop.

The laptop is behind NAT, so a true push webhook can't reach it. This lightweight
stdlib server provides the PULL half of the return channel: it serves the same
task-completion reports recorded in ``~/trading-system/REPORTS.json`` back over
HTTP. The laptop polls ``GET /reports`` and receives the latest results.

Auth — same two layers as the inbound webhook (:8644):
  1. AWS security group restricts the port to the laptop's IP (mirrors 8644 rule).
  2. HMAC-SHA256 signature over a timestamped request, using the SAME shared
     secret as the ``laptop-task`` webhook route (read from
     ``~/.hermes/webhook_subscriptions.json`` at startup; override with env
     ``REPORTS_HMAC_SECRET``).

Request signing (mirrors the webhook V2 scheme, adapted for a bodyless GET):
    canonical = f"{timestamp}.{path_with_query}"
    signature = "sha256=" + hex_hmac_sha256(secret, canonical)
    Headers:
      X-Report-Timestamp: <unix epoch seconds>
      X-Report-Signature: sha256=<hex>
    Timestamp must be within ±300s of server time (replay window).

Endpoints:
    GET /health   -> 200 {"ok": true, "service": "trading-reports"}
    GET /reports  -> 200 JSON (see below), 401 on auth failure

JSON shape of GET /reports (200):
    {
      "updated": "<ISO-8601 local>",
      "count": <int, number of reports returned>,
      "total": <int, total reports stored>,
      "reports": [
        {"ts": "<ISO-8601>", "task": "<one line>", "summary": "<done>",
         "commits": ["<sha>", ...], "blockers": ["<note>", ...]},
        ...  # newest first
      ]
    }

Query params: ``?limit=N`` (default 20, max 500), ``?since=<ISO ts>`` (only
entries strictly newer than this timestamp).
"""

import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("REPORTS_PORT", "8645"))
BIND = os.environ.get("REPORTS_BIND", "0.0.0.0")
REPLAY_WINDOW_SECONDS = 300
DEFAULT_LIMIT = 20
MAX_LIMIT = 500

_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "REPORTS.json",
)


def _load_secret() -> str:
    """Resolve the HMAC secret: env override first, else the laptop-task route."""
    env = os.environ.get("REPORTS_HMAC_SECRET", "").strip()
    if env:
        return env
    sub_path = os.path.expanduser("~/.hermes/webhook_subscriptions.json")
    try:
        with open(sub_path, "r", encoding="utf-8") as fh:
            subs = json.load(fh)
        secret = subs.get("laptop-task", {}).get("secret", "")
        if secret:
            return secret
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    raise SystemExit(
        "No HMAC secret configured: set REPORTS_HMAC_SECRET or ensure "
        "~/.hermes/webhook_subscriptions.json has a 'laptop-task' route."
    )


SECRET = _load_secret().encode("utf-8")


def _load_reports() -> list[dict]:
    try:
        with open(_JSON_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    reports = data.get("reports", []) if isinstance(data, dict) else []
    return [r for r in reports if isinstance(r, dict)]


def _verify(request: BaseHTTPRequestHandler) -> bool:
    """Constant-time HMAC-SHA256 check over '<timestamp>.<path>'."""
    ts_raw = request.headers.get("X-Report-Timestamp", "")
    sig_raw = request.headers.get("X-Report-Signature", "")
    try:
        ts = int(ts_raw)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > REPLAY_WINDOW_SECONDS:
        return False
    canonical = f"{ts}.{request.path}".encode("utf-8")
    expected = hmac.new(SECRET, canonical, hashlib.sha256).hexdigest()
    provided = sig_raw.removeprefix("sha256=").strip().lower()
    return hmac.compare_digest(provided, expected)


class ReportHandler(BaseHTTPRequestHandler):
    server_version = "trading-reports/1.0"

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"ok": True, "service": "trading-reports", "ts": time.time()})
            return
        if parsed.path != "/reports":
            self._json(404, {"error": "not found", "path": parsed.path})
            return

        if not _verify(self):
            self._json(401, {"error": "unauthorized"})
            return

        qs = urllib.parse.parse_qs(parsed.query)
        try:
            limit = int(qs.get("limit", [str(DEFAULT_LIMIT)])[0])
        except ValueError:
            limit = DEFAULT_LIMIT
        limit = max(1, min(limit, MAX_LIMIT))
        since = qs.get("since", [""])[0]

        reports = _load_reports()
        total = len(reports)
        if since:
            reports = [r for r in reports if str(r.get("ts", "")) > since]
        # Newest first ("latest task-completion reports").
        newest_first = list(reversed(reports))[:limit]

        self._json(
            200,
            {
                "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
                "count": len(newest_first),
                "total": total,
                "reports": newest_first,
            },
        )

    def log_message(self, fmt, *args):  # noqa: A003
        # Quiet access log; the gateway/journal already capture what matters.
        pass


def main() -> None:
    server = ThreadingHTTPServer((BIND, PORT), ReportHandler)
    print(f"trading-reports listening on {BIND}:{PORT} (secret={'env' if os.environ.get('REPORTS_HMAC_SECRET') else 'webhook_subscriptions.json'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
