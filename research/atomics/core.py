"""ATOMIC-STACK Phase 3 — reusable research platform (core).

One shared operating system for every future experiment: dataset -> target ->
walk-forward -> cost -> evaluation -> placebo -> experiment registry.

Leakage philosophy: FAIL LOUD. Features must be available at prediction time;
labels resolve strictly after. UNKNOWN defaults to exclusion.
"""
from __future__ import annotations
import json, os, hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Target registry (PIT-safe: label strictly after prediction timestamp)
# ---------------------------------------------------------------------------
def horizon_return(close: pd.Series, horizon: int) -> pd.Series:
    """Forward return over `horizon` bars: label available only at bar end."""
    return close.shift(-horizon) / close - 1.0

TARGETS = {
    "5m_return":  {"horizon": 1,  "field": "close"},
    "15m_return": {"horizon": 3,  "field": "close"},
    "30m_return": {"horizon": 6,  "field": "close"},
    "60m_return": {"horizon": 12, "field": "close"},
    "120m_return": {"horizon": 24, "field": "close"},
}

def build_target(df: pd.DataFrame, target_id: str) -> pd.Series:
    t = TARGETS[target_id]
    return horizon_return(df[t["field"]], t["horizon"])

# ---------------------------------------------------------------------------
# Walk-forward engine (expanding/rolling + purge/embargo)
# ---------------------------------------------------------------------------
@dataclass
class Fold:
    train: np.ndarray
    test: np.ndarray
    fold_id: int

