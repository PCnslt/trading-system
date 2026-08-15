"""Minimal S3 helpers for the data engine (own namespace, no trading imports).

Thin wrapper over boto3 put/get/list/exists. JSON serialization handles numpy
numerics and dates. Kept separate from data/s3_archive.py so the engine stays
self-contained.
"""
import json
import datetime as dt

import boto3

from . import config


def _json_default(o):
    try:
        return float(o)
    except (TypeError, ValueError):
        try:
            return o.isoformat()
        except AttributeError:
            return str(o)


_s3 = None


def client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=config.region())
    return _s3


def put_json(obj, key):
    body = json.dumps(obj, default=_json_default)
    client().put_object(Bucket=config.bucket(), Key=key, Body=body)
    return f"s3://{config.bucket()}/{key}"


def get_json(key):
    try:
        r = client().get_object(Bucket=config.bucket(), Key=key)
        return json.loads(r["Body"].read().decode("utf-8"))
    except client().exceptions.NoSuchKey:
        return None
    except Exception:
        return None


def exists(key):
    try:
        client().head_object(Bucket=config.bucket(), Key=key)
        return True
    except Exception:
        return False


def list_keys(prefix):
    """Yield all keys under a prefix (paginated)."""
    paginator = client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=config.bucket(), Prefix=prefix):
        for o in page.get("Contents", []):
            yield o["Key"]


def put_text(text, key):
    client().put_object(Bucket=config.bucket(), Key=key, Body=text.encode("utf-8"))
    return f"s3://{config.bucket()}/{key}"
