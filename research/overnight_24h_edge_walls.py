#!/usr/bin/env python3
"""Stage 5: the decisive table — PF>=1.3 OOS cost wall WITH and WITHOUT the COVID
crash window, plus a look at the surviving fat tail in the gated small-cap panel.

Merges into research/overnight_24h_edge_results.json under "cost_walls".
Run: ./venv/bin/python -u research/overnight_24h_edge_walls.py
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
PX_LO, PX_HI, DV_MIN = 2.0, 50.0, 20.0
COVID = (pd.Timestamp("2020-02-20"), pd.Timestamp("2020-04-30"))


def pf_of(x):
    w = float(x[x > 0].sum()); l = float(-x[x < 0].sum())
    return w / l if l > 1e-12 else float("inf")


def wall(x, target=1.3):
    x = np.asarray(x, float)
    if x.size == 0 or pf_of(x) < target:
        return 0.0
    lo, hi = 0.0, 1000.0
    if pf_of(x - hi) >= target:
        return hi
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if pf_of(x - mid) >= target else (lo, mid)
    return round(lo, 2)


def main() -> None:
    cols = ["date", "sym", "univ", "close", "ov_bp", "prev_bp", "dv20_musd",
            "tick1_bp", "dow", "tde", "sig", "c2", "o2", "c5", "o5"]
    df = pd.concat([pd.read_parquet(os.path.join(FEAT_DIR, f), columns=cols)
                    for f in sorted(os.listdir(FEAT_DIR)) if f.endswith(".parquet")],
                   ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    sc = (df["univ"].to_numpy() & 1).astype(bool)
    lc = (df["univ"].to_numpy() & 2).astype(bool)
    g_sc = sc & (df["close"] >= PX_LO).to_numpy() & (df["close"] <= PX_HI).to_numpy() \
        & (df["dv20_musd"] >= DV_MIN).to_numpy()
    g_lc = lc & (df["dv20_musd"] >= DV_MIN).to_numpy()
    prev, dow, tde, sig = (df["prev_bp"].to_numpy(float), df["dow"].to_numpy(),
                           df["tde"].to_numpy(), df["sig"].to_numpy(bool))

    # fat-tail audit of the gated small-cap panel
    sub = df.loc[g_sc, ["sym", "date", "close", "ov_bp", "dv20_musd"]].dropna()
    worst = sub.reindex(sub["ov_bp"].abs().sort_values(ascending=False).index).head(6)
    tail = [{"sym": r.sym, "date": str(r.date.date()), "close": round(float(r.close), 2),
             "ov_bp": round(float(r.ov_bp), 0), "dv20_musd": round(float(r.dv20_musd), 1)}
            for r in worst.itertuples()]
    print("[tail] largest |overnight gap| rows surviving the price/ADV gate:")
    for t in tail:
        print(f"   {t['sym']:<6} {t['date']} close ${t['close']} gap {t['ov_bp']:+.0f}bp "
              f"dv20 ${t['dv20_musd']}M")

    variants = {
        "1a_uncond_smallcap_gated": g_sc,
        "1c_uncond_largecap": g_lc,
        "2a_signal_overnight_only_smallcap": g_sc & sig,
        "2b_signal_overnight_only_largecap": g_lc & sig,
        "3a_prevday_down_smallcap": g_sc & (prev < 0),
        "3c_smallcap_prevdown_10%toinf": g_sc & (prev < -1000.0),
        "3d_largecap_prevdown_10%toinf": g_lc & (prev < -1000.0),
        "4a_dow_Mon_smallcap": g_sc & (dow == 0),
        "4b_dow_Mon_largecap": g_lc & (dow == 0),
        "4c_monthend_last1_smallcap": g_sc & (tde == 0),
        "4d_monthend_last1_largecap": g_lc & (tde == 0),
        "5b_smallcap_prevdown3pct_mon_tue": g_sc & (prev < -300.0) & (dow <= 1),
        "5c_largecap_mon_prevdown": g_lc & (dow == 0) & (prev < 0),
    }
    oos_m = (df["date"] > pd.Timestamp("2019-12-31")).to_numpy()
    covid_m = ((df["date"] >= COVID[0]) & (df["date"] <= COVID[1])).to_numpy()
    ov = df["ov_bp"].to_numpy(float)

    rows = {}
    print(f"\n{'variant':<40} {'n_oos':>7} {'wall_bp':>8} {'wall_exCOVID':>13} "
          f"{'mean_oos':>9} {'mean_exC':>9} {'PF_exC':>7} {'tick1_med':>10}")
    for name, m in variants.items():
        o = m & oos_m & np.isfinite(ov)
        x = ov[o]
        xe = ov[o & ~covid_m]
        t1 = float(np.median(df["tick1_bp"].to_numpy(float)[o]))
        rows[name] = {
            "n_oos": int(x.size), "n_oos_excl_covid": int(xe.size),
            "wall_pf13_oos_bp": wall(x), "wall_pf13_oos_excl_covid_bp": wall(xe),
            "oos_mean_bp": round(float(x.mean()), 2),
            "oos_mean_excl_covid_bp": round(float(xe.mean()), 2),
            "oos_pf": round(pf_of(x), 3), "oos_pf_excl_covid": round(pf_of(xe), 3),
            "tick1_median_bp": round(t1, 2),
        }
        r = rows[name]
        print(f"{name:<40} {r['n_oos']:>7} {r['wall_pf13_oos_bp']:>8.2f} "
              f"{r['wall_pf13_oos_excl_covid_bp']:>13.2f} {r['oos_mean_bp']:>+9.2f} "
              f"{r['oos_mean_excl_covid_bp']:>+9.2f} {r['oos_pf_excl_covid']:>7.3f} {r['tick1_median_bp']:>10.2f}")

    # the entry-switch question: incremental value of evening vs next-open entry
    print("\n[entry switch] paired close-entry minus open-entry, OOS, signal days only:")
    inc = {}
    for uname, um in [("smallcap", g_sc & sig), ("largecap", g_lc & sig)]:
        for H in (2, 5):
            m = um & oos_m
            d = (df[f"c{H}"].to_numpy(float) - df[f"o{H}"].to_numpy(float))[m]
            d = d[np.isfinite(d)]
            de = (df[f"c{H}"].to_numpy(float) - df[f"o{H}"].to_numpy(float))[m & ~covid_m]
            de = de[np.isfinite(de)]
            inc[f"{uname}_H{H}"] = {
                "n_oos": int(d.size),
                "mean_bp": round(float(d.mean()), 2),
                "median_bp": round(float(np.median(d)), 2),
                "mean_excl_covid_bp": round(float(de.mean()), 2),
                "pct_positive": round(float((d > 0).mean()), 4),
                "t_stat": round(float(d.mean() / (d.std(ddof=1) / np.sqrt(d.size))), 2),
                "max_extra_buyside_cost_bp_before_switch_loses": round(float(d.mean()), 2),
            }
            i = inc[f"{uname}_H{H}"]
            print(f"   {uname}_H{H}: +{i['mean_bp']}bp mean (median +{i['median_bp']}, "
                  f"{100*i['pct_positive']:.0f}% pos, t={i['t_stat']}) -> switching the entry to the "
                  f"evening session only pays if the extra BUY-side cost < {i['mean_bp']}bp")

    res = json.load(open(OUT_JSON))
    res["cost_walls"] = {
        "note": "wall = max flat round-trip cost in bp at which PF(gross-cost) >= 1.3 on OOS trades",
        "by_variant": rows,
        "gated_smallcap_fat_tail_rows": tail,
        "entry_switch_incremental_value": inc,
        "best_wall_bp": max(v["wall_pf13_oos_excl_covid_bp"] for v in rows.values()),
    }
    json.dump(res, open(OUT_JSON, "w"), indent=2, default=str)
    print(f"\nbest PF>=1.3 OOS wall across all variants (excl COVID): "
          f"{res['cost_walls']['best_wall_bp']}bp")
    print(f"merged cost_walls into {OUT_JSON}")


if __name__ == "__main__":
    main()
