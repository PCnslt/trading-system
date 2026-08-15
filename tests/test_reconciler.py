"""Broker reconciliation tests (execution-hardening Phase 2).

Covers MATCH / MISMATCH / UNKNOWN semantics, position drift (both directions),
protective-stop EXISTENCE on every open position, unaccounted fills, and
fail-closed broker queries.
"""
import datetime as dt

import pytest

from hardening.reconciler import (reconcile, ReconcileResult, symbol_of,
                                  signed_pos, broker_positions, expected_positions)


TODAY = '2026-08-14'


# ---- fakes ----
class _C:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakePos:
    def __init__(self, symbol, position):
        self.contract = _C(symbol=symbol)
        self.position = position


class FakeOrder:
    def __init__(self, symbol, action, orderType, qty):
        self.contract = _C(symbol=symbol)
        self.order = _C(action=action, orderType=orderType, totalQuantity=qty)


class FakeExec:
    def __init__(self, symbol, side, shares, time=None):
        self.contract = _C(symbol=symbol)
        self.side = side
        self.shares = shares
        self.time = time


class FakeIB:
    def __init__(self, positions=None, orders=None, executions=None,
                 fail_positions=False, fail_orders=False, fail_executions=False):
        self._positions = positions or []
        self._orders = orders or []
        self._executions = executions if executions is not None else []
        self.fail_positions = fail_positions
        self.fail_orders = fail_orders
        self.fail_executions = fail_executions

    def positions(self):
        if self.fail_positions:
            raise RuntimeError("connection lost")
        return self._positions

    def openOrders(self):
        if self.fail_orders:
            raise RuntimeError("connection lost")
        return self._orders

    def executions(self):
        if self.fail_executions:
            raise RuntimeError("connection lost")
        return self._executions

    def fills(self):
        if self.fail_executions:
            raise RuntimeError("connection lost")
        return self._executions


def pos_row(table, tag, pos, side=None, **extra):
    item = {'pk': f'POSITION#{tag}', 'sk': 'current', 'pos': pos, **extra}
    if side:
        item['side'] = side
    table.put_item(Item=item)


def trade_row(table, tag, sk=TODAY):
    table.put_item(Item={'pk': f'TRADE#{tag}', 'sk': sk, 'side': 'BUY', 'qty': 1})


# ---- unit helpers ----
def test_symbol_of():
    assert symbol_of('MES_DONCHIAN') == 'MES'
    assert symbol_of('MNQ_RSI2') == 'MNQ'


def test_signed_pos_long_without_side():
    assert signed_pos('MES_DONCHIAN', {'pos': 2}) == 2   # implied LONG


def test_signed_pos_short():
    assert signed_pos('MES_FADESHORT', {'pos': 1, 'side': 'SHORT'}) == -1


def test_signed_pos_unknown_side_raises():
    with pytest.raises(ValueError):
        signed_pos('MES_DONCH15', {'pos': 1})   # bidirectional, no side stored


# ---- MATCH cases ----
def test_reconcile_match_empty(fake_table):
    r = reconcile(FakeIB(), fake_table, today_iso=TODAY)
    assert r.status == 'MATCH' and r.ok


def test_reconcile_match_open_long_with_stop(fake_table):
    pos_row(fake_table, 'MES_DONCHIAN', 1)   # no side -> LONG
    ib = FakeIB(positions=[FakePos('MES', 1)],
                orders=[FakeOrder('MES', 'SELL', 'STP', 1)])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MATCH', r.reason


def test_reconcile_match_short_position(fake_table):
    pos_row(fake_table, 'MES_FADESHORT', 1, side='SHORT')
    # NEVER-LOSE-MONEY: a short rests a BUY (cover) stop.
    ib = FakeIB(positions=[FakePos('MES', -1)],
                orders=[FakeOrder('MES', 'BUY', 'STP', 1)])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MATCH', r.reason


