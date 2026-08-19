"""Adaptive trailing-stop engine — regime-adaptive, edge-aware.

The naive chandelier (fixed N*ATR from peak) fails because a stop has two jobs in
tension — PROTECT (wants tight) and GIVE ROOM (wants wide) — and a fixed multiplier
can't resolve them: it whipsaws in chop and gives back too much in calm trends.

This engine adapts the stop to THREE signals each bar:
  1. volatility regime   VR = ATR / rolling-median(ATR, 100)   (wobble -> widen)
  2. trend efficiency    ER = Kaufman efficiency ratio          (trend -> tighten)
  3. profit stage        breakeven-lock -> trail -> accelerate  (Parabolic-style)

and routes the EXIT PHILOSOPHY by edge type:
  'trend'    -> adaptive chandelier trail (all stages)
  'meanrev'  -> breakeven-lock ONLY (target-based edge, NO trail — trailing cuts it)
  'momentum' -> volatility-scaling (size_scale ~ 1/VR) + a WIDE trail

Grounded in: Kaminski & Lo 2014 (stops help momentum, hurt mean-reversion),
Moreira & Muir 2017 (volatility-managed portfolios), Kaufman ER, Wilder Parabolic SAR.

Pure functions + a stateful class; no broker/network I/O. Importable by bots and
by the research harness alike (single source of truth).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --- tuning knobs (one place) ---
BASE_MULT = 3.0       # chandelier base multiplier (ATR units)
VR_LO, VR_HI = 0.6, 1.6    # volatility-ratio clamp (multiplier scale bounds)
ER_WEIGHT = 0.4            # how much trend efficiency tightens the stop (0..1)
MULT_LO, MULT_HI = 1.5, 5.0  # hard bounds on the adaptive multiplier
BREAKEVEN_ATR = 1.0   # +1 ATR profit -> lock to breakeven
TRAIL_ATR = 2.0       # +2 ATR profit -> start adaptive trail
ACCEL_ATR = 0.10      # per-ATR tightening past TRAIL_ATR (Parabolic acceleration)
MOMENTUM_WIDE = 2.0   # momentum lane: trail multiplier = base * this (wide)


def wilder_atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def kaufman_er(c: pd.Series, n: int = 20) -> pd.Series:
    """Kaufman efficiency ratio in [0,1]: 1 = pure trend, 0 = pure noise."""
    change = c.diff(n).abs()
    vol = c.diff().abs().rolling(n).sum()
    return (change / vol.replace(0, np.nan)).clip(0, 1)


def compute_features(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(atr, atr_median, er_smooth) aligned to df index. Handles multi-index cols."""
    h = df['High'].squeeze()
    l = df['Low'].squeeze()
    c = df['Close'].squeeze()
    atr = wilder_atr(h, l, c)
    atr_median = atr.rolling(100, min_periods=20).median()
    er_smooth = kaufman_er(c).ewm(alpha=0.1, adjust=False).mean()
    return atr, atr_median, er_smooth


def adaptive_multiplier(base: float, atr: float, atr_median: float,
                        er: float) -> float:
    """Adaptive ATR multiplier: widen in high-vol, tighten in low-vol and trend."""
    vr = (atr / atr_median) if (atr_median and atr_median > 0 and atr > 0) else 1.0
    vol_scale = float(np.clip(vr, VR_LO, VR_HI))
    er_scale = 1.0 - ER_WEIGHT * float(er)
    return float(np.clip(base * vol_scale * er_scale, MULT_LO, MULT_HI))


class AdaptiveStop:
    """Stateful adaptive stop for ONE open position (long). Ratchets down = up only.

    update() returns (stop_price, size_scale). size_scale != 1.0 only for the
    'momentum' edge (volatility-scaled position sizing).
    """

    def __init__(self, edge_type: str, base_mult: float = BASE_MULT):
        if edge_type not in ('trend', 'meanrev', 'momentum'):
            raise ValueError(f"unknown edge_type {edge_type!r}")
        self.edge_type = edge_type
        self.base_mult = base_mult
        self.peak: float | None = None
        self.stage: int = 0

    def reset(self) -> None:
        self.peak = None
        self.stage = 0

    def update(self, entry: float, close: float, high: float,
               atr: float, atr_median: float, er: float) -> tuple[float, float]:
        if atr <= 0:
            return entry, 1.0  # degenerate — refuse to trail on zero vol

        if self.peak is None:
            self.peak = close
        self.peak = max(self.peak, high)

        if self.edge_type == 'momentum':
            vr = (atr / atr_median) if (atr_median and atr_median > 0) else 1.0
            size_scale = 1.0 / max(0.5, float(vr))       # vol-scaling (Moreira-Muir)
            wide_mult = self.base_mult * MOMENTUM_WIDE
            return self.peak - wide_mult * atr, size_scale

        mult = adaptive_multiplier(self.base_mult, atr, atr_median, er)
        profit_atr = (close - entry) / atr

        if self.edge_type == 'meanrev':
            # target-based edge: only a breakeven lock once in profit — NEVER trail
            if profit_atr >= BREAKEVEN_ATR:
                return entry, 1.0
            return entry - self.base_mult * atr, 1.0

        # 'trend': staged adaptive trail
        if profit_atr >= TRAIL_ATR:
            self.stage = max(self.stage, 2)
        elif profit_atr >= BREAKEVEN_ATR:
            self.stage = max(self.stage, 1)

        if self.stage >= 2:
            # Parabolic-style acceleration: tighten as profit extends
            tighten = 1.0 - ACCEL_ATR * max(0.0, profit_atr - TRAIL_ATR)
            mult = max(0.5, mult * max(0.5, tighten))
            return self.peak - mult * atr, 1.0
        if self.stage == 1:
            return entry, 1.0                               # breakeven lock
        return entry - mult * atr, 1.0                      # disaster floor (stage 0)
