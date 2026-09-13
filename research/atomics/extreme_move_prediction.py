#!/usr/bin/env python
"""
EXTREME-MOVE PREDICTION (research atomic).

Question: can realized volatility, relative volume, prior |return|, and range
expansion predict P(|forward 30m return| > 1%) and P(> 2%)?

Data: 5-min RTH bars (S3 'ibkr/equities/5min/{SYM}.parquet', 40 liquid names,
~2026-01-02 -> 2026-09-01). Features are strictly causal (only info <= t).
Chronological 70/30 split, logistic classifier (sklearn), ROC-AUC + precision@
high-confidence + top-decile realized |forward return|.

Research-only. No orders, no data purchase, no writes to the lake.
"""
import io
import json
import os

import boto3
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

BUCKET = "trading-datalake-920641308584"
PREFIX = "ibkr/equities/5min/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extreme_move_results.json")

# ---- target thresholds for |forward 30m return| ----
THRESHOLDS = [0.01, 0.02]
FWD_BARS = 6  # 6 x 5-min = 30 minutes


def load_all():
    s3 = boto3.client("s3", region_name="us-east-1")
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".parquet")]

    frames = []
    for k in keys:
        sym = k.split("/")[-1].replace(".parquet", "")
        buf = io.BytesIO()
        s3.download_fileobj(BUCKET, k, buf)
        buf.seek(0)
        df = pd.read_parquet(buf)
        df["symbol"] = sym
        frames.append(df)
    data = pd.concat(frames, ignore_index=True)
    data = data.sort_values(["symbol", "date"]).reset_index(drop=True)
    return data


def build_features(data):
    df = data.copy()
    # drop no-trade placeholder bars (flat + zero volume + barCount==0)
    placeholder = (df["volume"] == 0) & (df["barCount"] == 0) & \
                  (df["open"] == df["high"]) & (df["high"] == df["low"]) & (df["low"] == df["close"])
    df = df[~placeholder].copy()

    df["session"] = df["date"].dt.date

    # --- forward 30m return (within-session; last 6 bars of each day -> NaN) ---
    df["fwd_close"] = df.groupby(["symbol", "session"])["close"].shift(-FWD_BARS)
    df["fwd_ret_30m"] = df["fwd_close"] / df["close"] - 1.0

    # --- causal features (all computed with trailing/backward windows only) ---
    grp = df.groupby("symbol", group_keys=False)

    df["logret"] = np.log(df["close"] / grp["close"].shift(1))

    # realized volatility: trailing std of 5-min log returns, 1h and 2h lookbacks
    df["rv_12"] = grp["logret"].transform(lambda s: s.rolling(12, min_periods=6).std())
    df["rv_24"] = grp["logret"].transform(lambda s: s.rolling(24, min_periods=12).std())

    # relative volume: trailing 12-bar mean volume vs 78-bar (1-day) baseline
    df["vol12"] = grp["volume"].transform(lambda s: s.rolling(12, min_periods=6).mean())
    df["vol78"] = grp["volume"].transform(lambda s: s.rolling(78, min_periods=39).mean())
    df["rel_volume"] = df["vol12"] / df["vol78"]

    # prior |return|: last 30m and last bar absolute returns
    df["prior_abs_ret_6"] = grp["close"].pct_change(FWD_BARS).abs()
    df["prior_abs_ret_1"] = grp["close"].pct_change(1).abs()

    # range expansion: current bar (high-low) vs trailing 24-bar average range
    df["range"] = df["high"] - df["low"]
    df["range_ma24"] = grp["range"].transform(lambda s: s.rolling(24, min_periods=12).mean())
    df["range_expansion"] = df["range"] / df["range_ma24"]

    return df


FEATURES = [
    "rv_12",
    "rv_24",
    "rel_volume",
    "prior_abs_ret_6",
    "prior_abs_ret_1",
    "range_expansion",
]


def chronological_split(df):
    """70/30 split on global time order (train strictly before test)."""
    df = df.sort_values("date").reset_index(drop=True)
    n = len(df)
    cut = int(n * 0.7)
    return df.iloc[:cut], df.iloc[cut:]


