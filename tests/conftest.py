"""pytest bootstrap: put bot/ on sys.path and provide a DynamoDB table double."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))          # repo root (hardening.*)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bot'))    # bot/*


class FakeTable:
    """In-memory DynamoDB table double (get_item / put_item)."""

    def __init__(self, items=None):
        self.items = {} if items is None else items
        self.put_calls = []

    def get_item(self, Key=None, **kwargs):
        key = ((Key or {}).get('pk'), (Key or {}).get('sk'))
        if key in self.items:
            return {'Item': dict(self.items[key])}
        return {}

    def put_item(self, Item=None, ConditionExpression=None, **kwargs):
        item = dict(Item or {})
        if ConditionExpression and 'attribute_not_exists' in ConditionExpression:
            pk = item.get('pk')
            if any(k[0] == pk for k in self.items.keys()):
                from hardening.exec_manager import ConditionalWriteConflict
                raise ConditionalWriteConflict()
        self.put_calls.append(item)
        self.items[(item.get('pk'), item.get('sk'))] = item
        return item

    def scan(self, FilterExpression=None, ExpressionAttributeValues=None, **kwargs):
        """Minimal scan: supports the reconciler's single 'begins_with(pk, :p)'
        filter. Returns {'Items': [...]} for matching rows."""
        prefix = (ExpressionAttributeValues or {}).get(':p')
        items = []
        for (pk, sk), item in self.items.items():
            if prefix is None or str(pk).startswith(prefix):
                items.append(dict(item))
        return {'Items': items}

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None,
              ScanIndexForward=False, Limit=None, **kwargs):
        """Minimal query: supports 'pk = :pk' and 'pk = :pk AND begins_with(sk, :p)'."""
        eav = ExpressionAttributeValues or {}
        pk = eav.get(':pk')
        prefix = eav.get(':p')
        out = []
        for (kpk, ksk), item in self.items.items():
            if kpk != pk:
                continue
            if prefix is not None and not str(ksk).startswith(prefix):
                continue
            out.append((ksk, dict(item)))
        out.sort(key=lambda x: x[0], reverse=not ScanIndexForward)
        if Limit:
            out = out[:Limit]
        return {'Items': [it for _, it in out]}


@pytest.fixture
def fake_table():
    return FakeTable()
