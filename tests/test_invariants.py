"""Safety invariants from architecture-review §55, encoded as executable tests.

Each test maps to a named invariant. They exercise the actual admission/control
helpers (not copies), so a regression in the guardrails fails here.
"""
import datetime as dt

import pytest

import control
from risk import RiskEngine, RiskConfig
from execution import confirm_fill

TODAY = dt.date.today().isoformat()


# ---- KILLED / PAUSED / HALTED -> no entries ----
def test_invariant_killed_no_entries():
    assert control.control_allows_entry({'state': 'KILLED'}) is False


def test_invariant_paused_no_entries():
    assert control.control_allows_entry({'state': 'PAUSED'}) is False


def test_invariant_halted_no_entries():
    e = RiskEngine(RiskConfig())
    e.emergency_halt("reconciliation mismatch")
    assert e.can_enter()[0] is False


def test_invariant_unknown_control_no_entries():
    # unknown / missing state is fail-closed -> no entries
    assert control.control_state({}) is None
    assert control.control_allows_entry({}) is False


# ---- STALE DATA / STALE SIGNAL / DAILY LOSS -> no entries ----
def test_invariant_stale_data_no_entries():
    import time
    e = RiskEngine(RiskConfig())
    e._last_data_ts = time.time() - 9999
    assert e.can_enter()[0] is False


def test_invariant_daily_loss_limit_no_entries():
    e = RiskEngine(RiskConfig(risk_budget_usd=100_000, max_daily_loss_pct=0.02))
    e.daily_pnl = -100_000 * 0.02 - 1
    assert e.can_enter()[0] is False


# ---- ACCOUNT MISMATCH / LIVE+PAPER -> no orders ----
def test_invariant_account_mismatch_no_orders():
    assert control.account_mode_ok('LIVE', ['DUR193467'])[0] is False
    assert control.account_mode_ok('PAPER', ['U123456'])[0] is False


def test_invariant_live_account_paper_mode_no_orders():
    assert control.account_mode_ok('PAPER', ['U123456'])[0] is False


def test_invariant_paper_account_live_mode_no_orders():
    assert control.account_mode_ok('LIVE', ['DUR193467'])[0] is False


# ---- UNKNOWN POSITION -> no entries (reconciliation is read-only + fail-closed) ----
def _pos(symbol, position):
    return type('Pos', (), {'contract': type('C', (), {'symbol': symbol})(),
                            'position': position})()


class _ReconcileIB:
    """Read-only broker double for the shared reconciler (never places orders)."""

    def __init__(self, positions=None, orders=None):
        self._positions = positions or []
        self._orders = orders or []
        self.order_calls = []

    def positions(self):
        return list(self._positions)

    def openOrders(self):
        return list(self._orders)

    def executions(self):
        return []

    def fills(self):
        return []

    def placeOrder(self, con, order):
        self.order_calls.append((con, order))


def _stop_order(symbol, action, qty):
    return type('O', (), {'contract': type('C', (), {'symbol': symbol})(),
                          'order': type('D', (), {'action': action, 'orderType': 'STP',
                                                  'totalQuantity': qty})()})()


def test_invariant_reconcile_readonly_and_matches_daily_mes(fake_table):
    # Daily bot holds MES; account IS consistent -> reconcile MATCHes and never
    # places an order (reconciliation is strictly read-only, never flattens).
    from hardening.reconciler import reconcile
    fake_table.items[('POSITION#MES_DONCHIAN', 'current')] = {
        'pk': 'POSITION#MES_DONCHIAN', 'sk': 'current', 'pos': 1, 'ts': 0}
    ib = _ReconcileIB([_pos('MES', 1)], orders=[_stop_order('MES', 'SELL', 1)])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MATCH'
    assert ib.order_calls == []


def test_invariant_reconcile_unknown_position_mismatch(fake_table):
    # Broker holds MES but no internal state accounts for it -> MISMATCH (halt).
    from hardening.reconciler import reconcile
    ib = _ReconcileIB([_pos('MES', 1)])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MISMATCH'
    assert ib.order_calls == []   # fail-closed: detect, never flatten


def test_invariant_reconcile_consistent_matches(fake_table):
    from hardening.reconciler import reconcile
    fake_table.items[('POSITION#MES_DONCH15', 'current')] = {
        'pk': 'POSITION#MES_DONCH15', 'sk': 'current', 'pos': 1, 'side': 'LONG', 'ts': 0}
    ib = _ReconcileIB([_pos('MES', 1)], orders=[_stop_order('MES', 'SELL', 1)])
    r = reconcile(ib, fake_table, today_iso=TODAY)
    assert r.status == 'MATCH'


def test_invariant_daily_mes_hold_stands_down_intraday(fake_table):
    # Cross-bot guard: the intraday bot stands down when the daily bot holds MES.
    from live_intraday import _daily_mes_held
    fake_table.items[('POSITION#MES_DONCHIAN', 'current')] = {'pos': 1, 'ts': 0}
    held, tag = _daily_mes_held(fake_table)
    assert held is True and tag == 'MES_DONCHIAN'


# ---- flatten requested -> never declare FLAT until broker confirms ----
class _FlattenIB:
    def __init__(self, positions):
        self._positions = positions
        self.orders = []
        self.cancelled = []

    def sleep(self, s):
        pass

    def openOrders(self):
        return []

    def positions(self):
        return list(self._positions)

    def placeOrder(self, con, order):
        self.orders.append((con, order))

    def cancelOrder(self, o):
        self.cancelled.append(o)


def test_invariant_flatten_never_declares_flat_without_broker_confirm(fake_table):
    # Broker still reports a position after the close attempt -> state NOT reset.
    ib = _FlattenIB([_pos('MES', 1)])
    control.flatten_ibkr(ib, ['MES'], fake_table, ['MES_DONCHIAN'], TODAY, 'PAPER')
    assert ib.orders != []                       # a close was attempted
    assert fake_table.put_calls == []            # but FLAT was NOT declared


def test_invariant_flatten_declares_flat_once_confirmed(fake_table):
    ib = _FlattenIB([])                          # already flat
    control.flatten_ibkr(ib, ['MES'], fake_table, ['MES_DONCHIAN'], TODAY, 'PAPER')
    assert fake_table.put_calls != []            # state reset to flat
    assert fake_table.items[('POSITION#MES_DONCHIAN', 'current')]['pos'] == 0
