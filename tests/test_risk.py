"""Risk engine: sizing cap + fail-closed gates + persistent accounting."""
import time

import pytest

from risk import RiskEngine, RiskConfig, realized_pnl, realized_vol_daily


def make_engine(**cfg):
    base = dict(risk_budget_usd=100_000, risk_pct=0.01,
                max_trades_per_day=4, max_consecutive_losses=6,
                max_daily_loss_pct=0.02, max_data_staleness_s=120)
    base.update(cfg)
    return RiskEngine(RiskConfig(**base))


# --- sizing cap (critical fix #5) ---
def test_position_size_wide_stop_returns_zero():
    # risk_amount = 1000; stop 1000 pts * $5 = $5000 risk -> contracts 0 -> reject
    e = make_engine()
    assert e.position_size(1000.0, 5.0) == 0


def test_position_size_zero_or_negative_stop_returns_zero():
    e = make_engine()
    assert e.position_size(0.0, 5.0) == 0
    assert e.position_size(-1.0, 5.0) == 0


def test_position_size_normal():
    # risk_amount 1000 / (10 pts * $5) = 20 -> capped by max_contracts 5
    e = make_engine(max_contracts=5)
    assert e.position_size(10.0, 5.0) == 5
    # wider but still within budget: 1000/(100*5)=2
    assert e.position_size(100.0, 5.0) == 2


def test_position_size_respects_min_contracts_boundary():
    # exactly one contract worth of risk -> 1, not forced to 0
    e = make_engine()
    # 1000 / (200 * 5) = 1 contract
    assert e.position_size(200.0, 5.0) == 1


# --- volatility overlay (PART 2.2: 1/realized-vol scaling, hard cap) ---
def test_position_size_vol_overlay_caps_qty():
    # stop-based: 1000/(10*5)=20 -> capped to max_contracts 5.
    # vol-based: budget 1000 / (0.1*1000*5=500) = 2 -> cap 5 down to 2.
    e = make_engine()
    assert e.position_size(10.0, 5.0, realized_vol=0.1, price=1000.0) == 2


def test_position_size_vol_overlay_rejects_when_vol_too_high():
    # even one contract exceeds the vol budget -> reject (fail-closed, 0).
    e = make_engine()
    assert e.position_size(10.0, 5.0, realized_vol=1.0, price=1000.0) == 0


def test_position_size_vol_overlay_never_increases():
    # stop-based=2; a tiny vol would allow 200 contracts, but the overlay only
    # caps — it never raises the stop-derived size.
    e = make_engine()
    assert e.position_size(100.0, 5.0, realized_vol=0.001, price=1000.0) == 2


def test_position_size_vol_overlay_off():
    e = make_engine(vol_scale_enabled=False)
    assert e.position_size(10.0, 5.0, realized_vol=0.5, price=1000.0) == 5


def test_position_size_vol_missing_params_backward_compat():
    # no vol/price -> overlay skipped, stop-based sizing unchanged.
    e = make_engine()
    assert e.position_size(10.0, 5.0) == 5


# --- portfolio heat cap (total open risk, prevents correlated stacking) ---
def test_heat_cap_disabled_by_default():
    e = make_engine()  # heat_cap_pct defaults 0.0
    e.set_open_positions(3, risk_usd=9000.0)  # way over any cap
    assert e.position_size(10.0, 5.0) == 5    # sizing unchanged when disabled


def test_heat_cap_limits_total_open_risk():
    e = make_engine(heat_cap_pct=0.03)        # budget 100k -> heat cap $3000
    e.set_open_positions(1, risk_usd=2500.0)
    # room $500 / ($50 per contract) = 10 -> capped by max_contracts 5
    assert e.position_size(10.0, 5.0) == 5
    e.set_open_positions(1, risk_usd=2900.0)
    # room $100 -> 2 contracts
    assert e.position_size(10.0, 5.0) == 2


def test_heat_cap_rejects_when_no_room():
    e = make_engine(heat_cap_pct=0.03)
    e.set_open_positions(1, risk_usd=3000.0)  # at cap -> no room
    assert e.position_size(10.0, 5.0) == 0


def test_record_fill_close_tracks_open_risk():
    e = make_engine(heat_cap_pct=0.03)
    e.record_fill(risk_usd=500.0)
    assert e.open_risk_usd == 500.0
    e.record_close(pnl=-100.0, risk_usd=500.0)
    assert e.open_risk_usd == 0.0


def test_realized_vol_daily():
    import pandas as pd
    # flat series -> ~0
    assert realized_vol_daily(pd.Series([100.0] * 30), 20) == pytest.approx(0.0, abs=1e-9)
    # insufficient history -> 0
    assert realized_vol_daily(pd.Series([100.0, 101.0]), 20) == 0.0
    # None -> 0
    assert realized_vol_daily(None, 20) == 0.0
    # real returns -> positive
    s = pd.Series([100.0, 101.0, 100.0, 102.0, 101.0])
    assert realized_vol_daily(s, 3) > 0.0


# --- daily-loss halt ---
def test_can_enter_daily_loss_halt():
    e = make_engine()
    limit = -100_000 * 0.02
    e.daily_pnl = limit - 1
    allowed, reason = e.can_enter()
    assert allowed is False
    assert 'daily loss' in reason


# --- stale data ---
def test_can_enter_stale_data():
    e = make_engine()
    e._last_data_ts = time.time() - 9999
    allowed, reason = e.can_enter()
    assert allowed is False
    assert 'stale' in reason


# --- consecutive-loss brake ---
def test_can_enter_consecutive_losses():
    e = make_engine()
    e.consecutive_losses = 6
    allowed, _ = e.can_enter()
    assert allowed is False


# --- max trades / day ---
def test_can_enter_max_trades():
    e = make_engine()
    e.daily_trades = 4
    allowed, _ = e.can_enter()
    assert allowed is False


# --- emergency halt ---
def test_emergency_halt_blocks_entries():
    e = make_engine()
    e.emergency_halt("reconciliation mismatch")
    allowed, reason = e.can_enter()
    assert allowed is False
    assert "reconciliation mismatch" in reason


# --- persistent accounting (critical fix #4) ---
def test_record_fill_and_close_accumulate_across_calls():
    e = make_engine()
    e.record_fill()
    e.record_fill()
    assert e.daily_trades == 2
    assert e.open_positions == 2
    e.record_close(-500.0)
    e.record_close(300.0)
    assert e.daily_trades == 2
    assert e.open_positions == 0
    assert e.daily_pnl == pytest.approx(-200.0)
    assert e.consecutive_losses == 0   # win resets the brake


def test_record_close_losses_trigger_halt():
    e = make_engine()
    limit = -100_000 * 0.02
    e.record_close(limit - 1)
    assert e.halted is True
    assert e.halt_reason == "daily loss halt"


def test_realized_pnl_direction():
    assert realized_pnl('LONG', 100, 110, 5.0, 2) == pytest.approx(100.0)
    assert realized_pnl('SHORT', 110, 100, 5.0, 2) == pytest.approx(100.0)
    assert realized_pnl('LONG', 100, 90, 5.0, 1) == pytest.approx(-50.0)
