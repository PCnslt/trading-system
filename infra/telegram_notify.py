#!/usr/bin/env python3
"""Send a Telegram message to the owner's home channel (stdlib only, zero deps).

Reads TELEGRAM_BOT_TOKEN + TELEGRAM_HOME_CHANNEL from the Hermes env file at
RUNTIME — the token is never hardcoded here and never appears in argv/ps (it is
loaded into memory only). Safe to commit; safe to call as root.

Usage:  python3 infra/telegram_notify.py "message text"
Exit 0 on Bot API `ok:true`; non-zero on any failure (missing env, send error,
Bot API error).
"""
import json
import sys
import urllib.parse
import urllib.request

ENV_FILE = "/home/ubuntu/.hermes/.env"


def _load_env(path):
    env = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")
    except OSError as exc:
        print(f"telegram_notify: cannot read {path}: {exc}", file=sys.stderr)
    return env


def main():
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        print("telegram_notify: no message text", file=sys.stderr)
        return 2

    env = _load_env(ENV_FILE)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat = env.get("TELEGRAM_HOME_CHANNEL", "")
    if not token or not chat:
        print("telegram_notify: missing TELEGRAM_BOT_TOKEN / TELEGRAM_HOME_CHANNEL",
              file=sys.stderr)
        return 3

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — network/timeout/HTTP are all fatal here
        print(f"telegram_notify: send failed: {exc}", file=sys.stderr)
        return 4

    if body.get("ok"):
        return 0
    print(f"telegram_notify: Bot API error: {body}", file=sys.stderr)
    return 5


if __name__ == "__main__":
    sys.exit(main())
