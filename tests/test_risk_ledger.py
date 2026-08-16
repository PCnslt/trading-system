"""Persistent risk ledger + restart-safe RiskEngine (execution-hardening Phase 1).

Covers: fresh-day load, round-trip persistence, fail-closed read/write errors,
restart survival of daily-loss halt / consecutive-loss brake, scope isolation,
and mid-run persist failure blocking new entries.
"""
import pytest

from risk import RiskEngine, RiskConfig, realized_pnl
from hardening.risk_ledger import RiskLedger, RiskStateUnavailable


def make_cfg(**kw):
    base = dict(risk_budget_usd=100_000, risk_pct=0.01,
                max_trades_per_day=4, max_consecutive_losses=6,
                max_daily_loss_pct=0.02, max_data_staleness_s=120)
    base.update(kw)
    return RiskConfig(**base)


class FailingTable:
    """Table double that raises on get/put (for fail-closed tests)."""

    def __init__(self, fail_get=False, fail_put=False):
        self.fail_get = fail_get
        self.fail_put = fail_put

    def get_item(self, Key=None, **kw):
        if self.fail_get:
            raise RuntimeError("throttled")
        return {}

    def put_item(self, Item=None, **kw):
        if self.fail_put:
            raise RuntimeError("throttled")


# ---- ledger basics ----
def test_ledger_load_absent_returns_empty(fake_table):
    ledger = RiskLedger(fake_table, scope='live')
    assert ledger.load('2026-08-14') == {}


def test_ledger_save_then_load_roundtrip(fake_table):
    ledger = RiskLedger(fake_table, scope='live')
    ledger.save('2026-08-14', {'daily_pnl': -42.5, 'daily_trades': 2})
    state = ledger.load('2026-08-14')
    assert state['daily_pnl'] == -42.5
    assert state['daily_trades'] == 2
    # key fields are stripped on load
    assert 'pk' not in state and 'sk' not in state
    # item stored under RISK#<date>/<scope>
    key = ('RISK#2026-08-14', 'live')
    assert key in fake_table.items


def test_ledger_load_error_fail_closed():
    ledger = RiskLedger(FailingTable(fail_get=True), scope='live')
    with pytest.raises(RiskStateUnavailable):
        ledger.load('2026-08-14')


def test_ledger_save_error_fail_closed():
    ledger = RiskLedger(FailingTable(fail_put=True), scope='live')
    with pytest.raises(RiskStateUnavailable):
        ledger.save('2026-08-14', {'daily_pnl': 0.0})


def test_ledger_scopes_are_isolated(fake_table):
    a = RiskLedger(fake_table, scope='live')
    b = RiskLedger(fake_table, scope='live_intraday')
    a.save('2026-08-14', {'daily_pnl': -100.0})
    b.save('2026-08-14', {'daily_pnl': -5.0})
    assert a.load('2026-08-14')['daily_pnl'] == -100.0
    assert b.load('2026-08-14')['daily_pnl'] == -5.0


# ---- engine load ----
def test_engine_load_fresh_day(fake_table):
    e = RiskEngine.load(make_cfg(), RiskLedger(fake_table, scope='live'))
    assert e.daily_pnl == 0.0 and e.daily_trades == 0
    assert e.consecutive_losses == 0 and e.halted is False


def test_engine_load_restores_state(fake_table):
    import datetime as dt
    ledger = RiskLedger(fake_table, scope='live')
    ledger.save(dt.date.today().isoformat(), {'daily_pnl': -1500.0, 'daily_trades': 3,
                                              'consecutive_losses': 2, 'halted': True,
                                              'halt_reason': 'daily loss halt',
                                              'open_positions': 1})
    e = RiskEngine.load(make_cfg(), ledger)
    assert e.daily_pnl == -1500.0
    assert e.daily_trades == 3
    assert e.consecutive_losses == 2
    assert e.halted is True
    assert e.halt_reason == 'daily loss halt'
    assert e.open_positions == 1


def test_engine_load_read_error_raises(fake_table):
    ledger = RiskLedger(FailingTable(fail_get=True), scope='live')
    with pytest.raises(RiskStateUnavailable):
        RiskEngine.load(make_cfg(), ledger)


# ---- persistence on accounting ----
def test_engine_persists_record_fill_and_close(fake_table):
    ledger = RiskLedger(fake_table, scope='live')
    e = RiskEngine.load(make_cfg(), ledger)
    e.record_fill()
    e.record_close(-500.0)
    state = ledger.load(e._day.isoformat())
    assert state['daily_trades'] == 1
    assert state['daily_pnl'] == -500.0
    assert state['consecutive_losses'] == 1
    assert state['open_positions'] == 0


def test_engine_survives_restart(fake_table):
    ledger = RiskLedger(fake_table, scope='live')
    e1 = RiskEngine.load(make_cfg(), ledger)
    e1.record_fill()
    e1.record_fill()
    e1.record_close(-300.0)
    e1.record_close(100.0)   # win resets the brake
    # "restart" -> a brand-new engine loads the same day's ledger
    e2 = RiskEngine.load(make_cfg(), ledger)
    assert e2.daily_trades == 2
    assert e2.daily_pnl == -200.0
    assert e2.consecutive_losses == 0


def test_daily_loss_halt_survives_restart(fake_table):
    ledger = RiskLedger(fake_table, scope='live')
    e1 = RiskEngine.load(make_cfg(), ledger)
    e1.record_close(-2001.0)   # exceeds 2% of 100k -> halt
    assert e1.halted is True
    e2 = RiskEngine.load(make_cfg(), ledger)
    allowed, reason = e2.can_enter()
    assert allowed is False
    assert 'daily loss' in reason


def test_consecutive_loss_brake_survives_restart(fake_table):
    ledger = RiskLedger(fake_table, scope='live')
    cfg = make_cfg(max_trades_per_day=100)   # isolate the brake (not trades/day)
    e1 = RiskEngine.load(cfg, ledger)
    for _ in range(6):
        e1.record_fill()
        e1.record_close(-1.0)
    e2 = RiskEngine.load(cfg, ledger)
    allowed, reason = e2.can_enter()
    assert allowed is False
    assert 'consecutive-loss' in reason


# ---- fail-closed on save ----
def test_persist_error_blocks_new_entries():
    ledger = RiskLedger(FailingTable(fail_put=True), scope='live')
    e = RiskEngine.load(make_cfg(), ledger)
    e.record_fill()   # save fails -> _persist_error set
    allowed, reason = e.can_enter()
    assert allowed is False
    assert 'persistence' in reason


# ---- rollover persists a fresh day ----
def test_rollover_resets_and_persists_new_day(fake_table):
    ledger = RiskLedger(fake_table, scope='live')
    e = RiskEngine.load(make_cfg(), ledger)
    e.record_close(-999.0)
    assert e.daily_pnl == -999.0
    # simulate midnight crossing by forcing the day back one
    e._day = e._day.fromordinal(e._day.toordinal() - 1)
    allowed, reason = e.can_enter()   # triggers rollover
    assert allowed is True
    assert e.daily_pnl == 0.0
    assert e.consecutive_losses == 0
    # new day's ledger row now exists and is fresh
    assert ('RISK#' + e._day.isoformat(), 'live') in fake_table.items


def test_realized_pnl_direction():
    assert realized_pnl('LONG', 100, 110, 5.0, 2) == pytest.approx(100.0)
    assert realized_pnl('SHORT', 110, 100, 5.0, 2) == pytest.approx(100.0)
