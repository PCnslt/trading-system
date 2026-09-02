"""Cluster inference — date-clustered standard errors and block bootstrap CIs
for a mean return.

Returns observed on the same date are correlated (they share a common market
shock), so the naive i.i.d. standard error understates uncertainty. We treat
each date as a cluster: the clustered SE uses the cluster-robust sandwich
estimator, and the bootstrap CI resamples whole dates (blocks), not individual
observations.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List
import numpy as np


@dataclass
class BootstrapCI:
    mean: float
    ci_low: float
    ci_high: float
    se: float                 # std of the bootstrap distribution
    n_iter: int
    alpha: float
    method: str = "percentile"


def group_by_date(returns, dates) -> Dict:
    """Group observation indices by date. Returns {date: np.array(indices)}."""
    returns = np.asarray(returns, dtype=float)
    dates = np.asarray(dates)
    if returns.ndim != 1 or dates.shape[0] != returns.shape[0]:
        raise ValueError("returns must be 1D and match dates length")
    groups: Dict = {}
    for i, d in enumerate(dates):
        groups.setdefault(d, []).append(i)
    return {d: np.asarray(idxs, dtype=int) for d, idxs in groups.items()}


def _cluster_stats(returns, dates):
    returns = np.asarray(returns, dtype=float)
    dates = np.asarray(dates)
    groups = group_by_date(returns, dates)
    n_dates = len(groups)
    return returns, groups, n_dates


def clustered_mean_se(returns, dates) -> float:
    """Cluster-robust (Liang-Zeger sandwich) standard error of the mean return,
    clustered by date."""
    returns, groups, G = _cluster_stats(returns, dates)
    if G < 2:
        return float("nan")
    mu = float(np.mean(returns))
    N = returns.shape[0]
    score_sum_sq = 0.0
    for idxs in groups.values():
        cluster_score = float(np.sum(returns[idxs] - mu))
        score_sum_sq += cluster_score * cluster_score
    var = (G / (G - 1.0)) * score_sum_sq / (N * N)
    return float(np.sqrt(var))


def naive_mean_se(returns) -> float:
    """i.i.d. standard error (for comparison with the clustered version)."""
    r = np.asarray(returns, dtype=float)
    if r.shape[0] < 2:
        return float("nan")
    return float(r.std(ddof=1) / np.sqrt(r.shape[0]))


def block_bootstrap_ci(returns, dates, n_iter: int = 1000,
                       alpha: float = 0.05, seed: int = 0) -> BootstrapCI:
    """Percentile block-bootstrap CI for the mean return.

    Resamples whole dates (clusters) with replacement, recomputes the mean of
    the observations in the resampled dates, and takes the empirical
    percentiles of the resulting distribution."""
    returns, groups, G = _cluster_stats(returns, dates)
    if G < 2:
        raise ValueError("need at least 2 date clusters to bootstrap")
    date_keys = list(groups.keys())
    rng = np.random.default_rng(seed)

    stats = np.empty(n_iter)
    for b in range(n_iter):
        chosen = rng.integers(0, G, size=G)
        vals = np.concatenate([returns[groups[date_keys[c]]] for c in chosen])
        stats[b] = float(np.mean(vals))

    lo_p, hi_p = 100.0 * alpha / 2.0, 100.0 * (1.0 - alpha / 2.0)
    lo, hi = np.percentile(stats, [lo_p, hi_p])
    return BootstrapCI(
        mean=float(np.mean(returns)),
        ci_low=float(lo),
        ci_high=float(hi),
        se=float(stats.std(ddof=1)),
        n_iter=n_iter,
        alpha=alpha,
    )