def evaluate(model, X_train, y_train, X_test, y_test, fwd_ret_test):
    model.fit(X_train, y_train)
    p = model.predict_proba(X_test)[:, 1]

    base = y_test.mean()
    auc = roc_auc_score(y_test, p) if y_test.nunique() > 1 else float("nan")

    order = np.argsort(-p)  # descending predicted prob
    def top_bucket(frac):
        k = max(1, int(len(order) * frac))
        idx = order[:k]
        prec = y_test.iloc[idx].mean()
        rec = y_test.iloc[idx].sum() / y_test.sum() if y_test.sum() > 0 else float("nan")
        return {"frac": frac, "n": int(k),
                "precision": float(prec), "recall": float(rec),
                "lift_vs_base": float(prec / base) if base > 0 else float("nan")}

    # top-decile realized |forward return| (answers the headline question)
    deciles = {}
    for d in range(1, 11):
        lo = int(len(order) * (d - 1) / 10)
        hi = int(len(order) * d / 10)
        idx = order[lo:hi]
        deciles[f"decile_{d}"] = {
            "mean_pred_prob": float(p[idx].mean()),
            "mean_abs_fwd_ret": float(np.abs(fwd_ret_test.iloc[idx]).mean()),
            "n": int(len(idx)),
        }

    top_idx = order[: int(len(order) * 0.1)]
    bot_idx = order[int(len(order) * 0.9):]
    top_mean = float(np.abs(fwd_ret_test.iloc[top_idx]).mean())
    bot_mean = float(np.abs(fwd_ret_test.iloc[bot_idx]).mean())
    overall_mean = float(np.abs(fwd_ret_test).mean())

    return {
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "base_rate": float(base),
        "n_pos_test": int(y_test.sum()),
        "roc_auc": float(auc),
        "precision_at_top_10pct": top_bucket(0.10),
        "precision_at_top_5pct": top_bucket(0.05),
        "precision_at_top_1pct": top_bucket(0.01),
        "decile_realized_abs_fwd_ret": deciles,
        "top_decile_mean_abs_fwd_ret": top_mean,
        "bottom_decile_mean_abs_fwd_ret": bot_mean,
        "overall_mean_abs_fwd_ret": overall_mean,
        "top_minus_bottom": top_mean - bot_mean,
        "top_vs_overall_ratio": top_mean / overall_mean if overall_mean > 0 else float("nan"),
        "logistic_coefs": {f: float(c) for f, c in zip(FEATURES, model.coef_[0])},
        "intercept": float(model.intercept_[0]),
    }


def main():
    data = load_all()
    df = build_features(data)

    # raw feature matrix (no scaling yet)
    X_raw = df[FEATURES].values.astype(float)

    # drop rows with missing features or missing forward return
    valid = np.isfinite(X_raw).all(axis=1) & df["fwd_ret_30m"].notna().values
    X_raw = X_raw[valid]
    df_valid = df[valid].reset_index(drop=True)
    fwd_ret = df_valid["fwd_ret_30m"].values
    dates = df_valid["date"].values

    # chronological 70/30 split on global time (train strictly before test)
    order = np.argsort(dates, kind="stable")
    n = len(df_valid)
    cut = int(n * 0.7)
    tr_idx = order[:cut]
    te_idx = order[cut:]

    X_train = X_raw[tr_idx]
    X_test = X_raw[te_idx]
    fwd_ret_test = fwd_ret[te_idx]
    split_date_train_max = str(df_valid["date"].iloc[tr_idx].max())
    split_date_test_min = str(df_valid["date"].iloc[te_idx].min())
    train_min = str(df_valid["date"].iloc[tr_idx].min())
    test_max = str(df_valid["date"].iloc[te_idx].max())

    # standardize features INSIDE the train/test split (no scaler leakage)
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    results = {
        "task": "extreme_move_prediction",
        "description": ("Logistic regression predicting P(|forward 30m return| > thr) from "
                        "realized vol, relative volume, prior |return|, and range expansion. "
                        "Chronological 70/30 split, causal features only."),
        "data": {
            "bucket": BUCKET,
            "prefix": PREFIX,
            "n_symbols": int(df["symbol"].nunique()),
            "n_bars_total": int(len(df)),
            "n_bars_used": int(len(df_valid)),
            "forward_horizon_bars": FWD_BARS,
            "forward_horizon_minutes": FWD_BARS * 5,
            "features": FEATURES,
            "date_min": str(df["date"].min()),
            "date_max": str(df["date"].max()),
            "split": "chronological 70/30 (train strictly before test)",
            "train_date_range": [train_min, split_date_train_max],
            "test_date_range": [split_date_test_min, test_max],
            "n_train": int(len(tr_idx)),
            "n_test": int(len(te_idx)),
        },
        "targets": {},
    }

    for thr in THRESHOLDS:
        y = (np.abs(fwd_ret) > thr).astype(int)
        y_train = pd.Series(y[tr_idx])
        y_test = pd.Series(y[te_idx])
        model = LogisticRegression(max_iter=2000, class_weight="balanced", solver="lbfgs")
        res = evaluate(model, X_train, y_train, X_test, y_test,
                       pd.Series(fwd_ret_test))
        res["threshold"] = thr
        results["targets"][f"abs_fwd_30m_gt_{int(thr*100)}pct"] = res

        # univariate ROC-AUC diagnostics (each feature alone)
        uni = {}
        for j, f in enumerate(FEATURES):
            try:
                a = roc_auc_score(y_test, X_test[:, j])
            except Exception:
                a = float("nan")
            uni[f] = float(a)
        results["targets"][f"abs_fwd_30m_gt_{int(thr*100)}pct"]["univariate_roc_auc"] = uni

    with open(OUT, "w") as fh:
        json.dump(results, fh, indent=2)

    print(json.dumps(results, indent=2))
    print(f"\nWROTE {OUT}")


if __name__ == "__main__":
    main()
