"""Baseline engine — cheap, honest reference predictions.

Baselines are the null models every research claim must beat before it is
worth a second look. None of them use the target, so none can leak.

    random          : pure noise (seeded, reproducible)
    historical_mean : expanding/rolling mean of PAST returns (no lookahead)
    market_return   : equal-weight cross-sectional mean (the "market")
    momentum        : identity on a signal (trend-following)
    reversal        : negative of a signal (mean-reversion)
"""
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd


def random(n: int, seed: int = 0) -> np.ndarray:
    """``n`` i.i.d. standard-normal predictions (reproducible via seed)."""
    return np.random.default_rng(seed).standard_normal(n)


def historical_mean(returns, window: Optional[int] = None, min_periods: int = 1) -> np.ndarray:
    """Predict each bar's return as the mean of STRICTLY PAST returns.

    ``window=None`` -> expanding mean; otherwise a trailing rolling window.
    The mean is shifted by one bar so the prediction at time ``t`` only sees
    data up to ``t-1`` (no lookahead)."""
    s = pd.Series(np.asarray(returns, dtype=float))
    if window is None:
        m = s.expanding(min_periods=min_periods).mean()
    else:
        m = s.rolling(window=window, min_periods=min_periods).mean()
    return m.shift(1).to_numpy()


def market_return(returns) -> np.ndarray:
    """Equal-weight cross-sectional (market) baseline.

    - 1D input -> a constant scalar mean broadcast to the same length.
    - 2D input (time x symbol) -> per-timestamp row mean broadcast to every
      symbol in that row (the "everyone gets the market" prediction)."""
    arr = np.asarray(returns, dtype=float)
    if arr.ndim == 1:
        return np.full(arr.shape, np.nanmean(arr), dtype=float)
    row_mean = np.nanmean(arr, axis=1)
    return np.tile(row_mean[:, None], (1, arr.shape[1]))


def momentum(signal) -> np.ndarray:
    """Trend-following baseline: prediction equals the signal."""
    return np.asarray(signal, dtype=float)


def reversal(signal) -> np.ndarray:
    """Mean-reversion baseline: prediction equals negative signal."""
    return -np.asarray(signal, dtype=float)
