"""Execution manager + idempotent TradeIntent tests (execution-hardening Phase 3).

Covers: deterministic signal_id/intent_id, idempotency (one signal_id -> one
accepted intent via conditional write), fill verification (full/partial/
rejected/timeout->UNKNOWN), protective-stop placement, and exit cancel-then-close.
"""
import pytest

from hardening.exec_manager import (TradeIntent, IntentStore, ExecutionManager,
                                    ExecutionResult, _conditional_put)


def make_intent(**kw):
    base = dict(scope='live', tag='MES_DONCHIAN', symbol='MES', action='BUY',
                side='LONG', qty=1, order_type='MKT', stop_price=0.0,
                contract_month='202609', bar_time='2026-08-14', signal_reason='x')
    base.update(kw)
    return TradeIntent(**base)


# ---- fakes ----
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


class _Order:
    def __init__(self, action, orderType, totalQuantity, symbol='MES'):
        self.contract = type('C', (), {'symbol': symbol})()
        self.order = type('O', (), {'action': action, 'orderType': orderType,
                                    'totalQuantity': totalQuantity})()


class FakeIB:
    def __init__(self, fill_status='Filled', fill_shares=1, fill_price=100.0):
        self.fill_status = fill_status
        self.fill_shares = fill_shares
        self.fill_price = fill_price
        self.placed = []       # every order passed to placeOrder (MarketOrder/StopOrder)
        self.open = []         # resting orders (stops)
        self.cancelled = []
        self.slept = 0

    def sleep(self, s):
        self.slept += s

    def placeOrder(self, contract, order):
        self.placed.append(order)
        fills = [_Fill(self.fill_shares, self.fill_price)] if self.fill_status == 'Filled' else []
        return FakeTrade(self.fill_status, fills)

    def openOrders(self):
        return list(self.open)

    def cancelOrder(self, o):
        self.cancelled.append(o)
        if o in self.open:
            self.open.remove(o)


def make_manager(ib, table, scope='live'):
    return ExecutionManager(ib, table, scope=scope)


# ---- TradeIntent determinism ----
def test_signal_id_deterministic_and_stable():
    a = make_intent()
    b = make_intent()
    assert a.signal_id == b.signal_id
    assert a.intent_id == b.intent_id


def test_signal_id_differs_on_action():
    assert make_intent(action='BUY').signal_id != make_intent(action='SELL').signal_id


def test_signal_id_differs_on_bar_time():
    assert make_intent(bar_time='2026-08-14').signal_id != make_intent(bar_time='2026-08-15').signal_id


def test_intent_id_differs_on_qty_but_signal_id_same():
    a = make_intent(qty=1)
    b = make_intent(qty=2)
    assert a.signal_id == b.signal_id       # same signal
    assert a.intent_id != b.intent_id       # different intent (qty differs)


# ---- IntentStore idempotency ----
def test_intent_store_accept_once(fake_table):
    store = IntentStore(fake_table)
    intent = make_intent()
    assert store.accept(intent) is True
    assert store.accept(intent) is False    # second acceptance -> duplicate
    assert store.was_accepted(intent.signal_id) is True


def test_intent_store_was_accepted_false_before(fake_table):
    store = IntentStore(fake_table)
    assert store.was_accepted(make_intent().signal_id) is False


def test_conditional_put_conflict_returns_false(fake_table):
    fake_table.put_item(Item={'pk': 'INTENT#abc', 'sk': 'accepted'})
    assert _conditional_put(fake_table, {'pk': 'INTENT#abc', 'sk': 'accepted'}) is False
    assert _conditional_put(fake_table, {'pk': 'INTENT#xyz', 'sk': 'accepted'}) is True


# ---- submit_entry ----
def test_submit_entry_filled_places_stop(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=2, fill_price=101.0)
    mgr = make_manager(ib, fake_table)
    intent = make_intent(qty=2, stop_price=95.0)
    res = mgr.submit_entry(intent, contract=None, has_stop=True, fill_timeout=8.0)
    assert res.status == 'FILLED'
    assert res.filled_qty == 2
    assert res.avg_px == pytest.approx(101.0)
    # market order + protective stop both placed
    assert len(ib.placed) == 2
    stop = ib.placed[1]
    assert stop.orderType == 'STP' and stop.action == 'SELL'


def test_submit_entry_partial_fill(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=3, stop_price=90.0), None, has_stop=True)
    assert res.status == 'PARTIAL'
    assert res.filled_qty == 1


def test_submit_entry_duplicate_is_idempotent(fake_table):
    ib = FakeIB()
    mgr = make_manager(ib, fake_table)
    intent = make_intent(qty=1, stop_price=90.0)
    first = mgr.submit_entry(intent, None, has_stop=True)
    second = mgr.submit_entry(intent, None, has_stop=True)
    assert first.status == 'FILLED'
    assert second.status == 'DUPLICATE'
    # only ONE entry order ever placed (the duplicate placed nothing)
    assert len([o for o in ib.placed if o.orderType == 'MKT']) == 1


def test_submit_entry_rejected(fake_table):
    ib = FakeIB(fill_status='Rejected')
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=90.0), None, has_stop=True)
    assert res.status == 'REJECTED'
    assert res.filled_qty == 0


def test_submit_entry_timeout_is_unknown_not_rejected(fake_table):
    ib = FakeIB(fill_status='Submitted')   # stays open -> timeout
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=90.0), None,
                           has_stop=True, fill_timeout=0.01)
    assert res.status == 'UNKNOWN'          # timeout is UNKNOWN, never "rejected"


def test_submit_entry_no_stop_when_has_stop_false(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=90.0), None, has_stop=False)
    assert res.status == 'FILLED'
    assert all(o.orderType != 'STP' for o in ib.placed)


# ---- submit_exit ----
def test_submit_exit_cancels_stop_then_closes(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=99.0)
    stop = _Order('SELL', 'STP', 1)
    ib.open.append(stop)
    mgr = make_manager(ib, fake_table)
    intent = make_intent(action='SELL', qty=1, stop_price=0.0)
    res = mgr.submit_exit(intent, None, cancel_stop=True)
    assert res.status == 'FILLED'
    assert stop in ib.cancelled                       # stop cancelled first
    assert any(o.orderType == 'MKT' and o.action == 'SELL' for o in ib.placed)


def test_submit_exit_duplicate(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=99.0)
    mgr = make_manager(ib, fake_table)
    intent = make_intent(action='SELL', qty=1)
    assert mgr.submit_exit(intent, None).status == 'FILLED'
    assert mgr.submit_exit(intent, None).status == 'DUPLICATE'


# ---- is_stop_open ----
def test_is_stop_open(fake_table):
    ib = FakeIB()
    mgr = make_manager(ib, fake_table)
    assert mgr.is_stop_open('MES', 'LONG') is False
    ib.open.append(_Order('SELL', 'STP', 1))
    assert mgr.is_stop_open('MES', 'LONG') is True
