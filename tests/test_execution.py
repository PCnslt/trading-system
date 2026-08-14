"""Fill-verification helper tests (rejection / partial / timeout / full)."""
import pytest

from execution import confirm_fill


class FakeIB:
    def __init__(self):
        self.slept = 0

    def sleep(self, s):
        self.slept += s


class _Exec:
    def __init__(self, shares, price):
        self.shares = shares
        self.price = price


class _Fill:
    def __init__(self, shares, price):
        self.execution = _Exec(shares, price)


class FakeTrade:
    def __init__(self, status='Filled', fills=None):
        self._status = status
        self.fills = fills or []

    @property
    def orderStatus(self):
        return type('OS', (), {'status': self._status})()


def test_confirm_fill_full():
    ib = FakeIB()
    t = FakeTrade('Filled', [_Fill(2, 100.0), _Fill(1, 102.0)])
    qty, avg, status = confirm_fill(ib, t)
    assert qty == 3
    assert avg == pytest.approx((200.0 + 102.0) / 3)
    assert status == 'Filled'


def test_confirm_fill_rejected_no_fill():
    ib = FakeIB()
    t = FakeTrade('Rejected')
    qty, avg, status = confirm_fill(ib, t)
    assert qty == 0 and status == 'Rejected'


def test_confirm_fill_cancelled_after_partial():
    ib = FakeIB()
    t = FakeTrade('Cancelled', [_Fill(2, 100.0)])
    qty, avg, status = confirm_fill(ib, t)
    assert qty == 2 and status == 'Cancelled'


def test_confirm_fill_timeout_returns_partial():
    ib = FakeIB()
    t = FakeTrade('Submitted', [_Fill(1, 99.0)])
    qty, avg, status = confirm_fill(ib, t, timeout=0.01)
    assert qty == 1
    assert status == 'Submitted'
