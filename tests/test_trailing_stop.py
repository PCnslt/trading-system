"""Trailing-stop unit tests — the live.py chandelier trail math.

`donchian_trail` is the live port of the validated backtest variant
(research/trailing_stop_backtest.py, DONCHIAN chandelier 3*ATR). These tests
pin the ratchet-up-only semantics and the legacy-position fallback so a
regression in the live port can't silently loosen a stop.
"""
import sys

import pytest

# conftest.py puts repo-root and bot/ on sys.path; import bot.live lazily so a
# missing optional dependency (yfinance/boto3/ib_insync) degrades to a skip.
try:
    from bot.live import donchian_trail, CHAND_ATR
except Exception as e:  # pragma: no cover - dependency/env guard
    pytest.skip(f"bot.live not importable in this env: {e}", allow_module_level=True)


def _detail(close, atr):
    return {'close': float(close), 'atr': float(atr)}


def test_ratchet_up_on_new_high():
    state = {'entry': '100.0', 'peak': '100.0', 'stop': '80.0'}
    # close rises to 110 with ATR 5 -> candidate 110 - 15 = 95 > 80 -> raise
    new_stop, new_peak, reason = donchian_trail(_detail(110.0, 5.0), state)
    assert new_peak == pytest.approx(110.0)
    assert new_stop == pytest.approx(110.0 - CHAND_ATR * 5.0)
    assert "chandelier" in reason


def test_no_ratchet_when_candidate_below_current_stop():
    # close barely moves; 3*ATR is wide so candidate < current stop -> new_stop None
    state = {'entry': '100.0', 'peak': '100.0', 'stop': '80.0'}
    new_stop, new_peak, _ = donchian_trail(_detail(101.0, 20.0), state)
    # candidate = 101 - 60 = 41 < 80 -> no raise (caller applies tighten-only)
    assert new_stop == pytest.approx(41.0)
    assert new_peak == pytest.approx(101.0)   # peak still advances


def test_legacy_position_uses_entry_as_peak():
    state = {'entry': '100.0'}                 # no 'peak' key (pre-tagging)
    new_stop, new_peak, _ = donchian_trail(_detail(99.0, 5.0), state)
    assert new_peak == pytest.approx(100.0)    # falls back to entry, not 99
    assert new_stop == pytest.approx(100.0 - CHAND_ATR * 5.0)


def test_nan_atr_returns_none():
    state = {'entry': '100.0', 'peak': '100.0'}
    new_stop, new_peak, reason = donchian_trail({'close': 105.0, 'atr': float('nan')}, state)
    assert new_stop is None
    assert new_peak is None
    assert reason == "no ATR"
