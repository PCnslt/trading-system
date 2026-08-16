"""Rigorous validation of Connors RSI(2) long-only mean-reversion on a FIXED
liquidity-ranked universe of 50 S&P 100 large-caps.

Method (no data-mining):
  * Fixed universe by liquidity (top-50 avg dollar volume), not past returns.
  * Entry RSI(2)<thr AND close>SMA200, thr in {2,5,10}; next-open fill.
  * Exit: hard stop 2*ATR -> 5-day time stop -> revert (close>SMA5 | RSI2>70).
  * Fixed stop vs trailing (tighten-only 1*ATR ratchet).
  * Cost: bps-per-side {0, 5, 10} post-applied (Robinhood $0 comm + spread).
  * Walk-forward: 5 expanding folds; threshold chosen from TRAIN ONLY (no-feedback).
Outputs: results JSON + markdown report.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

import numpy as np
import pandas as pd

import stock_mr_engine as E

OUT_JSON = "/home/ubuntu/trading-system/research/stock_mr_results.json"
PKL = "/tmp/stock_mr_ohlcv.pkl"
BPS_GRID = (0.0, 0.0005, 0.0010)  # 0, 5bps, 10bps per side

FOLDS = [
    ("2006-01-01", "2010-01-01"),
    ("2010-01-01", "2014-01-01"),
    ("2014-01-01", "2018-01-01"),
    ("2018-01-01", "2022-01-01"),
    ("2022-01-01", "2026-12-31"),
]


def load():
    df = pd.read_pickle(PKL)
    return df


def pooled_stats(trades, bps=0.0):
    """Pool across symbols with fractional returns (equal weight per trade)."""
    if not trades:
        return {"n": 0, "pf": float("nan"), "win": float("nan"),
                "avg_hold": float("nan"), "net": 0.0, "gross_ret": 0.0}
    rets = np.array([
        (t["exit_price"] * (1 - bps)) / (t["entry_price"] * (1 + bps)) - 1.0
        for t in trades
    ])
    wins = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    holds = np.array([t["hold_days"] for t in trades], dtype=float)
    return {
        "n": int(len(trades)),
        "pf": float(pf),
        "win": float((rets > 0).mean()),
        "avg_hold": float(holds.mean()),
        "net": float(rets.sum()),          # sum of per-trade frac returns (equal weight)
        "worst": float(rets.min()),
        "best": float(rets.max()),
    }


def equity_curve_maxdd(trades, close_by_sym, bps=0.0):
    """Daily mark-to-market portfolio curve (equal $1 per trade), max drawdown."""
    if not trades:
        return float("nan"), None
    daily = defaultdict(float)
    for t in trades:
        closes = close_by_sym[t["symbol"]]
        entry_adj = t["entry_price"] * (1 + bps)
        for i in range(t["entry_i"], t["exit_i"] + 1):
            if i == t["exit_i"]:
                px = t["exit_price"] * (1 - bps)
            else:
                px = closes[i]
            daily[i] += px / entry_adj - 1.0
    eq = pd.Series(daily).sort_index().cumsum()
    dd = float((eq - eq.cummax()).min())
    return dd, eq


def build_trades(data: dict, thr: int, stop_mode: str):
    trades = []
    for sym, df in data.items():
        trades.extend(E.run_symbol(df, sym, thr, stop_mode))
    return trades


def per_year(trades, bps=0.0):
    """Per-year pooled PF / win / n (entry-year bucketing)."""
    by = defaultdict(list)
    for t in trades:
        by[t["entry_date"].year].append(t)
    out = {}
    for y in sorted(by):
        out[y] = pooled_stats(by[y], bps)
    return out


def regime_split(trades, bps=0.0):
    regimes = [
        ("pre-GFC 2000-07", "2000-01-01", "2008-01-01"),
        ("GFC 2008-09", "2008-01-01", "2010-01-01"),
        ("bull-grind 2010-19", "2010-01-01", "2020-01-01"),
        ("COVID+bear 2020-22", "2020-01-01", "2023-01-01"),
        ("bull 2023-25", "2023-01-01", "2026-01-01"),
    ]
    out = {}
    for name, a, b in regimes:
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        sub = [t for t in trades if a <= t["entry_date"] < b]
        out[name] = pooled_stats(sub, bps)
    return out


def main():
    t0 = time.time()
    df = load()
    # split back into per-symbol frames with position index preserved
    data = {}
    for sym, g in df.groupby(level=0):
        if g.index.nlevels > 1:
            g = g.droplevel(0)
        data[sym] = g  # keep DatetimeIndex (engine uses d.index[i] for dates)
    print(f"loaded {len(data)} symbols")

    # per-symbol close numpy arrays for mark-to-market
    close_by_sym = {s: d["close"].to_numpy() for s, d in data.items()}

    # --- run all configs (6 per symbol), cache trades ---
    trades = {}  # (thr, mode) -> list of trades
    for thr in E.THRESHOLDS:
        for mode in E.STOP_MODES:
            trades[(thr, mode)] = build_trades(data, thr, mode)
            print(f"  thr={thr} mode={mode}: {len(trades[(thr,mode)])} trades "
                  f"({time.time()-t0:.0f}s)")

    res = {"universe": sorted(data.keys()),
           "universe_n": len(data),
           "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    # --- full-sample threshold sweep (in-sample reference) ---
    sweep = {}
    for thr in E.THRESHOLDS:
        sweep[thr] = {}
        for bps in BPS_GRID:
            sweep[thr][f"{bps:.4f}"] = pooled_stats(trades[(thr, "fixed")], bps)
    res["full_sample_fixed"] = sweep

    # --- walk-forward (expanding folds, threshold from train only) ---
    wf = {"folds": [], "pooled_oos": {}}
    oos_all = []   # chosen-threshold OOS trades across folds
    for (a, b) in FOLDS:
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        # train = entry < a ; select threshold by train PF @5bps (deployable cost)
        train_pf = {}
        for thr in E.THRESHOLDS:
            train = [t for t in trades[(thr, "fixed")] if t["entry_date"] < a]
            train_pf[thr] = pooled_stats(train, 0.0005)["pf"]
        chosen = max(train_pf, key=lambda k: (train_pf[k] if train_pf[k] == train_pf[k] else -1))
        fold_oos = [t for t in trades[(chosen, "fixed")] if a <= t["entry_date"] < b]
        oos_all.extend(fold_oos)
        wf["folds"].append({
            "test": [str(a.date()), str(b.date())],
            "train_pf_by_thr": {str(k): (v if v == v else None) for k, v in train_pf.items()},
            "chosen_thr": chosen,
            "oos": pooled_stats(fold_oos, 0.0),
            "oos_5bps": pooled_stats(fold_oos, 0.0005),
        })
    for bps in BPS_GRID:
        wf["pooled_oos"][f"{bps:.4f}"] = pooled_stats(oos_all, bps)
    res["walk_forward"] = wf

    # --- per-year PF (fixed stop) at each threshold, 0 & 5 bps ---
    peryear = {}
    for thr in E.THRESHOLDS:
        peryear[thr] = {
            "0bps": per_year(trades[(thr, "fixed")], 0.0),
            "5bps": per_year(trades[(thr, "fixed")], 0.0005),
        }
    res["per_year"] = peryear

    # --- regime split (fixed stop, thr=5, 0 & 5 bps) ---
    res["regimes_thr5"] = {
        "0bps": regime_split(trades[(5, "fixed")], 0.0),
        "5bps": regime_split(trades[(5, "fixed")], 0.0005),
    }

    # --- fixed vs trailing (0 & 5 bps), plus tighten-event rate ---
    tv = {}
    for thr in E.THRESHOLDS:
        tv[thr] = {}
        for bps in (0.0, 0.0005):
            f = trades[(thr, "fixed")]
            t = trades[(thr, "trail")]
            tv[thr][f"{bps:.4f}"] = {
                "fixed": pooled_stats(f, bps),
                "trail": pooled_stats(t, bps),
            }
        # stop-out rate delta as a proxy for "did the trail change exits"
        tv[thr]["stop_out_rate"] = {
            "fixed": float(np.mean([x["reason"] == "stop" for x in trades[(thr, "fixed")]])),
            "trail": float(np.mean([x["reason"] == "stop" for x in trades[(thr, "trail")]])),
        }
        tv[thr]["exit_reason_mix_fixed"] = dict(pd.Series(
            [x["reason"] for x in trades[(thr, "fixed")]]).value_counts())
        tv[thr]["exit_reason_mix_trail"] = dict(pd.Series(
            [x["reason"] for x in trades[(thr, "trail")]]).value_counts())
    res["trailing_vs_fixed"] = tv

    # --- maxDD (daily equity curve) at 0 & 5 bps, fixed stop, each threshold ---
    dd = {}
    for thr in E.THRESHOLDS:
        dd[thr] = {}
        for bps in (0.0, 0.0005):
            d, _ = equity_curve_maxdd(trades[(thr, "fixed")], close_by_sym, bps)
            dd[thr][f"{bps:.4f}"] = d
    res["maxdd_fixed"] = dd

    # --- diagnostic: signal hit count vs trade count (bug-check) ---
    diag = {}
    for thr in E.THRESHOLDS:
        hits = 0
        for sym, d in data.items():
            d = E.indicators(d)
            w = 200
            hits += int(((d["rsi2"].iloc[w:-1].to_numpy() < thr) &
                         (d["close"].iloc[w:-1].to_numpy() > d["sma200"].iloc[w:-1].to_numpy())).sum())
        diag[thr] = {"signal_hits": hits, "trades_fixed": len(trades[(thr, "fixed")])}
    res["diagnostic"] = diag

    with open(OUT_JSON, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\nwrote {OUT_JSON} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
