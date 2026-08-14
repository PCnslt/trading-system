"""pytest bootstrap: put bot/ on sys.path and provide a DynamoDB table double."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bot'))


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

    def put_item(self, Item=None, **kwargs):
        item = dict(Item or {})
        self.put_calls.append(item)
        self.items[(item.get('pk'), item.get('sk'))] = item
        return item


@pytest.fixture
def fake_table():
    return FakeTable()
