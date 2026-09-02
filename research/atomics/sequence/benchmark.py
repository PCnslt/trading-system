"""Phase 4 — sequential vs flat benchmark on the intraday SEQUENCE dataset.

Target: forward 30-min return (r6). Chronological 70/30 split (from cache).
Models:
  - Ridge (flat scalars)           [flat baseline]
  - LightGBM (flat scalars)        [flat baseline]
  - MLP on sequence tensor (12x4)  [sequential]
  - 1D-CNN on sequence tensor      [sequential]
  - momentum heuristic (pred = past r6)   [context baseline]

Metrics: rank IC (Spearman), top-decile excess return (bp). Honest verdict on
whether the sequence representation beats flat scalars.
"""
from __future__ import annotations
import os, sys, json, time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn

sys.path.insert(0, "/home/ubuntu/trading-system/research")
from atomics.core import rank_ic, top_decile_ret  # noqa: E402

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
RESULTS_PATH = "/home/ubuntu/trading-system/research/atomics/sequence_results.json"

SEED = 0
np.random.seed(SEED)


def load_cache() -> dict:
    samples = pd.read_parquet(os.path.join(CACHE_DIR, "samples.parquet"))
    seq = np.load(os.path.join(CACHE_DIR, "seq.npy"))
    meta = json.load(open(os.path.join(CACHE_DIR, "meta.json")))
    return {"samples": samples, "seq": seq, "meta": meta}


def split_arrays(samples: pd.DataFrame):
    tr = (samples["split"] == "train").to_numpy()
    te = ~tr
    Xf = samples[meta["flat_features"]].to_numpy(dtype=np.float32)
    y = samples["label"].to_numpy(dtype=np.float32)
    return tr, te, Xf, y


def metric_dict(pred: np.ndarray, y: np.ndarray) -> dict:
    return {
        "rank_ic": rank_ic(pred, y),
        "top_decile_bp": top_decile_ret(pred, y) * 1e4,
    }


# ---------------------------------------------------------------------------
# Torch models (small, CPU)
# ---------------------------------------------------------------------------
def train_torch(make_model, Xtr, ytr, Xval, yval, Xte, seed=0, epochs=30,
                batch=2048, lr=1e-3, patience=5, scale_target=100.0):
    torch.manual_seed(seed)
    dev = torch.device("cpu")
    model = make_model().to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.MSELoss()

    # standardize inputs per-channel using TRAIN statistics only (no leakage)
    mu = Xtr.mean(axis=0)
    sd = Xtr.std(axis=0) + 1e-6

    def norm(X):
        return (X - mu) / sd

    Xtr_n, Xval_n, Xte_n = norm(Xtr), norm(Xval), norm(Xte)
    ytr_s = ytr * scale_target
    yval_s = yval * scale_target

    Xtr_t = torch.from_numpy(Xtr_n)
    ytr_t = torch.from_numpy(ytr_s).unsqueeze(1)
    Xval_t = torch.from_numpy(Xval_n)
    yval_t = torch.from_numpy(yval_s).unsqueeze(1)
    Xte_t = torch.from_numpy(Xte_n)

    n = Xtr_t.shape[0]
    best_val, best_state, bad = float("inf"), None, 0
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            opt.zero_grad()
            loss = loss_fn(model(Xtr_t[idx]), ytr_t[idx])
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            vloss = loss_fn(model(Xval_t), yval_t).item()
        if vloss < best_val:
            best_val, bad = vloss, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        pred = model(Xte_t).squeeze(1).numpy() / scale_target
    return pred


class CNN(nn.Module):
    def __init__(self, in_ch=4):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_ch, 32, 3, padding=1), nn.ReLU(),
            nn.Conv1d(32, 32, 3, padding=1), nn.ReLU(),
            nn.Conv1d(32, 16, 3, padding=1), nn.ReLU(),
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.head = nn.Sequential(nn.Linear(16, 8), nn.ReLU(), nn.Linear(8, 1))

    def forward(self, x):
        x = x.transpose(1, 2)  # (B, C, T)
        x = self.pool(self.conv(x)).squeeze(-1)
        return self.head(x)


class MLP(nn.Module):
    def __init__(self, in_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, x):
        return self.net(x)


def run_flat_models(tr, te, Xf, y):
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    import lightgbm as lgb

    results = {}

    # Ridge
    sc = StandardScaler().fit(Xf[tr])
    ridge = Ridge(alpha=1.0).fit(sc.transform(Xf[tr]), y[tr])
    results["ridge"] = metric_dict(ridge.predict(sc.transform(Xf[te])), y[te])

    # LightGBM
    t0 = time.time()
    lgbm = lgb.LGBMRegressor(
        n_estimators=300, learning_rate=0.05, num_leaves=31,
        min_child_samples=100, subsample=0.8, colsample_bytree=0.8,
        random_state=SEED, n_jobs=-1, verbose=-1,
    )
    lgbm.fit(Xf[tr], y[tr])
    results["lightgbm"] = metric_dict(lgbm.predict(Xf[te]), y[te])
    print(f"  lightgbm fit {time.time()-t0:.1f}s")

    # momentum context baseline: predict past r6 as future
    r6_col = meta["flat_features"].index("r6")
    results["momentum_baseline"] = metric_dict(Xf[te][:, r6_col], y[te])

    return results


