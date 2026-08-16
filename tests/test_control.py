"""Regression tests for the control-plane hardening (fail-closed read, read-modify-write,
global flatten acks, account/mode guard)."""
import pytest

import control


def _ctrl(state='RUNNING', flatten='false', extra=None):
    d = {'pk': 'CONTROL', 'sk': 'system', 'state': state, 'flatten': flatten}
    if extra:
        d.update(extra)
    return d


# --- 1. get_control fail-closed ---
def test_get_control_missing_raises(fake_table):
    with pytest.raises(control.ControlUnavailable):
        control.get_control(fake_table)


def test_get_control_read_error_raises(fake_table):
    class Boom:
        def get_item(self, **k):
            raise RuntimeError("network down")
    with pytest.raises(control.ControlUnavailable):
        control.get_control(Boom())


def test_get_control_returns_item(fake_table):
    fake_table.items[('CONTROL', 'system')] = _ctrl()
    assert control.get_control(fake_table)['state'] == 'RUNNING'


# --- control_state / control_allows_entry fail-closed ---
def test_control_state_unknown_is_none():
    assert control.control_state({}) is None
    assert control.control_state({'state': 'BOGUS'}) is None


def test_control_state_valid():
    assert control.control_state({'state': 'RUNNING'}) == 'RUNNING'
    assert control.control_state({'state': 'KILLED'}) == 'KILLED'


def test_control_allows_entry_only_running():
    assert control.control_allows_entry({'state': 'RUNNING'}) is True
    assert control.control_allows_entry({'state': 'PAUSED'}) is False
    assert control.control_allows_entry({'state': 'KILLED'}) is False
    assert control.control_allows_entry({}) is False


# --- wants_flatten ---
def test_wants_flatten():
    assert control.wants_flatten({'flatten': 'true', 'state': 'RUNNING'}) is True
    assert control.wants_flatten({'flatten': 'false', 'state': 'KILLED'}) is True
    assert control.wants_flatten({'flatten': 'false', 'state': 'RUNNING'}) is False


# --- account/mode guard ---
def test_account_mode_ok_paper_live_mismatch():
    ok, _ = control.account_mode_ok('LIVE', ['DUR193467'])
    assert ok is False


def test_account_mode_ok_live_account_paper_mode():
    ok, _ = control.account_mode_ok('PAPER', ['U123456'])
    assert ok is False


def test_account_mode_ok_paper_paper():
    ok, _ = control.account_mode_ok('PAPER', ['DUR193467'])
    assert ok is True


def test_account_mode_ok_live_live():
    ok, _ = control.account_mode_ok('LIVE', ['U123456'])
    assert ok is True


# --- set_control read-modify-write (dashboard bug) ---
def test_set_control_preserves_existing_flags(fake_table):
    fake_table.items[('CONTROL', 'system')] = _ctrl(state='PAUSED', flatten='true')
    control.set_control(fake_table, state='KILLED')
    saved = fake_table.items[('CONTROL', 'system')]
    assert saved['state'] == 'KILLED'          # new field applied
    assert saved['flatten'] == 'true'          # existing flag preserved
    assert saved['pk'] == 'CONTROL' and saved['sk'] == 'system'


# --- global flatten ack semantics ---
def test_flatten_not_cleared_until_all_bots_ack(fake_table):
    fake_table.items[('CONTROL', 'system')] = _ctrl(flatten='true')
    # first bot honours + acks; flag must survive
    control.ack_flatten(fake_table, 'live')
    control.clear_flatten(fake_table)
    assert fake_table.items[('CONTROL', 'system')]['flatten'] == 'true'

    # second bot acks; still not cleared
    control.ack_flatten(fake_table, 'live_bondsfx')
    control.clear_flatten(fake_table)
    assert fake_table.items[('CONTROL', 'system')]['flatten'] == 'true'

    # third bot acks; still not cleared (live_gc is the 4th bot)
    control.ack_flatten(fake_table, 'live_intraday')
    control.clear_flatten(fake_table)
    assert fake_table.items[('CONTROL', 'system')]['flatten'] == 'true'

    # fourth (final) bot acks -> cleared
    control.ack_flatten(fake_table, 'live_gc')
    control.clear_flatten(fake_table)
    assert fake_table.items[('CONTROL', 'system')]['flatten'] == 'false'
    assert 'flatten_acked' not in fake_table.items[('CONTROL', 'system')]
