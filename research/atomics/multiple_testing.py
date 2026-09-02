"""Multiple-testing ledger — count every experiment and control the false
discovery rate (FDR) across the batch with Benjamini-Hochberg.

Running many experiments inflates false positives. The ledger records how many
experiments were attempted and applies a simple BH correction to a list of
p-values so a reported "significant" result is significant *given* how many
hypotheses were actually tested.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class BHResult:
    rejected: np.ndarray          # boolean mask, same length as input
    adjusted: np.ndarray          # BH-adjusted p-values
    alpha: float
    m: int                        # number of hypotheses corrected
    experiments_attempted: int    # ledger counter at correction time
    n_rejected: int = field(default=0)

    def __post_init__(self):
        self.n_rejected = int(np.sum(self.rejected))


def benjamini_hochberg(pvalues, alpha: float = 0.05) -> Tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg FDR correction.

    Returns ``(rejected, adjusted)``. ``rejected`` is a boolean array marking
    hypotheses rejected at FDR ``alpha``; ``adjusted`` holds BH q-values.
    NaN p-values are treated as 1.0 (never rejected)."""
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    if m == 0:
        return np.array([], dtype=bool), np.array([], dtype=float)

    p = np.where(np.isnan(p), 1.0, p)
    order = np.argsort(p, kind="stable")
    sorted_p = p[order]

    # largest k with p_(k) <= alpha * k / m
    k = m
    while k >= 1 and sorted_p[k - 1] > alpha * k / m:
        k -= 1

    rejected_sorted = np.zeros(m, dtype=bool)
    if k >= 1:
        rejected_sorted[:k] = True

    rejected = np.zeros(m, dtype=bool)
    rejected[order] = rejected_sorted

    # BH adjusted p-values: q_(i) = min_{j>=i} p_(j) * m / j, capped at 1
    adjusted_sorted = np.empty(m)
    running = np.inf
    for i in range(m - 1, -1, -1):
        adj = sorted_p[i] * m / (i + 1)
        running = min(running, adj)
        adjusted_sorted[i] = min(running, 1.0)
    adjusted = np.empty(m)
    adjusted[order] = adjusted_sorted

    return rejected, adjusted


class MultipleTestingLedger:
    """Tracks experiments attempted and applies BH FDR to a batch of p-values."""

    def __init__(self):
        self.experiments_attempted = 0
        self.records: List[dict] = []

    def record(self, n: int = 1, note: str = "") -> int:
        """Record ``n`` additional experiments attempted. Returns new total."""
        self.experiments_attempted += n
        self.records.append({"n": n, "note": note, "total": self.experiments_attempted})
        return self.experiments_attempted

    def correct(self, pvalues, alpha: float = 0.05) -> BHResult:
        """Apply BH correction. ``m`` = number of p-values supplied; the ledger
        counter is attached for audit so a result can never claim significance
        without the full experiment count being visible."""
        rejected, adjusted = benjamini_hochberg(pvalues, alpha)
        return BHResult(rejected=rejected, adjusted=adjusted, alpha=alpha,
                        m=np.asarray(pvalues).size,
                        experiments_attempted=self.experiments_attempted)
