"""Cross-broker de-dup: the same RSI2 signal must not be bought on both brokers.

Observed 2026-08-24: BB was a Robinhood signal (rsi2=0.40) AND the #2 IBKR pick, so
both lanes would have bought it the same morning at 2x intended exposure.
"""
from __future__ import annotations

import pytest

from bot.cross_broker import blocked_by_other_broker, held_by_ibkr, held_by_rh


class FakeTable:
    def __init__(self, items=None, raise_on=None):
        self.items = items or {}
        self.raise_on = raise_on

    def get_item(self, Key):  # noqa: N803 - boto3 kwarg name
        pk = Key['pk']
        if self.raise_on and self.raise_on in pk:
            raise RuntimeError("dynamo unavailable")
        it = self.items.get((pk, Key['sk']))
        return {'Item': it} if it else {}


def test_rh_lane_skips_a_name_ibkr_already_holds():
    t = FakeTable({('POSITION#BB_RSI2', 'current'): {'status': 'OPEN', 'pos': '26'}})
    blocked, why = blocked_by_other_broker(t, 'BB', 'rh')
    assert blocked and 'IBKR' in why


def test_ibkr_lane_skips_a_name_rh_already_holds():
    t = FakeTable({('RHPOS#BB', 'current'): {'status': 'OPEN'}})
    blocked, why = blocked_by_other_broker(t, 'BB', 'ibkr')
    assert blocked and 'Robinhood' in why


def test_free_symbol_is_not_blocked():
    t = FakeTable({})
    assert blocked_by_other_broker(t, 'FLG', 'rh') == (False, '')
    assert blocked_by_other_broker(t, 'FLG', 'ibkr') == (False, '')


def test_own_lane_does_not_block_itself():
    """RH holding BB must not stop the RH lane from managing BB."""
    t = FakeTable({('RHPOS#BB', 'current'): {'status': 'OPEN'}})
    blocked, _ = blocked_by_other_broker(t, 'BB', 'rh')
    assert not blocked


def test_closed_position_does_not_block():
    t = FakeTable({('RHPOS#BB', 'current'): {'status': 'CLOSED'}})
    assert blocked_by_other_broker(t, 'BB', 'ibkr') == (False, '')


def test_pending_counts_as_held():
    t = FakeTable({('RHPOS#BB', 'current'): {'status': 'PENDING'}})
    blocked, _ = blocked_by_other_broker(t, 'BB', 'ibkr')
    assert blocked


def test_lookup_failure_fails_closed():
    """A dynamo error must NOT be read as 'free to trade'."""
    t = FakeTable({}, raise_on='RHPOS#')
    blocked, why = blocked_by_other_broker(t, 'BB', 'ibkr')
    assert blocked and 'fail-closed' in why


def test_case_insensitive_symbols():
    t = FakeTable({('RHPOS#BB', 'current'): {'status': 'OPEN'}})
    assert held_by_rh(t, 'bb')
    assert not held_by_ibkr(t, 'bb')


def test_bad_lane_rejected():
    with pytest.raises(ValueError):
        blocked_by_other_broker(FakeTable(), 'BB', 'schwab')
