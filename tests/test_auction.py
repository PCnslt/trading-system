"""Creamer auction 4-step framework tests (data/auction.py) — Phase 4.

Locks the signal-only setup logic: market structure, fib golden pocket,
value-area location, confirmation (absorption + shift of dominance +
imbalance), execution levels, and the participation floor.
"""
import pytest

from data.auction import (market_structure, fib_golden_pocket, value_area_position,
                          golden_pocket_outside_value, shift_of_dominance,
                          confirmation, execution_levels, auction_setup, auction_score)

# synthetic uptrend: HH (8->10) + HL (2->3)
UP_HIGHS = [5, 5, 5, 8, 5, 5, 5, 10, 5, 5, 5]
UP_LOWS = [4, 4, 4, 2, 4, 4, 4, 3, 4, 4, 4]
# synthetic downtrend: LH (10->8) + LL (3->2)
DN_HIGHS = [5, 5, 5, 10, 5, 5, 5, 8, 5, 5, 5]
DN_LOWS = [4, 4, 4, 3, 4, 4, 4, 2, 4, 4, 4]


# ---- step 1: environment ----
def test_structure_uptrend():
    assert market_structure(UP_HIGHS, UP_LOWS) == 'up'


def test_structure_downtrend():
    assert market_structure(DN_HIGHS, DN_LOWS) == 'down'


def test_structure_sideways_on_flat():
    flat = [5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5]
    assert market_structure(flat, flat) == 'sideways'


# ---- step 2: location ----
def test_fib_golden_pocket_levels():
    p = fib_golden_pocket(100.0, 120.0)
    assert p['0.705'] == pytest.approx(120 - 0.705 * 20)
    assert p['0.886'] == pytest.approx(120 - 0.886 * 20)
    assert p['0.886'] < p['0.705']     # deeper retrace is lower price


def test_value_area_position():
    assert value_area_position(110, vah=109, val=100) == 'premium'
    assert value_area_position(99, vah=109, val=100) == 'discount'
    assert value_area_position(105, vah=109, val=100) == 'inside'


def test_golden_pocket_outside_value():
    p = fib_golden_pocket(100.0, 120.0)   # range ~[102.3, 105.9]
    assert golden_pocket_outside_value(p, vah=112, val=108) is True    # below VAL
    assert golden_pocket_outside_value(p, vah=106, val=103) is False   # overlaps VA


# ---- step 3: confirmation ----
def test_shift_of_dominance_flip():
    assert shift_of_dominance([-5, -3, -2, 4]) is True     # sellers -> buyers
    assert shift_of_dominance([5, 3, 2, -4]) is True       # buyers -> sellers
    assert shift_of_dominance([-5, -3, -2, -4]) is False   # no flip


def test_confirmation_long():
    c = confirmation({'sell_absorption': True}, shift=True, imbalance=0.3, side='long')
    assert c['passed'] is True


def test_confirmation_short():
    c = confirmation({'buy_absorption': True}, shift=True, imbalance=-0.4, side='short')
    assert c['passed'] is True


def test_confirmation_imbalance_pending_does_not_veto():
    c = confirmation({'sell_absorption': True}, shift=True, imbalance=None, side='long')
    assert c['passed'] is True
    assert any('pending' in r for r in c['reasons'])


# ---- step 4: execution ----
def test_execution_levels_long_stop_below_failed_sellers():
    ex = execution_levels('long', 104.0, fib_golden_pocket(100, 120),
                          failed_extreme=102.0, poc=110.0)
    assert ex['stop'] == 102.0                      # min(failed, 0.886=102.28)
    assert ex['target_poc'] == 110.0


# ---- orchestrator ----
def _base_setup_args():
    return dict(
        side='long', price=104.0, highs=UP_HIGHS, lows=UP_LOWS,
        vah=112.0, val=108.0, poc=110.0,
        deltas=[-5, -3, -2, 4],
        absorption={'sell_absorption': True, 'buy_absorption': False},
        imbalance=0.3, swing_low=100.0, swing_high=120.0,
        failed_extreme=102.0, participation=25000.0,
    )


def test_auction_setup_long_passes():
    s = auction_setup(**_base_setup_args())
    assert s is not None
    assert s['side'] == 'long'
    assert s['environment'] == 'up'
    assert s['stop'] == 102.0


def test_auction_setup_rejects_below_participation_floor():
    a = _base_setup_args(); a['participation'] = 15000.0
    assert auction_setup(**a) is None


def test_auction_setup_rejects_wrong_environment_direction():
    a = _base_setup_args(); a['side'] = 'short'   # short needs a downtrend
    assert auction_setup(**a) is None


def test_auction_setup_rejects_price_outside_pocket():
    a = _base_setup_args(); a['price'] = 110.0    # above the golden pocket
    assert auction_setup(**a) is None


# ---- score-based variant ----
def test_auction_score_full_alignment_is_setup():
    sc = auction_score(**_base_setup_args())
    assert 0.0 <= sc['score'] <= 1.0
    assert sc['setup'] is True
    assert sc['components']['absorption'] == 1.0
    assert sc['components']['shift'] == 1.0


def test_auction_score_hard_gate_below_participation_floor():
    a = _base_setup_args(); a['participation'] = 15000.0
    sc = auction_score(**a)
    assert sc['setup'] is False
    assert sc['score'] == 0.0


def test_auction_score_wrong_direction_low_score():
    a = _base_setup_args(); a['side'] = 'short'   # short in an uptrend -> env=0
    sc = auction_score(**a)
    assert sc['components']['env'] == 0.0
    assert sc['score'] < 0.6
