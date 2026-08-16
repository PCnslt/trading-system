#!/usr/bin/env python3
"""Idempotent creation of the VPS→laptop SQS channel (app-managed resource).

Creates (if absent):
  1. FIFO queue `vps-to-laptop.fifo` with sensible latency/retention settings.
  2. A resource (queue) policy granting:
       - the VPS role (trading-vps-role) sqs:SendMessage (publish)
       - the account root principal the receive/delete/visibility set (laptop consume)
     (the root principal is the standard SQS idiom for "any IAM identity in this account").
  3. A scoped inline IAM policy `sqs-publish-vps-to-laptop` on trading-vps-role
     (SendMessage + GetQueueUrl + GetQueueAttributes on THIS queue only), so the
     publish path is least-privilege regardless of the role's AdministratorAccess.

Run:  ./venv/bin/python infra/create_sqs_channel.py
Uses the EC2 instance role (no AWS keys on disk). Safe to re-run.
"""
import json
import sys

import boto3

REGION = "us-east-1"
ACCOUNT = "920641308584"
QUEUE_NAME = "vps-to-laptop.fifo"
ROLE_NAME = "trading-vps-role"
INLINE_POLICY_NAME = "sqs-publish-vps-to-laptop"

sqs = boto3.client("sqs", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)


def main() -> int:
    # 1. Create the FIFO queue.
    create_kwargs = dict(
        QueueName=QUEUE_NAME,
        Attributes={
            "FifoQueue": "true",
            "ContentBasedDeduplication": "true",
            "VisibilityTimeout": "60",           # laptop long-polls 20s; 60s covers processing
            "MessageRetentionPeriod": "1209600",  # 14 days
            "ReceiveMessageWaitTimeSeconds": "20",  # long-poll default
        },
    )
    url = None
    try:
        resp = sqs.create_queue(**create_kwargs)
        url = resp["QueueUrl"]
        print(f"CREATED queue {QUEUE_NAME}")
    except sqs.exceptions.QueueNameExists:
        url = sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
        print(f"EXISTS queue {QUEUE_NAME}")

    # Queue ARN (derive from URL — create_queue doesn't return ARN).
    attrs = sqs.get_queue_attributes(
        QueueUrl=url, AttributeNames=["QueueArn"]
    )["Attributes"]
    queue_arn = attrs["QueueArn"]
    print(f"Queue URL : {url}")
    print(f"Queue ARN : {queue_arn}")

    # 2. Queue (resource) policy — VPS publish + laptop consume.
    role_arn = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
    policy = {
        "Version": "2012-10-17",
        "Id": "VpsToLaptopSqsPolicy",
        "Statement": [
            {
                "Sid": "VpsPublish",
                "Effect": "Allow",
                "Principal": {"AWS": role_arn},
                "Action": [
                    "sqs:SendMessage",
                    "sqs:GetQueueAttributes",
                    "sqs:GetQueueUrl",
                ],
                "Resource": queue_arn,
            },
            {
                "Sid": "LaptopConsume",
                "Effect": "Allow",
                # root principal = "any IAM identity in this account". The laptop's
                # IAM user/role must ALSO have a matching identity-based policy.
                "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:root"},
                "Action": [
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:GetQueueAttributes",
                    "sqs:ChangeMessageVisibility",
                ],
                "Resource": queue_arn,
            },
        ],
    }
    sqs.set_queue_attributes(
        QueueUrl=url,
        Attributes={"Policy": json.dumps(policy)},
    )
    print(f"SET queue policy (VpsPublish + LaptopConsume)")

    # 3. Scoped inline IAM policy on the role (publish only).
    inline = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "sqs:SendMessage",
                    "sqs:GetQueueUrl",
                    "sqs:GetQueueAttributes",
                ],
                "Resource": queue_arn,
            }
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=INLINE_POLICY_NAME,
        PolicyDocument=json.dumps(inline),
    )
    print(f"SET inline role policy {INLINE_POLICY_NAME} on {ROLE_NAME}")

    print("\n=== DONE ===")
    print(f"queue={QUEUE_NAME} url={url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
