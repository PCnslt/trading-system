"""Index regime-gate validation: does an SPY>SMA200 filter kill RSI2's bear-year
bleed (2008 PF 0.36 / 2022 PF 0.81) WITHOUT gutting the walk-forward OOS (~1.47)?

Compares two variants of the SAME Connors RSI(2) long-only strategy on the fixed
50-name S&P100 liquidity universe (split+dividend adjusted, next-open fill,
2xATR intraday GTC stop, 5d time stop, revert close>SMA5 | RSI2>70):

  BASE   = entry RSI(2)<thr AND close>SMA200          (per-name trend filter only)
  GATED  = BASE AND SPY close > SPY SMA200            (+ index-level regime gate)

The gate is baked INTO the engine's entry loop (not post-filtered), so a gated-out
trade correctly unblocks a later re-entry the base variant never took.

Window: 1993-02-01 -> end of data (SPY inception onward). SPY only exists from
1993-01-29, so an index gate is unevaluable before that; restricting BOTH variants
to the same window makes the comparison apples-to-apples. Bear years of interest
(2001/2008/2018/2020/2022) are all deep inside the window.

Outputs: printed side-by-side + research/regime_gate_results.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stock_mr_engine as E  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PKL = "/tmp/stock_mr_ohlcv.pkl"
SPY_PKL = "/tmp/spy_gate.pkl"
OUT = os.path.join(HERE, "regime_gate_results.json")

THRESHOLDS = (2, 5, 10)
BPS_GRID = (0.0, 0.0005, 0.0010)  # 0, 5bps, 10bps per side
MIN_DATE = pd.Timestamp("1993-02-01")

# Same expanding folds as stock_mr_validate (2006-2026), entry-date bucketed.
FOLDS = [
    ("2006-01-01", "2010-01-01"),
    ("2010-01-01", "2014-01-01"),
    ("2014-01-01", "2018-01-01"),
    ("2018-01-01", "2022-01-01"),
    ("2022-01-01", "2026-12-31"),
]

BEAR_YEARS = (2001, 2008, 2011, 2018, 2020, 2022, 2025)


def load_symbols():
    df = pd.read_pickle(PKL)
    data = {}
    for sym, g in df.groupby(level=0):
        if g.index.nlevels > 1:
            g = g.droplevel(0)
        data[sym] = g
    return data


def load_gate():
    """SPY close > SPY SMA200 as a boolean Series indexed by SPY trading dates."""
    spy = pd.read_pickle(SPY_PKL)
    gate = spy["close"] > spy["close"].rolling(200).mean()
    return gate.dropna()


def pooled_stats(trades, bps=0.0):
    if not trades:
        return {"n": 0, "pf": float("nan"), "win": float("nan"),
                "avg_hold": float("nan"), "net": 0.0}
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
        "net": float(rets.sum()),
    }


def per_year(trades, bps=0.0):
    by = defaultdict(list)
    for t in trades:
        by[t["entry_date"].year].append(t)
    return {y: pooled_stats(by[y], bps) for y in sorted(by)}


def build_trades(data, thr, gate):
    trades = []
    for sym, df in data.items():
        trades.extend(E.run_symbol(df, sym, thr, "fixed", gate=gate))
    return trades


def restrict(trades, lo=MIN_DATE):
    return [t for t in trades if t["entry_date"] >= lo]


def walk_forward(trades_by_thr, bps_select=0.0005):
    """Expanding-fold OOS, threshold selected from TRAIN ONLY (no-feedback)."""
    folds_out = []
    oos_all = []
    for (a, b) in FOLDS:
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        train_pf = {}
        for thr in THRESHOLDS:
            train = [t for t in trades_by_thr[thr] if MIN_DATE <= t["entry_date"] < a]
            train_pf[thr] = pooled_stats(train, bps_select)["pf"]
        chosen = max(train_pf, key=lambda k: (train_pf[k] if train_pf[k] == train_pf[k] else -1))
        fold_oos = [t for t in trades_by_thr[chosen] if a <= t["entry_date"] < b]
        oos_all.extend(fold_oos)
        folds_out.append({
            "test": [str(a.date()), str(b.date())],
            "chosen_thr": chosen,
            "oos": pooled_stats(fold_oos, 0.0),
            "oos_5bps": pooled_stats(fold_oos, 0.0005),
        })
    return folds_out, pooled_stats(oos_all, 0.0), pooled_stats(oos_all, 0.0005)


def main():
    t0 = time.time()
    data = load_symbols()
    gate = load_gate()
    print(f"loaded {len(data)} symbols; SPY gate {len(gate)} bars "
          f"{gate.index.min().date()} -> {gate.index.max().date()}")
    print(f"gate ON fraction: {gate.mean():.1%} of bars (SPY > SMA200)\n")

    res = {"universe": sorted(data.keys()), "n_symbols": len(data),
           "window": [str(MIN_DATE.date()), str(max(d.index.max() for d in data.values()).date())],
           "gate": "SPY close > SPY SMA200",
           "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "variants": {}}

    for label, g in (("base", None), ("gated", gate)):
        trades_by_thr = {}
        for thr in THRESHOLDS:
            tr = build_trades(data, thr, g)
            trades_by_thr[thr] = restrict(tr)
            print(f"  [{label}] thr={thr}: {len(tr)} raw -> "
                  f"{len(trades_by_thr[thr])} post-1993 trades ({time.time()-t0:.0f}s)")
        res["variants"][label] = {"trades_by_thr": {str(k): len(v) for k, v in trades_by_thr.items()}}

        # full-sample (IS, 1993+) sweep
        full = {}
        for thr in THRESHOLDS:
            full[thr] = {f"{bps:.4f}": pooled_stats(trades_by_thr[thr], bps)
                         for bps in BPS_GRID}
        res["variants"][label]["full_sample"] = full

        # walk-forward (threshold-selected) OOS
        folds, oos0, oos5 = walk_forward(trades_by_thr)
        res["variants"][label]["walk_forward"] = {
            "folds": folds, "pooled_oos_0bps": oos0, "pooled_oos_5bps": oos5}

        # per-year (thr=2 and thr=5, 0bps) for the bear-year question
        peryear = {}
        for thr in (2, 5):
            peryear[thr] = per_year(trades_by_thr[thr], 0.0)
        res["variants"][label]["per_year"] = {str(k): v for k, v in peryear.items()}

    # ---- print comparison ----
    print("=" * 92)
    print("FULL-SAMPLE (1993+) PF  [n / win%]      BASE          GATED")
    print("=" * 92)
    for thr in (2, 5):
        for bps, tag in ((0.0, "0bps"), (0.0005, "5bps")):
            b = res["variants"]["base"]["full_sample"][thr][f"{bps:.4f}"]
            g = res["variants"]["gated"]["full_sample"][thr][f"{bps:.4f}"]
            print(f"  thr={thr} {tag:5s}   {b['pf']:6.2f} [{b['n']:5d}/{b['win']*100:4.1f}%]   "
                  f"   {g['pf']:6.2f} [{g['n']:5d}/{g['win']*100:4.1f}%]")
    print()
    print("WALK-FORWARD POOLED OOS (threshold-selected from train)")
    print("=" * 92)
    for bps, tag in ((0.0, "0bps"), (0.0005, "5bps")):
        b = res["variants"]["base"]["walk_forward"][f"pooled_oos_{tag}"]
        g = res["variants"]["gated"]["walk_forward"][f"pooled_oos_{tag}"]
        print(f"  {tag:5s}   PF {b['pf']:6.2f} [n={b['n']:5d}]  net={b['net']*100:6.1f}%   ->   "
              f"PF {g['pf']:6.2f} [n={g['n']:5d}]  net={g['net']*100:6.1f}%")
    print("  folds (base -> gated OOS PF @0bps):")
    for i, fb in enumerate(res["variants"]["base"]["walk_forward"]["folds"]):
        fg = res["variants"]["gated"]["walk_forward"]["folds"][i]
        print(f"    {fb['test'][0][:4]}-{fb['test'][1][:4]}: base {fb['oos']['pf']:5.2f} "
              f"(thr={fb['chosen_thr']}) -> gated {fg['oos']['pf']:5.2f} (thr={fg['chosen_thr']})")
    print()
    print("PER-YEAR PF @0bps (thr=5)  —  BASE vs GATED  [bear years flagged]")
    print("=" * 92)
    bp5 = res["variants"]["base"]["per_year"]["5"]
    gp5 = res["variants"]["gated"]["per_year"]["5"]
    years = sorted(set(bp5) | set(gp5))
    for y in years:
        b = bp5.get(y, {}).get("pf", float("nan"))
        g = gp5.get(y, {}).get("pf", float("nan"))
        bn = bp5.get(y, {}).get("n", 0)
        gn = gp5.get(y, {}).get("n", 0)
        flag = "  <-- BEAR" if y in BEAR_YEARS else ""
        print(f"  {y}: base PF {b:6.2f} (n={bn:4d})   gated PF {g:6.2f} (n={gn:4d}){flag}")

    print()
    print("PER-YEAR PF @0bps (thr=2)  —  BASE vs GATED")
    print("=" * 92)
    bp2 = res["variants"]["base"]["per_year"]["2"]
    gp2 = res["variants"]["gated"]["per_year"]["2"]
    years2 = sorted(set(bp2) | set(gp2))
    for y in years2:
        b = bp2.get(y, {}).get("pf", float("nan"))
        g = gp2.get(y, {}).get("pf", float("nan"))
        bn = bp2.get(y, {}).get("n", 0)
        gn = gp2.get(y, {}).get("n", 0)
        flag = "  <-- BEAR" if y in BEAR_YEARS else ""
        print(f"  {y}: base PF {b:6.2f} (n={bn:4d})   gated PF {g:6.2f} (n={gn:4d}){flag}")

    with open(OUT, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\nwrote {OUT} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
