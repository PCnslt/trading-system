"""GC gold momentum paper-execution bot tests (bot/live_gc.py).

Covers the NEW entry paths (Donchian long/short + TSMOM long/short): each
produces a positive protective stop distance from close (never-lose-money —
so exec_manager.submit_entry's stop_price<=0 rejection can never trip), the
chandelier trail ratchets only in the profitable direction (long up / short
down), and the TSMOM exit flips on a 12m-return sign change.
"""
import pytest

from live_gc import (donchian_desired, donchian_stop, donchian_trail,
                     donchian_exit, tsmom_desired, tsmom_stop, tsmom_exit,
                     STRATEGIES, resolve_contract_config, _DEFAULT_POINT_VALUE)
from risk import realized_pnl


def _detail(close=4400.0, don_hi=4350.0, don_lo=4200.0, atr=75.0, ret_12m=0.3):
    return {'close': close, 'don_hi': don_hi, 'don_lo': don_lo,
            'atr': atr, 'ret_12m': ret_12m}


# ---- Donchian desired (bidirectional) ----
def test_donchian_desired_long():
    assert donchian_desired(_detail(close=4400.0, don_hi=4350.0))[0] == 'LONG'


def test_donchian_desired_short():
    assert donchian_desired(_detail(close=4000.0, don_lo=4200.0))[0] == 'SHORT'


def test_donchian_desired_none_within_range():
    assert donchian_desired(_detail(close=4300.0, don_hi=4350.0, don_lo=4200.0))[0] is None


# ---- never-lose-money: every new entry path rests a positive stop distance ----
def test_donchian_stop_long_below_close():
    d = _detail(close=4400.0, atr=75.0)
    stop = donchian_stop(d, 'LONG')
    assert 0 < stop < d['close']


def test_donchian_stop_short_above_close():
    d = _detail(close=4400.0, atr=75.0)
    assert donchian_stop(d, 'SHORT') > d['close']


def test_tsmom_stop_long_below_close():
    d = _detail(close=4400.0, atr=75.0)
    stop = tsmom_stop(d, 'LONG')
    assert 0 < stop < d['close']


def test_tsmom_stop_short_above_close():
    d = _detail(close=4400.0, atr=75.0)
    assert tsmom_stop(d, 'SHORT') > d['close']


def test_all_strategies_rest_positive_stop_for_both_sides():
    # Guarantees submit_entry's never-lose-money chokepoint (reject stop_price<=0)
    # can never refuse a GC entry for lack of a stop: every strategy x side x
    # price level yields a positive, non-zero stop distance from close.
    for s in STRATEGIES:
        for side in ('LONG', 'SHORT'):
            for close in (2000.0, 4400.0, 6000.0):
                d = _detail(close=close, atr=50.0)
                stop = s['stop'](d, side)
                assert stop > 0
                assert abs(d['close'] - stop) > 0


# ---- chandelier trail: tighten-only (long up / short down) ----
def test_donchian_trail_long_ratchets_up():
    d = _detail(close=4500.0, atr=75.0)
    state = {'entry': '4400', 'peak': '4450'}
    new_stop, new_ext, _ = donchian_trail(d, state, 'LONG')
    assert new_ext == 4500.0
    assert new_stop == pytest.approx(4500.0 - 3 * 75.0)


def test_donchian_trail_short_ratchets_down():
    d = _detail(close=4300.0, atr=75.0)
    state = {'entry': '4400', 'trough': '4350'}
    new_stop, new_ext, _ = donchian_trail(d, state, 'SHORT')
    assert new_ext == 4300.0
    assert new_stop == pytest.approx(4300.0 + 3 * 75.0)


# ---- TSMOM desired + exit ----
def test_tsmom_desired_long():
    assert tsmom_desired(_detail(ret_12m=0.3))[0] == 'LONG'


def test_tsmom_desired_short():
    assert tsmom_desired(_detail(ret_12m=-0.2))[0] == 'SHORT'


def test_tsmom_desired_none_flat():
    assert tsmom_desired(_detail(ret_12m=0.0))[0] is None


def test_tsmom_exit_flips_on_sign_change():
    d = _detail(close=4400.0, atr=75.0, ret_12m=-0.2)
    assert tsmom_exit(d, 'LONG', 4100.0, 3, 'SHORT')[0] is True


def test_tsmom_exit_holds_same_sign():
    d = _detail(close=4400.0, atr=75.0, ret_12m=0.3)
    assert tsmom_exit(d, 'LONG', 4100.0, 3, 'LONG')[0] is False


# ---- Donchian exit ----
def test_donchian_exit_time_stop():
    assert donchian_exit(_detail(close=4400.0), 'LONG', 4100.0, 5, 'LONG')[0] is True


def test_donchian_exit_short_reverse_breakout():
    d = _detail(close=4500.0, don_hi=4450.0)
    assert donchian_exit(d, 'SHORT', 4600.0, 2, 'SHORT')[0] is True


# ---- MGC (micro gold) mode: contract config + per-point P&L / stop distance ----
def test_resolve_contract_default_gc():
    contract, exchange, pv = resolve_contract_config(contract='GC')
    assert (contract, exchange, pv) == ('GC', 'COMEX', 100.0)


def test_resolve_contract_mgc_tenth_point_value():
    contract, exchange, pv = resolve_contract_config(contract='MGC')
    assert (contract, exchange, pv) == ('MGC', 'COMEX', 10.0)


def test_resolve_contract_env_point_value_overrides_default(monkeypatch):
    monkeypatch.setenv('GC_POINT_VALUE', '25.0')
    _, _, pv = resolve_contract_config(contract='MGC')
    assert pv == 25.0


def test_default_point_value_table():
    assert _DEFAULT_POINT_VALUE['GC'] == 100.0
    assert _DEFAULT_POINT_VALUE['MGC'] == 10.0


def test_mgc_per_point_pnl_is_tenth_of_gc():
    # 1 MGC (10 oz) over a $10 move = $100; 1 GC (100 oz) = $1000.
    assert realized_pnl('LONG', 4400.0, 4410.0, 10.0, 1) == 100.0
    assert realized_pnl('LONG', 4400.0, 4410.0, 100.0, 1) == 1000.0
    # short side mirrors it
    assert realized_pnl('SHORT', 4400.0, 4410.0, 10.0, 1) == -100.0


def test_mgc_stop_distance_price_space_and_dollar_risk():
    # Chandelier stop distance is a PRICE distance (3*ATR), identical for GC and
    # MGC (they trade the same gold price). Only the per-point dollar value
    # scales: MGC = $10/point, GC = $100/point.
    d = _detail(close=4400.0, atr=76.0)
    stop = donchian_stop(d, 'LONG')
    dist = abs(d['close'] - stop)
    assert dist == pytest.approx(3 * 76.0)          # price distance
    assert dist * 10.0 == pytest.approx(2280.0)     # MGC dollar risk per contract
    assert dist * 100.0 == pytest.approx(22800.0)   # GC dollar risk per contract