def test_reconcile_match_rsi2_with_stop(fake_table):
    # NEVER-LOSE-MONEY: RSI2 now rests a hard stop too.
    pos_row(fake_table, 'MES_RSI2', 1)
    ib = FakeIB(positions=[FakePos('MES', 1)],
                orders=[FakeOrder('MES', 'SELL', 'STP', 1)])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MATCH', r.reason


def test_reconcile_mismatch_rsi2_missing_stop(fake_table):
    pos_row(fake_table, 'MES_RSI2', 1)
    ib = FakeIB(positions=[FakePos('MES', 1)])   # no stop -> missing -> MISMATCH
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MISMATCH'
    assert 'stop mismatch' in r.reason


# ---- MISMATCH cases ----
def test_reconcile_mismatch_broker_extra(fake_table):
    ib = FakeIB(positions=[FakePos('MES', 1)])   # internal flat
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MISMATCH'
    assert 'position drift' in r.reason


def test_reconcile_mismatch_internal_extra(fake_table):
    pos_row(fake_table, 'MES_DONCHIAN', 1)
    ib = FakeIB(positions=[])                    # broker flat
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MISMATCH'
    assert 'position drift' in r.reason


def test_reconcile_mismatch_missing_stop(fake_table):
    pos_row(fake_table, 'MES_DONCHIAN', 1)       # DONCHIAN expects a resting STP
    ib = FakeIB(positions=[FakePos('MES', 1)], orders=[])   # no stop
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MISMATCH'
    assert 'stop mismatch' in r.reason


def test_reconcile_mismatch_orphan_stop(fake_table):
    # broker has a resting STP but internal is flat -> orphan stop
    ib = FakeIB(positions=[], orders=[FakeOrder('MES', 'SELL', 'STP', 1)])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MISMATCH'
    assert 'stop mismatch' in r.reason


def test_reconcile_mismatch_unaccounted_fill(fake_table):
    # broker executed MES today, internal has NO trade today
    ib = FakeIB(positions=[],
                executions=[FakeExec('MES', 'BOT', 1, dt.datetime(2026, 8, 14, 18, 0))])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MISMATCH'
    assert 'unaccounted fills' in r.reason


def test_reconcile_no_false_positive_when_trade_recorded(fake_table):
    trade_row(fake_table, 'MES_DONCHIAN', sk=TODAY)
    ib = FakeIB(executions=[FakeExec('MES', 'BOT', 1, dt.datetime(2026, 8, 14, 18, 0))])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MATCH', r.reason


def test_reconcile_old_fill_not_flagged(fake_table):
    # yesterday's fill -> not "today", no flag
    ib = FakeIB(executions=[FakeExec('MES', 'BOT', 1, dt.datetime(2026, 8, 13, 18, 0))])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MATCH', r.reason


# ---- UNKNOWN (fail-closed) cases ----
def test_reconcile_unknown_broker_positions_fail(fake_table):
    r = reconcile(FakeIB(fail_positions=True), fake_table, today_iso=TODAY)
    assert r.status == 'UNKNOWN'
    assert not r.ok


def test_reconcile_unknown_broker_orders_fail(fake_table):
    ib = FakeIB(positions=[], fail_orders=True)
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'UNKNOWN'


def test_reconcile_unknown_executions_fail(fake_table):
    ib = FakeIB(positions=[], fail_executions=True)
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'UNKNOWN'


def test_reconcile_unknown_internal_scan_fail(fake_table):
    fake_table.scan = lambda **kw: (_ for _ in ()).throw(RuntimeError("throttled"))
    r = reconcile(FakeIB(), fake_table, today_iso=TODAY)
    assert r.status == 'UNKNOWN'


def test_reconcile_unknown_side(fake_table):
    pos_row(fake_table, 'MES_DONCH15', 1)   # no side stored -> unresolvable
    ib = FakeIB(positions=[FakePos('MES', 1)])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'UNKNOWN'
