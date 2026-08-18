"""VWAP equity-index intraday sleeve tests (bot/live_vwap.py).

Covers the Lane-10 re-activation signal: volume-filtered VWAP 2-sigma
reversion. Guarantees (a) entries only fire outside the ±Kσ band on
genuine high-volume participation, (b) the high-volume filter fails
closed (no low-volume fades), (c) every entry rests a positive 2×ATR hard
protective stop in the correct direction (never-lose-money — so
exec_manager.submit_entry's stop_price<=0 rejection can never trip), and
(d) the quarterly front-month roll is correct.
"""
import datetime as dt
import pytest

from live_vwap import (vwap_entry, vwap_exit, vwap_stop, front_month)


def _detail(close=5000.0, vwap=5000.0, sd=10.0, z=0.0, atr=5.0,
            vol=100.0, roll_vol=100.0, high_vol=True):
    return {'close': close, 'vwap': vwap, 'sd': sd, 'z': z, 'atr': atr,
            'vol': vol, 'roll_vol': roll_vol, 'high_vol': high_vol}


# ---- entry: outside band only, high-volume only ----
def test_vwap_entry_long_below_band():
    side, _ = vwap_entry(_detail(z=-2.5, close=4975.0, vwap=5000.0, high_vol=True))
    assert side == 1


def test_vwap_entry_short_above_band():
    side, _ = vwap_entry(_detail(z=2.5, close=5025.0, vwap=5000.0, high_vol=True))
    assert side == -1


def test_vwap_entry_none_inside_band():
    assert vwap_entry(_detail(z=1.0, high_vol=True))[0] == 0


def test_vwap_entry_none_low_volume_filter_fails_closed():
    # z is well beyond -2σ but the bar is low-volume -> no entry (the filter
    # that unlocked the equity-index sleeve; it must never silently drop).
    side, _ = vwap_entry(_detail(z=-3.0, close=4970.0, vwap=5000.0,
                                vol=50.0, roll_vol=100.0, high_vol=False))
    assert side == 0


def test_vwap_entry_none_nan_sd():
    assert vwap_entry(_detail(z=float('nan'), sd=float('nan')))[0] == 0


# ---- exit: reversion to VWAP ----
def test_vwap_exit_long_reverts():
    assert vwap_exit(_detail(close=5000.0, vwap=4999.0), 'LONG')[0] is True


def test_vwap_exit_short_reverts():
    assert vwap_exit(_detail(close=5000.0, vwap=5001.0), 'SHORT')[0] is True


def test_vwap_exit_hold_long_below_vwap():
    assert vwap_exit(_detail(close=4990.0, vwap=5000.0), 'LONG')[0] is False


# ---- never-lose-money: every entry rests a positive 2xATR stop, correct side ----
def test_vwap_stop_long_below_close():
    d = _detail(close=5000.0, atr=5.0)
    stop = vwap_stop(d, 'LONG')
    assert 0 < stop < d['close']
    assert d['close'] - stop == pytest.approx(2 * 5.0)


def test_vwap_stop_short_above_close():
    d = _detail(close=5000.0, atr=5.0)
    stop = vwap_stop(d, 'SHORT')
    assert stop > d['close']
    assert stop - d['close'] == pytest.approx(2 * 5.0)


def test_vwap_stop_nan_atr_returns_none():
    assert vwap_stop(_detail(atr=float('nan')), 'LONG') is None


# ---- contract roll (quarterly Mar/Jun/Sep/Dec) ----
def test_front_month_jan():
    assert front_month(dt.date(2026, 1, 15)) == '202603'


def test_front_month_jul():
    assert front_month(dt.date(2026, 7, 15)) == '202609'


def test_front_month_nov():
    assert front_month(dt.date(2026, 11, 15)) == '202612'
