# VPS ↔ Laptop Communication Channels

Two independent one-way channels carry traffic between the VPS Hermes (this
box, `52.7.95.127`) and the laptop Hermes (behind NAT, no public IP). Neither
depends on the Telegram group, and neither needs a VPN like Tailscale — both
sides talk out to AWS.

| Direction | Channel | Transport | Latency |
|-----------|---------|-----------|---------|
| Laptop → VPS | inbound webhook | HTTPS `POST :8644` (HMAC-signed) | instant (push) |
| VPS → Laptop | **SQS FIFO queue** (this doc) | `vps-to-laptop.fifo` long-poll | ~instant (≤20s) |
| VPS → Laptop (legacy) | `GET /reports` on `:8645` | HTTPS pull (HMAC-signed) | on-demand |

> The laptop is behind NAT, so a true VPS→laptop push webhook is impossible.
> The SQS queue is the recommended fix: the VPS *publishes* the instant a task
> finishes, and the laptop *long-polls* (20 s) for near-instant delivery. Both
> sides connect OUT to AWS — no inbound port on the laptop.

## 1. The SQS queue (`vps-to-laptop.fifo`)

- **Queue URL**: `https://sqs.us-east-1.amazonaws.com/920641308584/vps-to-laptop.fifo`
- **ARN**: `arn:aws:sqs:us-east-1:920641308584:vps-to-laptop.fifo`
- **Type**: FIFO, `ContentBasedDeduplication=true`, visibility 60 s, retention 14 days.
- **Access** (least-privilege, two layers):
  1. **Queue (resource) policy** — grants `sqs:SendMessage` to
     `trading-vps-role` (VPS publish) and the receive/delete/visibility actions
     to the account **root principal** (the standard SQS idiom for "any IAM
     identity in this account" — the laptop's user must *also* hold an
     identity-based policy, below).
  2. **Inline IAM policy `sqs-publish-vps-to-laptop`** on `trading-vps-role` —
     scoped to `sqs:SendMessage` + `GetQueueUrl` + `GetQueueAttributes` on THIS
     queue only. (The role also has AdministratorAccess; this inline policy makes
     the publish path explicit and survivable even if that were removed.)
- Created idempotently by `infra/create_sqs_channel.py` (`./venv/bin/python
  infra/create_sqs_channel.py`). Declared in `infra/cloudformation-stack.yaml`
  (app-managed, like the S3 data lake / DynamoDB — not created by CF itself).

### Message schema

Every report message body is a JSON object identical to a `REPORTS.json` entry,
plus a `message_id` dedup stamp:

```json
{
  "ts": "2026-08-16T14:02:11-04:00",
  "task": "One-line task description",
  "summary": "What was actually done",
  "commits": ["<sha>", "..."],
  "blockers": ["<note>", "..."],
  "message_id": "sha256(ts|task) hex — stable dedup key"
}
```

FIFO attributes: `MessageGroupId="reports"` (single group → strict append
order), `MessageDeduplicationId=sha256(ts|task)` (idempotent re-send).

## 2. VPS publisher (automatic)

`reporting/report.py::append_report()` now mirrors every entry to the queue via
`reporting/sqs_publisher.py::publish_report()` — the same content that lands in
`REPORTS.md`. The publish is **best-effort**: if SQS is down or boto3 is absent,
the append still succeeds and a warning goes to stderr. `REPORTS.md` /
`REPORTS.json` / `GET /reports` remain the source of truth.

Queue URL/region can be overridden with env `SQS_QUEUE_URL` / `AWS_REGION`.

## 3. Laptop subscriber (`infra/laptop_inbox.py`)

Runs on the laptop as a plain `./venv/bin/python` loop (no root):

```bash
cd <laptop-repo>   # any checkout of trading-system that has infra/laptop_inbox.py
./venv/bin/python infra/laptop_inbox.py --profile <laptop-aws-profile>
```

- Long-polls 20 s (`WaitTimeSeconds=20`) → near-instant delivery.
- Prints a one-line summary and appends full JSON to
  `~/.hermes/state/vps_inbox.log`.
- Dedupes by `message_id` (body) **and** SQS `MessageId`; the seen-set persists
  in `~/.hermes/state/vps_inbox_seen.json`, so restarts don't re-print history.
- Never crash-loops: every receive/delete is wrapped, transient errors back off
  (1 s → 60 s) and retry.
- `--once` drains once and exits (for tests/cron).

### Laptop IAM requirement

The laptop's AWS profile must be in account `920641308584` and hold an
identity-based policy allowing, on the queue ARN above:

```json
{
  "Effect": "Allow",
  "Action": [
    "sqs:ReceiveMessage",
    "sqs:DeleteMessage",
    "sqs:GetQueueAttributes",
    "sqs:ChangeMessageVisibility"
  ],
  "Resource": "arn:aws:sqs:us-east-1:920641308584:vps-to-laptop.fifo"
}
```

(If the laptop profile already has admin/`AmazonSQSFullAccess`, that suffices —
the queue policy's root-principal grant plus an admin identity policy is enough.)

## 4. Alternatives considered (why SQS won)

| Option | Verdict |
|--------|---------|
| **AWS SQS FIFO (chosen)** | Simplest. VPS pushes, laptop long-polls 20 s. Ordering + dedup built in. No server, no certs, no long-lived connections to babysit. |
| AWS IoT Core MQTT | True bidirectional pub/sub, both sides connect out — but requires device provisioning, certificates/authorizer, and an always-on MQTT client on each side. More moving parts for a one-way report feed. |
| API Gateway WebSocket | True server push to the laptop — but needs a $connect/$default route + a persistent WS client on the laptop, and the VPS still can't "push" without the laptop holding a connection. Overkill for report delivery. |

SQS is the right size: report delivery is one-way, low-volume, and needs
ordering + dedup — exactly FIFO's sweet spot. If a *bidirectional* control plane
is ever needed (laptop and VPS exchanging live commands both ways), revisit
IoT Core MQTT.

## 5. Verification (already performed, 2026-08-16)

1. Queue created + policy + inline role policy applied (`infra/create_sqs_channel.py`).
2. VPS published a test report; `infra/laptop_inbox.py --once` received it and
   appended it to the inbox log (run on the VPS with instance-role creds to
   prove the script end-to-end; the laptop runs the identical script with its
   own `--profile`).

## 6. Repair / ops

- **Queue recreated / URL changed** — re-run `infra/create_sqs_channel.py`, or
  set `SQS_QUEUE_URL` (VPS) / `--queue` (laptop) to the new URL.
- **Laptop stops receiving** — check (a) the laptop profile has the IAM policy
  above, (b) `AWS_PROFILE` is set / `--profile` passed, (c) the queue policy
  still lists the root principal (re-run `create_sqs_channel.py`).
- **Do NOT touch** the existing `:8644` laptop→VPS webhook or the `:8645`
  `GET /reports` pull path — they are independent and unchanged.