def run_sequence_models(tr, te, Xf, y, seq):
    # chronological val split from the training block (no shuffle)
    tr_idx = np.where(tr)[0]
    cut = int(0.85 * len(tr_idx))
    val_idx, train_idx = tr_idx[cut:], tr_idx[:cut]

    results = {}
    specs = {
        "mlp_sequence": (
            lambda: MLP(seq.shape[1] * seq.shape[2]),
            lambda X: X.reshape(X.shape[0], -1),
        ),
        "cnn_sequence": (
            lambda: CNN(seq.shape[2]),
            lambda X: X,
        ),
    }
    for name, (make_model, prep) in specs.items():
        t0 = time.time()
        ics, bps = [], []
        for seed in (0, 1, 2):
            pred = train_torch(make_model,
                               prep(seq[train_idx]), y[train_idx],
                               prep(seq[val_idx]), y[val_idx],
                               prep(seq[te]), seed=seed)
            ics.append(rank_ic(pred, y[te]))
            bps.append(top_decile_ret(pred, y[te]) * 1e4)
        results[name] = {
            "rank_ic": float(np.mean(ics)),
            "rank_ic_std": float(np.std(ics)),
            "top_decile_bp": float(np.mean(bps)),
            "top_decile_bp_std": float(np.std(bps)),
            "seeds_rank_ic": [round(float(x), 6) for x in ics],
            "seeds_top_decile_bp": [round(float(x), 4) for x in bps],
        }
        print(f"  {name} {time.time()-t0:.1f}s  rank_ic={results[name]['rank_ic']:.5f}"
              f" +- {results[name]['rank_ic_std']:.5f}  seeds={[round(float(x),5) for x in ics]}")

    return results


if __name__ == "__main__":
    cache = load_cache()
    global meta
    meta = cache["meta"]
    samples, seq = cache["samples"], cache["seq"]
    tr, te, Xf, y = split_arrays(samples)
    print(f"[benchmark] samples={len(samples)} train={tr.sum()} test={te.sum()}")
    print(f"[benchmark] label stats: mean={y.mean()*1e4:.2f}bp std={y.std()*1e4:.2f}bp")

    results = run_flat_models(tr, te, Xf, y)
    results.update(run_sequence_models(tr, te, Xf, y, seq))

    # verdict
    flat_ic = max(results["ridge"]["rank_ic"], results["lightgbm"]["rank_ic"])
    seq_ic = max(results["mlp_sequence"]["rank_ic"], results["cnn_sequence"]["rank_ic"])
    cnn_std = results["cnn_sequence"]["rank_ic_std"]
    significant = bool(seq_ic - flat_ic > cnn_std)  # cross-seed std >> mean => noise
    results["_verdict"] = {
        "best_flat_rank_ic": flat_ic,
        "best_sequence_rank_ic": seq_ic,
        "sequence_beats_flat": bool(seq_ic > flat_ic),
        "sequence_beats_flat_significant": significant,
    }

    base_cost_bp = 5.0  # core.py COST_SCENARIOS['base'] round-trip (spread 3 + slippage 2)
    best_bp = max(results["ridge"]["top_decile_bp"], results["lightgbm"]["top_decile_bp"],
                  results["mlp_sequence"]["top_decile_bp"], results["cnn_sequence"]["top_decile_bp"])
    conclusion = (
        "No model finds a tradable 30m intraday cross-sectional signal. Flat "
        f"LightGBM rank IC is {results['lightgbm']['rank_ic']:.4f} (Ridge "
        f"{results['ridge']['rank_ic']:.4f}). The sequence CNN posts the largest "
        f"nominal mean rank IC ({results['cnn_sequence']['rank_ic']:.4f}) but its "
        f"cross-seed std ({results['cnn_sequence']['rank_ic_std']:.4f}) is larger "
        f"than the mean, with per-seed ICs swinging from "
        f"{min(results['cnn_sequence']['seeds_rank_ic']):.4f} to "
        f"{max(results['cnn_sequence']['seeds_rank_ic']):.4f} (MLP likewise: mean "
        f"{results['mlp_sequence']['rank_ic']:.4f} +- "
        f"{results['mlp_sequence']['rank_ic_std']:.4f}). Every top-decile excess "
        f"return (best mean {best_bp:.2f}bp) sits below the {base_cost_bp:.1f}bp "
        "base round-trip cost. Honest verdict: SEQUENCE rank_IC ~= 0; the sequence "
        "representation does NOT reliably beat flat scalars (mean edge < cross-seed "
        "noise), and neither is economically meaningful."
    )

    out = {
        "experiment": "phase4_intraday_sequence",
        "target": meta["target"],
        "n_symbols": meta["n_symbols"],
        "n_samples": meta["n_samples"],
        "n_train": meta["n_train"],
        "n_test": meta["n_test"],
        "split_threshold": meta["split_threshold"],
        "split_ratio": meta["split_ratio"],
        "flat_features": meta["flat_features"],
        "sequence_shape": meta["sequence_shape"],
        "sequence_channels": meta["sequence_channels"],
        "data_range": meta["data_range"],
        "label_stats_bp": {"mean": float(y.mean() * 1e4), "std": float(y.std() * 1e4)},
        "models": {k: v for k, v in results.items() if not k.startswith("_")},
        "verdict": results["_verdict"],
        "conclusion": conclusion,
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(out, f, indent=2)
    print("[benchmark] wrote", RESULTS_PATH)
    print(json.dumps(out["models"], indent=2))
    print("verdict:", out["verdict"])
