#!/usr/bin/env python3
"""Stage 4: robustness checks on the 24h overnight-hold study.

1. The ungated small-cap panel has a corrupt IS mean (+1810bp) -> locate the
   offending rows and confirm the PRICE/ADV-GATED panel is clean.
2. Year-by-year OOS consistency of every variant that had a non-zero PF>=1.3
   cost wall, plus the headline unconditional variants.
3. Event clustering: what share of the "prior day < -10%" trades sit in the
   COVID crash window (2020-02-20 .. 2020-04-30)?
Merges the output into research/overnight_24h_edge_results.json under
"robustness" (read-modify-write of that file only).

Run: ./venv/bin/python -u research/overnight_24h_edge_checks.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
FEAT_DIR = os.path.join(_ROOT, "research", ".overnight24_features")
OUT_JSON = os.path.join(_ROOT, "research", "overnight_24h_edge_results.json")
IS_END = np.datetime64("2019-12-31")
PX_LO, PX_HI, DV_MIN = 2.0, 50.0, 20.0


def pf_of(x):
    w = float(x[x > 0].sum()); l = float(-x[x < 0].sum())
    return round(w / l, 3) if l > 1e-12 else float("inf")


def main() -> None:
    cols = ["date", "sym", "univ", "close", "ov_bp", "prev_bp", "dv20_musd",
            "tick1_bp", "cs_bp", "dow", "tde", "sig"]
    frames = [pd.read_parquet(os.path.join(FEAT_DIR, f), columns=cols)
              for f in sorted(os.listdir(FEAT_DIR)) if f.endswith(".parquet")]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    out = {}

    sc = (df["univ"].to_numpy() & 1).astype(bool)
    lc = (df["univ"].to_numpy() & 2).astype(bool)
    gate_sc = sc & (df["close"] >= PX_LO).to_numpy() & (df["close"] <= PX_HI).to_numpy() \
        & (df["dv20_musd"] >= DV_MIN).to_numpy()
    gate_lc = lc & (df["dv20_musd"] >= DV_MIN).to_numpy()

    # ---- 1. outlier audit -------------------------------------------------
    ung = df[sc & (df["date"] <= IS_END)]
    top = ung.reindex(ung["ov_bp"].abs().sort_values(ascending=False).index).head(8)
    out["ungated_is_outliers"] = [
        {"sym": r.sym, "date": str(r.date.date()), "close": round(float(r.close), 4),
         "ov_bp": round(float(r.ov_bp), 1), "dv20_musd": None if not np.isfinite(r.dv20_musd)
         else round(float(r.dv20_musd), 1)}
        for r in top.itertuples()]
    g = df.loc[gate_sc, "ov_bp"].to_numpy(float)
    g = g[np.isfinite(g)]
    out["gated_smallcap_ov_bp_distribution"] = {
        "n": int(g.size), "mean": round(float(g.mean()), 2),
        "median": round(float(np.median(g)), 2),
        "std": round(float(g.std(ddof=1)), 1),
        "min": round(float(g.min()), 1), "max": round(float(g.max()), 1),
        "p1": round(float(np.percentile(g, 1)), 1), "p99": round(float(np.percentile(g, 99)), 1),
        "mean_winsor_1_99": round(float(np.clip(g, np.percentile(g, 1),
                                                np.percentile(g, 99)).mean()), 2),
        "skew": round(float(pd.Series(g).skew()), 2),
    }
    print("[1] ungated-IS worst |ov_bp| rows (the +1810bp artifact):")
    for r in out["ungated_is_outliers"]:
        print(f"    {r['sym']:<6} {r['date']} close ${r['close']} ov {r['ov_bp']:+.0f}bp "
              f"dv20 {r['dv20_musd']}M")
    d = out["gated_smallcap_ov_bp_distribution"]
    print(f"[1] GATED smallcap gap: n={d['n']:,} mean {d['mean']:+.2f} median {d['median']:+.2f} "
          f"std {d['std']} min {d['min']} max {d['max']} winsorised(1-99) mean "
          f"{d['mean_winsor_1_99']:+.2f} skew {d['skew']}")

    # ---- 2/3. per-variant year table + covid clustering -------------------
    prev = df["prev_bp"].to_numpy(float)
    dow = df["dow"].to_numpy()
    tde = df["tde"].to_numpy()
    sig = df["sig"].to_numpy(bool)
    variants = {
        "1a_uncond_smallcap_gated": gate_sc,
        "1c_uncond_largecap": gate_lc,
        "2a_signal_overnight_only_smallcap": gate_sc & sig,
        "2b_signal_overnight_only_largecap": gate_lc & sig,
        "3c_smallcap_prevdown_10%toinf": gate_sc & (prev < -1000.0),
        "3d_largecap_prevdown_10%toinf": gate_lc & (prev < -1000.0),
        "4b_dow_Mon_largecap": gate_lc & (dow == 0),
        "4c_monthend_last1_smallcap": gate_sc & (tde == 0),
        "5b_smallcap_prevdown3pct_mon_tue": gate_sc & (prev < -300.0) & (dow <= 1),
        "5c_largecap_mon_prevdown": gate_lc & (dow == 0) & (prev < 0),
    }
    covid_lo, covid_hi = pd.Timestamp("2020-02-20"), pd.Timestamp("2020-04-30")
    yearly, clustering = {}, {}
    print("\n[2] year-by-year mean bp (n) — OOS years only")
    for name, m in variants.items():
        sub = df.loc[m, ["date", "ov_bp"]].dropna()
        yr = sub["date"].dt.year
        tab = sub.groupby(yr)["ov_bp"].agg(["count", "mean", "median"])
        pf = sub.groupby(yr)["ov_bp"].apply(lambda x: pf_of(x.to_numpy(float)))
        yearly[name] = {int(y): {"n": int(tab.loc[y, "count"]),
                                 "mean_bp": round(float(tab.loc[y, "mean"]), 2),
                                 "median_bp": round(float(tab.loc[y, "median"]), 2),
                                 "pf": pf.loc[y] if np.isfinite(pf.loc[y]) else "inf"}
                        for y in tab.index}
        oos = sub[sub["date"] > pd.Timestamp("2019-12-31")]
        inc = oos[(oos["date"] >= covid_lo) & (oos["date"] <= covid_hi)]
        clustering[name] = {
            "n_oos": int(len(oos)),
            "n_oos_covid_feb_apr_2020": int(len(inc)),
            "pct_oos_in_covid": round(100.0 * len(inc) / max(len(oos), 1), 1),
            "oos_mean_bp": round(float(oos["ov_bp"].mean()), 2),
            "oos_mean_bp_excl_covid": round(float(oos.loc[
                ~((oos["date"] >= covid_lo) & (oos["date"] <= covid_hi)), "ov_bp"].mean()), 2),
            "oos_pf_excl_covid": pf_of(oos.loc[
                ~((oos["date"] >= covid_lo) & (oos["date"] <= covid_hi)), "ov_bp"].to_numpy(float)),
            "n_distinct_oos_days": int(oos["date"].nunique()),
        }
        ys = " ".join(f"{y}:{yearly[name][y]['mean_bp']:+.0f}({yearly[name][y]['n']})"
                      for y in sorted(yearly[name]) if y >= 2020)
        c = clustering[name]
        print(f"  {name:<40} {ys}")
        print(f"  {'':<40} OOS {c['oos_mean_bp']:+.2f}bp -> excl COVID {c['oos_mean_bp_excl_covid']:+.2f}bp "
              f"PF {c['oos_pf_excl_covid']} ({c['pct_oos_in_covid']}% of OOS trades in Feb-Apr 2020, "
              f"{c['n_distinct_oos_days']} distinct days)")

    res = json.load(open(OUT_JSON))
    res["robustness"] = {"outlier_audit": out, "yearly": yearly,
                         "event_clustering": clustering}
    json.dump(res, open(OUT_JSON, "w"), indent=2, default=str)
    print(f"\nmerged robustness into {OUT_JSON}")


if __name__ == "__main__":
    main()
