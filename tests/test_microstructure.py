"""Microstructure feature tests (data/microstructure.py) — Phase 3.

Locks the footprint primitives the Creamer auction generator (Phase 4)
consumes: bid-ask delta classification, absorption (failed auction), volume
profile / value area, orderbook imbalance, and spread cost.
"""
import pytest

from data.microstructure import (classify_trade, bid_ask_delta, bar_absorption,
                                  volume_profile, orderbook_imbalance, spread_and_cost)


# ---- trade classification ----
def test_classify_buy_at_or_above_ask():
    assert classify_trade(10.0, 9.9, 10.0) == 1
    assert classify_trade(10.1, 9.9, 10.0) == 1


def test_classify_sell_at_or_below_bid():
    assert classify_trade(9.9, 9.9, 10.0) == -1
    assert classify_trade(9.8, 9.9, 10.0) == -1


def test_classify_mid_or_missing():
    assert classify_trade(9.95, 9.9, 10.0) == 0
    assert classify_trade(None, 9.9, 10.0) == 0


# ---- bid-ask delta ----
def test_bid_ask_delta_aggregates_signed_volume():
    ticks = [
        {'ts': 1, 'bid': 10.0, 'ask': 10.1, 'last': 10.1, 'lastSize': 5},   # buy 5
        {'ts': 1, 'bid': 10.0, 'ask': 10.1, 'last': 10.0, 'lastSize': 2},   # sell 2
        {'ts': 2, 'bid': 10.0, 'ask': 10.1, 'last': 10.1, 'lastSize': 3},   # buy 3
    ]
    bars = bid_ask_delta(ticks)
    assert bars[1]['delta'] == 5 - 2
    assert bars[2]['delta'] == 3
    assert bars[1]['buys'] == 5 and bars[1]['sells'] == 2


# ---- absorption ----
def test_sell_absorption_trapped_sellers():
    # aggressive sells at the low but the bar closes back off the low
    b = {'open': 100, 'high': 101, 'low': 99, 'close': 100.5}
    r = bar_absorption(b, delta=-50, delta_threshold=10)
    assert r['sell_absorption'] is True


def test_buy_absorption_trapped_buyers():
    b = {'open': 100, 'high': 102, 'low': 99.5, 'close': 100.2}
    r = bar_absorption(b, delta=80, delta_threshold=10)
    assert r['buy_absorption'] is True


def test_no_absorption_when_price_rewards():
    # buyers aggressive and the bar closed at the high -> rewarded, not trapped
    b = {'open': 100, 'high': 105, 'low': 99.5, 'close': 105}
    r = bar_absorption(b, delta=100, delta_threshold=10)
    assert r['buy_absorption'] is False


# ---- volume profile / value area ----
def test_volume_profile_poc_and_value_area():
    bars = [
        {'high': 10, 'low': 9, 'volume': 100},    # centered ~9.5
        {'high': 11, 'low': 10, 'volume': 40},    # centered ~10.5
    ]
    r = volume_profile(bars, price_step=1.0, value_area=0.70)
    assert r['poc'] is not None
    assert r['total_volume'] == pytest.approx(140.0)
    assert r['vah'] >= r['poc'] >= r['val']


def test_volume_profile_empty():
    r = volume_profile([])
    assert r['poc'] is None and r['total_volume'] == 0.0


# ---- orderbook imbalance ----
def test_imbalance_bid_heavy_positive():
    bids = [{'price': 10.0, 'quantity': 100}, {'price': 9.9, 'quantity': 100}]
    asks = [{'price': 10.1, 'quantity': 100}]
    assert orderbook_imbalance(bids, asks, top_n=5) == pytest.approx((200 - 100) / 300)


def test_imbalance_none_when_no_depth():
    assert orderbook_imbalance([], [], top_n=5) is None


# ---- spread + cost ----
def test_spread_and_capture_cost():
    r = spread_and_cost(10.0, 10.5, tick_size=0.25)
    assert r['spread'] == 0.5
    assert r['spread_ticks'] == 2.0
    assert r['capture_cost_ticks'] == 4.0


def test_spread_none_when_crossed():
    assert spread_and_cost(10.5, 10.0)['spread'] is None


# ---- session feature assembly (tick bucketing into bars) ----
def test_compute_session_features_buckets_ticks_into_bars():
    from microstructure_engine import compute_session_features
    bars = [
        {'ts': '2026-08-17T09:30:00-04:00', 'open': 100, 'high': 101,
         'low': 99, 'close': 100.5, 'volume': 100},
        {'ts': '2026-08-17T09:35:00-04:00', 'open': 100.5, 'high': 102,
         'low': 100, 'close': 101.5, 'volume': 80},
    ]
    import datetime as dt
    t0 = int(dt.datetime.fromisoformat('2026-08-17T09:30:00-04:00').timestamp())
    ticks = [
        {'ts': t0 + 120, 'bid': 100.0, 'ask': 100.25, 'last': 100.25, 'lastSize': 10},  # buy -> bar1
        {'ts': t0 + 300 + 120, 'bid': 101.0, 'ask': 101.25, 'last': 101.0, 'lastSize': 4},  # sell -> bar2
    ]
    per_bar, profile, imb = compute_session_features('MES', bars, ticks, book=None)
    assert len(per_bar) == 2
    assert per_bar[0]['delta'] == 10.0
    assert per_bar[1]['delta'] == -4.0
    assert profile['poc'] is not None
    assert imb is None
