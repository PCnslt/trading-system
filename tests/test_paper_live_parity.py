"""Paper/live executability parity for the RSI2 equities lane.

A paper trade we could not have taken live is not evidence. Every entry in this
system must carry a WHOLE-SHARE protective stop (Robinhood stops are whole-share
only; the IBKR API rejects fractional orders outright with Error 10243), so the
paper book must obey the same whole-share constraint as live.

Regression guarded here: before 2026-08-24 the paper lane recorded fractional
positions - $35 "buying" a slice of NVDA/GEV(@844)/EME(@705) - so the forward-test
record was optimistic and non-predictive. Only ~1 in 4 paper candidates that night
was affordable as a whole share.
"""
from __future__ import annotations

from bot.live_equities import position_size


def _shares(capital, close, atr, max_pos_pct=None):
    """Whole shares the paper lane would take, mirroring the live constraint."""
    size_usd, _ = position_size(capital, close, atr)
    return int(size_usd / close) if close > 0 else 0


def test_expensive_name_is_not_tradeable_on_a_small_account():
    """GEV-style: a ~$900 stock cannot be held whole-share on $700 of capital."""
    assert _shares(700, 900.0, 20.0) == 0


def test_mid_priced_name_is_skipped_when_under_one_share():
    """NVDA-style ~$200: 15% of $700 = $105 -> under one share -> no trade."""
    assert _shares(700, 200.0, 5.0) == 0


def test_affordable_name_yields_whole_shares():
    """BB-style $7.65: must produce a whole-share position, not a fractional slice."""
    n = _shares(700, 7.65, 0.29)
    assert n >= 1
    assert n == int(n)


def test_sub_fifty_name_is_tradeable():
    """ONB-style $25.77 at 15% cap -> ~4 whole shares."""
    assert _shares(700, 25.77, 0.46) >= 1


def test_notional_never_exceeds_the_position_cap():
    """Whole-share rounding must round DOWN, never over-commit capital."""
    for close, atr in ((7.65, 0.29), (25.77, 0.46), (49.0, 1.2), (104.0, 2.0)):
        size_usd, _ = position_size(700, close, atr)
        n = int(size_usd / close)
        assert n * close <= size_usd + 1e-9, f"{close}: {n}x{close} exceeds {size_usd}"


def test_zero_or_negative_price_is_safe():
    assert _shares(700, 0.0, 1.0) == 0