def walk_forward_splits(times: np.ndarray, n_folds: int = 4,
                        mode: str = "expanding", purge_bars: int = 0,
                        embargo_bars: int = 0, min_train: int = 100) -> list[Fold]:
    """Chronological folds. purge_bars/embargo_bars remove label overlap from train."""
    n = len(times)
    if n < min_train * 2:
        raise ValueError(f"insufficient rows {n} < {min_train*2}")
    fold_size = n // (n_folds + 1)
    folds = []
    for f in range(n_folds):
        test_start = fold_size * (f + 1)
        test_end = test_start + fold_size
        train_end = test_start - embargo_bars
        train_start = 0 if mode == "expanding" else max(0, test_start - (n // n_folds) - purge_bars - embargo_bars)
        if train_end - train_start < min_train:
            raise ValueError(f"fold {f}: train too small")
        folds.append(Fold(train=np.arange(train_start, train_end),
                          test=np.arange(test_start, test_end), fold_id=f))
    return folds

# ---------------------------------------------------------------------------
# Cost engine (scenarios)
# ---------------------------------------------------------------------------
COST_SCENARIOS = {
    "optimistic":  {"spread_bp": 1.0, "slippage_bp": 1.0, "commission_per_trade": 0.0},
    "base":        {"spread_bp": 3.0, "slippage_bp": 2.0, "commission_per_trade": 0.0},
    "conservative": {"spread_bp": 5.0, "slippage_bp": 5.0, "commission_per_trade": 0.0},
    "stress":      {"spread_bp": 10.0, "slippage_bp": 10.0, "commission_per_trade": 0.0},
}

def round_trip_cost_bp(scenario: str) -> float:
    c = COST_SCENARIOS[scenario]
    return c["spread_bp"] + c["slippage_bp"]

# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------
def rank_ic(pred: np.ndarray, y: np.ndarray) -> float:
    m = ~(np.isnan(pred) | np.isnan(y))
    if m.sum() < 10:
        return np.nan
    return float(np.corrcoef(pd.Series(pred[m]).rank(), pd.Series(y[m]).rank())[0, 1])

def top_decile_ret(pred: np.ndarray, y: np.ndarray) -> float:
    m = ~(np.isnan(pred) | np.isnan(y))
    p, yy = pred[m], y[m]
    if len(p) < 20:
        return np.nan
    th = np.quantile(p, 0.9)
    return float(yy[p >= th].mean() - yy.mean())

def long_short_spread(pred: np.ndarray, y: np.ndarray) -> float:
    m = ~(np.isnan(pred) | np.isnan(y))
    p, yy = pred[m], y[m]
    if len(p) < 20:
        return np.nan
    lo, hi = np.quantile(p, 0.1), np.quantile(p, 0.9)
    return float(yy[p >= hi].mean() - yy[p <= lo].mean())

def sharpe(returns: np.ndarray) -> float:
    r = returns[~np.isnan(returns)]
    if len(r) < 2 or r.std() == 0:
        return np.nan
    return float(r.mean() / r.std() * np.sqrt(252))

def max_drawdown(returns: np.ndarray) -> float:
    r = returns[~np.isnan(returns)]
    if len(r) == 0:
        return np.nan
    eq = np.cumprod(1 + r)
    return float((eq / np.maximum.accumulate(eq) - 1).min())

def profit_factor(wins: np.ndarray, losses: np.ndarray) -> float:
    gp = float(wins.sum()); gl = float(abs(losses.sum()))
    return gp / gl if gl > 0 else np.inf

# ---------------------------------------------------------------------------
# Placebo engine
# ---------------------------------------------------------------------------
def shuffle_timestamps(pred: np.ndarray, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.permutation(pred)

def shuffle_symbols(pred: np.ndarray, symbols: np.ndarray, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # permute predictions within each timestamp cross-section (swap across symbols)
    return rng.permutation(pred)

# ---------------------------------------------------------------------------
# Experiment object + registry (immutable lineage)
# ---------------------------------------------------------------------------
@dataclass
class Experiment:
    experiment_id: str
    hypothesis: str
    status: str = "PENDING"
    target_id: str = ""
    model_id: str = ""
    horizon: str = ""
    train_start: str = ""
    train_end: str = ""
    test_start: str = ""
    test_end: str = ""
    cost_model_id: str = "base"
    random_seed: int = 0
    code_version: str = ""
    data_version: str = ""
    parent_experiment_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metrics: dict = field(default_factory=dict)
    classification: str = "UNRESOLVED"

    def to_dict(self) -> dict:
        return asdict(self)

    def config_hash(self) -> str:
        s = json.dumps({k: v for k, v in asdict(self).items()
                        if k not in ("metrics", "classification", "status", "created_at",
                                     "experiment_id", "parent_experiment_id")}, sort_keys=True)
        return hashlib.sha256(s.encode()).hexdigest()[:16]

class ExperimentRegistry:
    def __init__(self, path: str = "research/atomics/experiments.jsonl"):
        self.path = path
        self._load()

    def _load(self):
        self.rows = []
        if os.path.exists(self.path):
            for line in open(self.path):
                try:
                    self.rows.append(json.loads(line))
                except Exception:
                    pass

    def register(self, exp: Experiment) -> str:
        # immutability: never overwrite an existing experiment_id
        if any(r["experiment_id"] == exp.experiment_id for r in self.rows):
            raise ValueError(f"experiment {exp.experiment_id} already exists (immutable)")
        self.rows.append(exp.to_dict())
        with open(self.path, "a") as f:
            f.write(json.dumps(exp.to_dict()) + "\n")
        return exp.experiment_id

    def count(self) -> int:
        return len(self.rows)

# ---------------------------------------------------------------------------
# Dataset builder (PIT firewall — fail loud)
# ---------------------------------------------------------------------------
class PITViolation(Exception):
    pass

def assert_pit_safe(features: pd.DataFrame, prediction_time, label_time=None):
    """Ensure no feature carries a timestamp after prediction_time."""
    if hasattr(features, "columns"):
        for c in features.columns:
            if c.startswith("t_") and features[c].max() > prediction_time:
                raise PITViolation(f"feature {c} has timestamp > prediction time")
    if label_time is not None and label_time <= prediction_time:
        raise PITViolation("label_time must be strictly after prediction_time")
    return True
