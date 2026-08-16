#!/usr/bin/env python3
"""LAPTOP-side subscriber for the VPS→laptop SQS channel.

Runs on the LAPTOP (behind NAT). Long-polls the FIFO queue
``vps-to-laptop.fifo`` and, for every NEW report message, prints a one-line
summary and appends the full JSON to ``~/.hermes/state/vps_inbox.log``.

Dedupe: by the message's ``message_id`` (a sha256 the VPS publisher stamps into
the body) AND by the SQS ``MessageId``. Seen ids persist in
``~/.hermes/state/vps_inbox_seen.json`` so a restart doesn't re-print history.

Resilience: every receive/delete is wrapped — transient errors (network, 500s,
throttling) are logged and retried with capped exponential backoff. It never
crash-loops; it always sleeps between attempts.

Run as a plain venv loop (no root):
    ./venv/bin/python infra/laptop_inbox.py --profile <laptop-aws-profile>

One-shot drain (useful for testing / cron):
    ./venv/bin/python infra/laptop_inbox.py --once

Env: AWS_PROFILE / AWS_DEFAULT_PROFILE also honored by boto3 if --profile is
omitted. The laptop's IAM user needs sqs:ReceiveMessage + sqs:DeleteMessage +
sqs:GetQueueAttributes (+ ChangeMessageVisibility) on the queue ARN — see
docs/COMMUNICATION.md. The queue policy grants the account root principal, so
any identity in account 920641308584 with a matching identity policy can pull.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

REGION = "us-east-1"
QUEUE_URL_DEFAULT = (
    "https://sqs.us-east-1.amazonaws.com/920641308584/vps-to-laptop.fifo"
)
QUEUE_NAME = "vps-to-laptop.fifo"

# Dedup persistence + inbox log location (laptop-side).
DEFAULT_STATE_DIR = os.path.expanduser("~/.hermes/state")
LOG_PATH_DEFAULT = os.path.join(DEFAULT_STATE_DIR, "vps_inbox.log")
SEEN_PATH_DEFAULT = os.path.join(DEFAULT_STATE_DIR, "vps_inbox_seen.json")

# Long-poll + backoff tuning.
WAIT_TIME_S = 20          # SQS long-poll (near-instant delivery, cheap)
MAX_MESSAGES = 10
BASE_BACKOFF_S = 1.0
MAX_BACKOFF_S = 60.0
SEEN_PRUNE = 5000          # keep the seen set bounded (FIFO order makes old ids safe to drop)


def _ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_seen(path: str) -> set:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, list):
                return set(data)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return set()


def save_seen(path: str, seen: set) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(sorted(seen), fh)
    os.replace(tmp, path)


def append_log(log_path: str, entry: dict) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def dedup_keys(msg: dict, body: dict) -> list[str]:
    keys = [msg.get("MessageId", "")]
    # body message_id is the VPS-stamped sha256(ts|task)
    if isinstance(body, dict) and body.get("message_id"):
        keys.append(body["message_id"])
    # fallback: ts|task hash-equivalent
    if isinstance(body, dict):
        keys.append(f"{body.get('ts', '')}|{body.get('task', '')}")
    return [k for k in keys if k]


def build_client(profile: str | None, region: str):
    try:
        import boto3
    except ImportError as exc:
        raise SystemExit(
            "boto3 not installed — run: ./venv/bin/python -m pip install boto3"
        ) from exc
    session = boto3.Session(profile_name=profile, region_name=region) if profile else boto3.Session(region_name=region)
    return session.client("sqs")


def resolve_url(client, url: str | None) -> str:
    if url:
        return url
    return client.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]


def process_messages(client, url: str, seen: set, log_path: str) -> int:
    resp = client.receive_message(
        QueueUrl=url,
        MaxNumberOfMessages=MAX_MESSAGES,
        WaitTimeSeconds=WAIT_TIME_S,
        AttributeNames=["All"],
        MessageAttributeNames=["All"],
    )
    messages = resp.get("Messages", [])
    for msg in messages:
        try:
            body = json.loads(msg.get("Body", "{}"))
        except json.JSONDecodeError:
            body = {"raw": msg.get("Body", "")}

        keys = dedup_keys(msg, body)
        if seen & set(keys):
            # already processed (redelivery after a crash before delete)
            pass
        else:
            seen.update(keys)
            print(f"[vps-inbox] {body.get('ts', '?')} {body.get('task', '(no task)')}")
            append_log(log_path, body)

        # Delete AFTER processing so a crash here leaves the message for retry
        # (the persisted seen-set then dedupes the redelivery).
        client.delete_message(QueueUrl=url, ReceiptHandle=msg["ReceiptHandle"])

    # bounded seen-set (FIFO: dropping oldest is safe — we delete as we go)
    if len(seen) > SEEN_PRUNE:
        seen = set(sorted(seen)[-SEEN_PRUNE:])
    return len(messages)


def main() -> int:
    ap = argparse.ArgumentParser(description="Laptop subscriber for the VPS→laptop SQS channel.")
    ap.add_argument("--queue", default=None, help="SQS queue URL (default: the vps-to-laptop.fifo queue)")
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE"),
                    help="Laptop AWS profile name (default: $AWS_PROFILE)")
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    ap.add_argument("--once", action="store_true", help="Drain once and exit (test/cron)")
    args = ap.parse_args()

    log_path = os.path.join(args.state_dir, "vps_inbox.log")
    seen_path = os.path.join(args.state_dir, "vps_inbox_seen.json")

    client = build_client(args.profile, args.region)
    url = resolve_url(client, args.queue)

    seen = load_seen(seen_path)
    backoff = BASE_BACKOFF_S
    print(f"[vps-inbox] polling {url} (profile={args.profile or '<env>'} region={args.region})",
          flush=True)

    while True:
        try:
            n = process_messages(client, url, seen, log_path)
            backoff = BASE_BACKOFF_S  # reset on success
            if args.once:
                print(f"[vps-inbox] drained {n} message(s), exiting", flush=True)
                save_seen(seen_path, seen)
                return 0
            save_seen(seen_path, seen)
        except KeyboardInterrupt:
            print("[vps-inbox] interrupted, saving seen-set", flush=True)
            save_seen(seen_path, seen)
            return 0
        except Exception as exc:  # noqa: BLE001 — never crash-loop
            print(f"[vps-inbox] error (retrying in {backoff:.1f}s): {exc}", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
            # Re-resolve the queue URL on transient failures (in case the queue
            # was recreated while we slept).
            try:
                url = resolve_url(client, args.queue)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
