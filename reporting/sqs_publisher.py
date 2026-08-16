"""SQS publisher for the VPS→laptop direct channel.

Every task-completion report written by :func:`reporting.report.append_report`
is ALSO published to the FIFO queue ``vps-to-laptop.fifo`` the instant it
lands. The laptop long-polls that queue (``infra/laptop_inbox.py``) for
near-instant delivery — no Telegram group, no Tailscale, both sides talk to
AWS (VPS pushes, laptop pulls; the laptop is behind NAT so true push can't
reach it).

The publish is STRICTLY BEST-EFFORT: a report append must NEVER fail because
SQS is down or boto3 is missing. All failures are swallowed and logged to
stderr. The canonical files (REPORTS.md / REPORTS.json) and the GET /reports
pull endpoint remain the source of truth; SQS is a fast mirror.

Queue: FIFO (``ContentBasedDeduplication=true``). One MessageGroupId
(``reports``) preserves append order; MessageDeduplicationId is a stable
sha256 of the report ``ts``+``task`` so re-sending an entry is a no-op.
"""

import hashlib
import json
import os
import sys

# Channel identity. The queue is app-managed (created by
# infra/create_sqs_channel.py); resolve by URL first, name as fallback.
SQS_QUEUE_URL = os.environ.get(
    "SQS_QUEUE_URL",
    "https://sqs.us-east-1.amazonaws.com/920641308584/vps-to-laptop.fifo",
)
SQS_QUEUE_NAME = "vps-to-laptop.fifo"
SQS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
MESSAGE_GROUP_ID = "reports"


def _dedup_id(entry: dict) -> str:
    """Stable dedup id for a report entry (FIFO MessageDeduplicationId)."""
    raw = f"{entry.get('ts', '')}|{entry.get('task', '')}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def publish_report(entry: dict) -> bool:
    """Publish one report entry to the SQS channel. Never raises.

    Returns True on success, False on any failure (logged to stderr).
    """
    try:
        import boto3  # lazy — report.py may run under a python without boto3
    except ImportError:
        print("[sqs-publish] boto3 unavailable — skipping (best-effort)", file=sys.stderr)
        return False

    body = dict(entry)
    # Add an explicit message id so the laptop can dedupe even without the
    # SQS MessageId (e.g. if the queue is drained/recreated).
    body["message_id"] = _dedup_id(entry)

    try:
        sqs = boto3.client("sqs", region_name=SQS_REGION)
        url = SQS_QUEUE_URL
        if not url:
            url = sqs.get_queue_url(QueueName=SQS_QUEUE_NAME)["QueueUrl"]
        sqs.send_message(
            QueueUrl=url,
            MessageBody=json.dumps(body, ensure_ascii=False),
            MessageGroupId=MESSAGE_GROUP_ID,
            MessageDeduplicationId=_dedup_id(entry),
        )
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort by design
        print(f"[sqs-publish] failed (non-fatal): {exc}", file=sys.stderr)
        return False
