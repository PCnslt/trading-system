"""Phase 3 extension infrastructure validation.

Exercises every new module with synthetic data and asserts the key
invariants:

  * prediction_store  : duplicate prediction_id raises (immutability)
  * model_registry    : CHALLENGER->CHAMPION needs explicit OOS evidence
  * baseline_engine   : momentum/reversal/random/historical_mean/market_return
  * ablation_engine   : BASE vs +family vs +shuffled-family reports a real delta
  * multiple_testing  : BH FDR rejects a true signal among nulls
  * cluster_inference : clustered SE > naive SE; bootstrap CI contains the mean
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from atomics.core import rank_ic
from atomics.prediction_store import Prediction, PredictionStore
from atomics.model_registry import (ModelRegistry, CANDIDATE, TESTING, CHALLENGER,
                                     CHAMPION, GRAVEYARD)
from atomics.baseline_engine import random, historical_mean, market_return, momentum, reversal
from atomics.ablation_engine import run_ablation
from atomics.multiple_testing import MultipleTestingLedger, benjamini_hochberg
from atomics.cluster_inference import clustered_mean_se, naive_mean_se, block_bootstrap_ci

PASS = []

def check(name, cond):
    PASS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


# ---------------------------------------------------------------------------
# 1. PredictionStore — immutability
# ---------------------------------------------------------------------------
_tmp = tempfile.mkdtemp()
pstore = PredictionStore(os.path.join(_tmp, "predictions.jsonl"))
p1 = Prediction(prediction_id="P-001", experiment_id="E-1", model_id="M-1",
                timestamp="2024-01-01T09:30:00Z", symbol="ES", target_id="5m_return",
                prediction=0.0012, confidence=0.8, model_version="v1")
pstore.append(p1)
check("prediction_store appends one row", pstore.count() == 1)
try:
    pstore.append(Prediction(prediction_id="P-001", experiment_id="E-2",
                             model_id="M-2", timestamp="2024-01-01T09:31:00Z",
                             symbol="NQ", target_id="5m_return", prediction=0.0))
    check("prediction_store duplicate id raises", False)
except ValueError:
    check("prediction_store duplicate id raises", True)
try:
    pstore.append({"prediction_id": "P-001", "experiment_id": "E-3", "model_id": "M-3",
                   "timestamp": "t", "symbol": "S", "target_id": "5m_return",
                   "prediction": 0.0, "probability": None, "confidence": None,
                   "model_version": "v0"})
    check("prediction_store duplicate dict id raises", False)
except ValueError:
    check("prediction_store duplicate dict id raises", True)
# missing required field
try:
    pstore.append({"prediction_id": "P-002", "symbol": "ES"})
    check("prediction_store missing field raises", False)
except ValueError:
    check("prediction_store missing field raises", True)
# persistence across reload
pstore2 = PredictionStore(os.path.join(_tmp, "predictions.jsonl"))
check("prediction_store survives reload", pstore2.count() == 1 and pstore2.get("P-001")["symbol"] == "ES")


# ---------------------------------------------------------------------------
# 2. ModelRegistry — no auto-promotion
# ---------------------------------------------------------------------------
mreg = ModelRegistry()
mreg.register("m1")
mreg.register("m2", status=TESTING)
check("model_registry registers candidates", mreg.status("m1") == CANDIDATE)
try:
    mreg.register("m1")
    check("model_registry duplicate register raises", False)
except ValueError:
    check("model_registry duplicate register raises", True)
# cannot skip the ladder
try:
    mreg.promote("m1", CHAMPION, oos_evidence={"oos_ic": 0.05})
    check("model_registry blocks ladder skip (CANDIDATE->CHAMPION)", False)
except ValueError:
    check("model_registry blocks ladder skip (CANDIDATE->CHAMPION)", True)
# climb honestly
mreg.promote("m1", TESTING)
mreg.promote("m1", CHALLENGER)
check("model_registry climbs to CHALLENGER", mreg.status("m1") == CHALLENGER)
# the hard gate: no evidence -> no champion
try:
    mreg.promote("m1", CHAMPION)
    check("model_registry blocks auto-promote to CHAMPION (no evidence)", False)
except ValueError:
    check("model_registry blocks auto-promote to CHAMPION (no evidence)", True)
# explicit evidence -> champion
mreg.promote("m1", CHAMPION, oos_evidence={"oos_ic": 0.05, "oos_p": 0.01})
check("model_registry promotes with explicit OOS evidence", mreg.status("m1") == CHAMPION)
check("model_registry records oos_evidence", mreg.get("m1").oos_evidence.get("oos_ic") == 0.05)
# champion can only retire
try:
    mreg.promote("m1", TESTING)
    check("model_registry blocks demotion of CHAMPION", False)
except ValueError:
    check("model_registry blocks demotion of CHAMPION", True)
mreg.retire("m1")
check("model_registry retires to GRAVEYARD", mreg.status("m1") == GRAVEYARD)


# ---------------------------------------------------------------------------
# 3. Baseline engine
# ---------------------------------------------------------------------------
sig = np.array([1.0, -2.0, 3.0, -4.0])
check("baseline momentum == signal", np.allclose(momentum(sig), sig))
check("baseline reversal == -signal", np.allclose(reversal(sig), -sig))
r1, r2 = random(1000, seed=5), random(1000, seed=5)
check("baseline random reproducible", np.allclose(r1, r2) and len(r1) == 1000 and abs(r1.mean()) < 0.2)
ret = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
hm = historical_mean(ret)
check("baseline historical_mean no lookahead (first is NaN)", np.isnan(hm[0]))
check("baseline historical_mean uses strictly past", np.isclose(hm[1], 0.01) and np.isclose(hm[2], 0.015))
mr = market_return(np.array([[1.0, 2.0, 3.0], [4.0, 6.0, 8.0]]))
check("baseline market_return constant within row",
      np.allclose(mr[0], [2.0, 2.0, 2.0]) and np.allclose(mr[1], [6.0, 6.0, 6.0]))


# ---------------------------------------------------------------------------
# 4. Ablation engine — reports incremental delta
# ---------------------------------------------------------------------------
rng = np.random.default_rng(0)
n = 800
signal = rng.normal(0, 1, n)
noise = rng.normal(0, 1, n)
y = 0.5 * signal + noise
useless = rng.normal(0, 1, n)  # independent of y

def metric_fn(features):
    arrs = [np.asarray(v, dtype=float).reshape(-1) for v in features.values()]
    if not arrs:
        return 0.0
    X = np.column_stack(arrs)
    ics = [abs(rank_ic(X[:, j], y)) for j in range(X.shape[1])]
    return float(np.nanmax(ics))

res = run_ablation(metric_fn, {"signal_family": signal, "noise_family": useless},
                   base_features=None, shuffle_seed=1)
by_name = {r["family"]: r for r in res}
check("ablation reports both families", set(by_name) == {"signal_family", "noise_family"})
check("ablation base_score is zero on empty set", by_name["signal_family"]["base_score"] == 0.0)
check("ablation informative family has positive delta_add",
      by_name["signal_family"]["delta_add"] > 0.2)
check("ablation real delta exceeds shuffled delta",
      by_name["signal_family"]["delta_add"] > by_name["signal_family"]["delta_shuffled"])
check("ablation noise family adds ~nothing", by_name["noise_family"]["delta_add"] < 0.1)


# ---------------------------------------------------------------------------
# 5. Multiple testing — BH FDR rejects a true signal
# ---------------------------------------------------------------------------
ledger = MultipleTestingLedger()
ledger.record(4)
pvals = [0.001, 0.40, 0.60, 0.90]
res_led = ledger.correct(pvals, alpha=0.05)
check("ledger tracks experiments_attempted", ledger.experiments_attempted == 4)
check("FDR rejects only the significant p-value",
      res_led.rejected.tolist() == [True, False, False, False])
check("FDR n_rejected == 1", res_led.n_rejected == 1)
# standalone function agrees
rej, adj = benjamini_hochberg(pvals, alpha=0.05)
check("standalone BH agrees with ledger", rej.tolist() == [True, False, False, False])
check("BH adjusted p-values bounded by 1", bool(np.all(adj <= 1.0)) and adj[0] < 0.05)
# all-null -> nothing rejected
null_rej, _ = benjamini_hochberg([0.5, 0.6, 0.7, 0.8], alpha=0.05)
check("BH rejects nothing for all-null", int(null_rej.sum()) == 0)


# ---------------------------------------------------------------------------
# 6. Cluster inference — clustered SE + bootstrap CI
# ---------------------------------------------------------------------------
rng = np.random.default_rng(1)
dates, returns = [], []
n_days, n_per_day = 60, 20
for d in range(n_days):
    day_shock = rng.normal(0, 1)          # common shock -> positive intra-date corr
    for _ in range(n_per_day):
        dates.append(d)
        returns.append(0.01 + day_shock + rng.normal(0, 1))
returns = np.asarray(returns)
dates = np.asarray(dates)
se_cl = clustered_mean_se(returns, dates)
se_naive = naive_mean_se(returns)
check("clustered SE exceeds naive SE under date correlation", se_cl > se_naive)
ci = block_bootstrap_ci(returns, dates, n_iter=1000, alpha=0.05, seed=2)
true_mean = float(np.mean(returns))
check("bootstrap CI contains the true mean", ci.ci_low <= true_mean <= ci.ci_high)
check("bootstrap CI is finite and ordered", np.isfinite(ci.ci_low) and ci.ci_low < ci.ci_high)
check("bootstrap CI SE is positive", ci.se > 0)


print(f"\n{sum(1 for _, p in PASS if p)}/{len(PASS)} checks passed")
failures = [n for n, p in PASS if not p]
print("FAILURES:", failures if failures else "NONE")
if failures:
    sys.exit(1)
print("ALL PASS")
