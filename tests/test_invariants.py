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


# ---- UNKNOWN POSITION -> no entries (reconciliation stand-down) ----
def _pos(symbol, position):
    return type('Pos', (), {'contract': type('C', (), {'symbol': symbol})(),
                            'position': position})()


class _ReconcileIB:
    def __init__(self, positions):
        self._positions = positions
        self.orders = []

    def positions(self):
        return list(self._positions)

    def sleep(self, s):
        pass

    def placeOrder(self, con, order):
        self.orders.append((con, order))


def test_invariant_reconcile_does_not_flatten_daily_mes(fake_table):
    # Daily bot holds MES (authoritative state) — reconcile must stand down, not flatten.
    from live_intraday import _reconcile, DAILY_MES_TAGS
    fake_table.items[('POSITION#MES_DONCHIAN', 'current')] = {
        'pos': 1, 'side': 'LONG', 'session_date': TODAY, 'ts': 0}
    ib = _ReconcileIB([_pos('MES', 1)])
    result = _reconcile(ib, fake_table, None, TODAY, 'PAPER')
    assert result is False
    assert ib.orders == []   # nothing flattened


def test_invariant_reconcile_unknown_position_stands_down(fake_table):
    # IBKR shows MES but no strategy (intraday or daily) state accounts for it.
    from live_intraday import _reconcile
    ib = _ReconcileIB([_pos('MES', 1)])
    result = _reconcile(ib, fake_table, None, TODAY, 'PAPER')
    assert result is False
    assert ib.orders == []   # fail-closed: no flatten off stale/unknown truth


def test_invariant_reconcile_consistent_proceeds(fake_table):
    from live_intraday import _reconcile
    fake_table.items[('POSITION#MES_DONCH15', 'current')] = {
        'pos': 1, 'side': 'LONG', 'session_date': TODAY, 'ts': 0}
    ib = _ReconcileIB([_pos('MES', 1)])
    assert _reconcile(ib, fake_table, None, TODAY, 'PAPER') is True


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
