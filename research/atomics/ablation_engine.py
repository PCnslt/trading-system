"""Ablation engine — isolate the incremental contribution of each feature
family against a shuffled (placebo) copy of itself.

For each family it measures three scores:

    BASE                 : metric on the base feature set alone
    BASE + family        : metric after adding the (real) family
    BASE + shuffled      : metric after adding a row-shuffled family

and reports the incremental deltas. ``delta_add`` is the family's real
contribution; ``delta_shuffled`` is its placebo ceiling. A family is worth
keeping only when ``delta_add`` meaningfully exceeds ``delta_shuffled``.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
import numpy as np


def _as_family_array(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def run_ablation(metric_fn: Callable[[Dict[str, np.ndarray]], float],
                 feature_families: Dict[str, Any],
                 base_features: Optional[Dict[str, Any]] = None,
                 shuffle_seed: int = 0,
                 n_shuffles: int = 1) -> List[Dict[str, Any]]:
    """Compute BASE vs BASE+family vs BASE+shuffled-family for every family.

    ``metric_fn`` receives a dict ``{family_name: array}`` and returns a
    scalar (higher = better). ``base_features`` is the fixed feature set every
    comparison starts from (default empty). ``n_shuffles`` placebo runs are
    averaged for the shuffled score.
    """
    base = {k: _as_family_array(v) for k, v in (base_features or {}).items()}
    families = {k: _as_family_array(v) for k, v in feature_families.items()}
    base_score = float(metric_fn(dict(base)))

    rng = np.random.default_rng(shuffle_seed)
    results: List[Dict[str, Any]] = []

    for name, feats in families.items():
        if name in base:
            # already present in the base set -> not an additive ablation
            continue

        add_score = float(metric_fn({**base, name: feats}))

        shuffled_scores = []
        for _ in range(max(1, n_shuffles)):
            shuf = feats.copy()
            rng.shuffle(shuf)  # shuffle along the row (observation) axis
            shuffled_scores.append(float(metric_fn({**base, name: shuf})))
        shuffled_score = float(np.mean(shuffled_scores))

        delta_add = add_score - base_score
        delta_shuffled = shuffled_score - base_score
        results.append({
            "family": name,
            "base_score": base_score,
            "add_score": add_score,
            "shuffled_score": shuffled_score,
            "delta_add": delta_add,
            "delta_shuffled": delta_shuffled,
            "placebo_gap": delta_add - delta_shuffled,
        })

    return results
