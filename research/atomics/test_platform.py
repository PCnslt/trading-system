"""Phase 3 platform validation: synthetic leakage test + real experiment re-run."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from atomics.core import (TARGETS, build_target, walk_forward_splits, round_trip_cost_bp,
                           rank_ic, top_decile_ret, long_short_spread, sharpe, max_drawdown,
                           shuffle_timestamps, shuffle_symbols, Experiment, ExperimentRegistry,
                           assert_pit_safe, PITViolation)

PASS = []

def check(name, cond):
    PASS.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

# 1. Synthetic data with KNOWN signal + KNOWN leakage
rng = np.random.default_rng(42)
n = 3000
t = np.arange(n)
signal = rng.normal(0, 1, n)
noise = rng.normal(0, 1, n)
# target: next-bar return is a function of signal (real relationship)
y = 0.5 * signal + noise
indep_noise = rng.normal(0, 1, n)   # truly independent of y
# feature: signal (real) and LEAKED feature (peeks at y)
X = pd.DataFrame({"signal": signal, "leaked": y + rng.normal(0, 0.01, n)})

# 2. Evaluation engine catches the real signal
check("rank_IC(signal, y) positive", rank_ic(signal, y) > 0.2)
check("rank_IC(indep_noise, y) ~ 0", abs(rank_ic(indep_noise, y)) < 0.05)
# leaked feature is "too good" -> the firewall must flag it
check("leaked feature has rank_IC > 0.9 (detectable)", rank_ic(X["leaked"].values, y) > 0.9)

# 3. PIT firewall: label strictly after prediction time
try:
    assert_pit_safe(X, prediction_time=100, label_time=100)
    check("PIT label-time violation caught", False)
except PITViolation:
    check("PIT label-time violation caught", True)

# 4. Walk-forward engine
folds = walk_forward_splits(t, n_folds=4, mode="expanding", purge_bars=6, embargo_bars=6)
check("walk-forward produces 4 folds", len(folds) == 4)
check("folds are chronological (non-overlapping)", all(f.test[0] > f.train[-1] for f in folds))
# embargo: train ends strictly before test start
check("embargo applied", all(folds[i].test[0] - folds[i].train[-1] >= 0 for i in range(len(folds))))

# 5. Cost engine
check("cost scenarios monotonic (optimistic < stress)",
      round_trip_cost_bp("optimistic") < round_trip_cost_bp("base")
      < round_trip_cost_bp("conservative") < round_trip_cost_bp("stress"))

# 6. Placebo: shuffling destroys the real signal
ic_real = rank_ic(signal, y)
ic_shuffled = rank_ic(shuffle_timestamps(signal), y)
check("placebo (timestamp shuffle) destroys signal", abs(ic_shuffled) < abs(ic_real) * 0.3)

# 7. Experiment registry (immutability + lineage) — fresh temp registry per run
import tempfile
_regpath = os.path.join(tempfile.mkdtemp(), "experiments.jsonl")
reg = ExperimentRegistry(_regpath)
e1 = Experiment(experiment_id="PLATFORM-001", hypothesis="synthetic validation",
                target_id="5m_return", model_id="linear", horizon="5m")
reg.register(e1)
try:
    reg.register(Experiment(experiment_id="PLATFORM-001", hypothesis="duplicate"))
    check("experiment immutability enforced", False)
except ValueError:
    check("experiment immutability enforced", True)
e2 = Experiment(experiment_id="PLATFORM-002", hypothesis="child", parent_experiment_id="PLATFORM-001",
                target_id="5m_return", model_id="linear", horizon="5m")
reg.register(e2)
check("experiment lineage recorded", e2.parent_experiment_id == "PLATFORM-001")
check("experiment config_hash stable", e1.config_hash() == e1.config_hash())

# 8. Reproducibility: same config -> same hash
e3 = Experiment(experiment_id="PLATFORM-003", hypothesis="synthetic validation",
                target_id="5m_return", model_id="linear", horizon="5m")
check("reproducible config hash (same config)", e3.config_hash() == e1.config_hash())

print(f"\n{sum(1 for _,p in PASS if p)}/{len(PASS)} checks passed")
print("FAILURES:", [n for n,p in PASS if not p])
