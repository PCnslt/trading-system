#!/usr/bin/env python3
"""Stage 3: is a CLOSE-to-NEXT-OPEN overnight hold a tradeable edge for a ~$700
whole-share Robinhood account trading the 24-hour (Blue Ocean) session?

THE TRADE UNDER TEST: buy in the evening session at (approximately) close[t],
sell at/after the next regular open[t+1].  gross = 1e4*(open[t+1]/close[t]-1).

Builds on research/overnight_structure_backtest.py + research/moc_entry_validate.py
(raw gap +11.0bp mean / +9.5bp median on 189 large-caps; rejected because RH has
no MOC).  New question: does the 24h session's LIMIT-order access make it
implementable, and do real per-name spreads leave anything?

VARIANTS: unconditional (522 available of the 524-name sub-$50 universe vs 189
large-caps); conditional on the deployed dip signal (Wilder RSI(2)<5 &
close>SMA200) with a close-entry vs next-open-entry head-to-head; conditional on
prior-day down move and its size; day-of-week; month-end.

COST MODELS (all ROUND-TRIP bp, charged once per trade):
  cs     Corwin-Schultz (2012) high-low spread, per symbol-YEAR, negative 2-day
         estimates floored at 0 (standard practice).  REPORTED AS INSTRUCTED but
         it is a noise-inflated UPPER BOUND: it returns 51bp for AAPL in 2025,
         which is physically impossible (a 1-cent spread on a $232 stock is
         0.4bp).  See research/overnight_24h_cs_diag.py.
  ar     Abdi-Ranaldo (2017) close-high-low, per symbol-YEAR (averages before the
         sqrt so no flooring bias) -- still very noisy at 250-obs windows.
  tick1/2/3   k * 100/close bp = crossing a k-cent quoted spread.  tick1 is the
         PHYSICALLY BINDING FLOOR for any real fill; tick2/tick3 are realistic
         for the thin overnight session.
  flat   10 / 20 / 30 / 40 bp (required stress) + 60 / 100 bp (overnight session
         is thinner than RTH, so these are not academic).

Also reports a GAP-CAPTURE HAIRCUT: entering at 7-8pm ET does not get you
close[t]; if the evening session has already priced in fraction f of the gap you
only earn (1-f) of it.  Sensitivity at f = 0, 25%, 50%.

IS <= 2019-12-31, OOS >= 2020-01-01.
Run: ./venv/bin/python -u research/overnight_24h_edge.py
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
FLATS = [10.0, 20.0, 30.0, 40.0, 60.0, 100.0]
PF_TARGET = 1.3
PX_LO, PX_HI = 2.0, 50.0
DV_MIN = 20.0

RESULT: dict = {
    "study": "close-to-next-open overnight hold, Robinhood 24h market, ~$700 whole-share account",
    "trade": "buy at close[t] in the evening session, sell at open[t+1]; gross = 1e4*(open[t+1]/close[t]-1)",
    "is_split": {"is": "<= 2019-12-31", "oos": ">= 2020-01-01"},
    "pf_target_oos": PF_TARGET,
    "gates": {"price_band_usd": [PX_LO, PX_HI], "dv20_min_musd": DV_MIN,
              "note": "price/ADV gate applied at TRADE TIME so a $700 whole-share account could actually have taken the trade"},
    "cost_models": {
        "cs": "Corwin-Schultz 2012 high-low spread, per symbol-year, neg 2-day est floored at 0; NOISE-INFLATED UPPER BOUND",
        "ar": "Abdi-Ranaldo 2017 close-high-low, per symbol-year; unbiased aggregation but very noisy",
        "tick1": "100/close bp = cross a 1-cent spread; PHYSICAL FLOOR",
        "tick2": "200/close bp", "tick3": "300/close bp",
        "flat": "10/20/30/40/60/100 bp round trip",
    },
    "variants": [],
}


def pf_of(x: np.ndarray) -> float:
    if x.size == 0:
        return float("nan")
    w = float(x[x > 0].sum())
    l = float(-x[x < 0].sum())
    return w / l if l > 1e-12 else float("inf")


def jf(v: float):
    if v is None or not np.isfinite(v):
        return None if v is None or np.isnan(v) else "inf"
    return round(float(v), 3)


def block(gross: np.ndarray, cost) -> dict:
    net = gross - cost
    if net.size == 0:
        return {"n": 0}
    sd = float(net.std(ddof=1)) if net.size > 1 else float("nan")
    p = pf_of(net)
    return {
        "n": int(net.size),
        "mean_bp": round(float(net.mean()), 2),
        "median_bp": round(float(np.median(net)), 2),
        "win_rate": round(float((net > 0).mean()), 4),
        "pf": jf(p),
        "t_stat": round(float(net.mean() / (sd / np.sqrt(net.size))), 2)
        if sd and np.isfinite(sd) and sd > 0 else None,
    }


def cost_wall_pf(gross: np.ndarray, target: float = PF_TARGET) -> float:
    """Max flat round-trip cost (bp) at which PF(gross - cost) >= target."""
    if gross.size == 0:
        return float("nan")
    if pf_of(gross) < target:
        return 0.0
    lo, hi = 0.0, 1000.0
    if pf_of(gross - hi) >= target:
        return hi
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if pf_of(gross - mid) >= target:
            lo = mid
        else:
            hi = mid
    return round(lo, 2)


def variant(name: str, gross: np.ndarray, dates: np.ndarray, costs: dict,
            note: str = "", quiet: bool = False) -> dict:
    m = np.isfinite(gross)
    for v in costs.values():
        m &= np.isfinite(v)
    gross, dates = gross[m], dates[m]
    costs = {k: v[m] for k, v in costs.items()}
    ism = dates <= IS_END
    oosm = ~ism
    row = {
        "name": name, "note": note, "n": int(gross.size),
        "n_is": int(ism.sum()), "n_oos": int(oosm.sum()),
        "cost_model_bp": {k: {"mean": round(float(v.mean()), 2),
                              "median": round(float(np.median(v)), 2)}
                          for k, v in costs.items()} if gross.size else {},
        "gross": {"is": block(gross[ism], 0.0), "oos": block(gross[oosm], 0.0)},
        "net": {},
        "cost_wall_pf13_oos_bp": cost_wall_pf(gross[oosm]),
        "cost_wall_pf13_is_bp": cost_wall_pf(gross[ism]),
        "mean_breakeven_cost_oos_bp": round(float(gross[oosm].mean()), 2) if oosm.any() else None,
        "mean_breakeven_cost_is_bp": round(float(gross[ism].mean()), 2) if ism.any() else None,
        "gap_capture_haircut_oos_mean_bp": {
            "f_0": round(float(gross[oosm].mean()), 2) if oosm.any() else None,
            "f_25pct": round(float(gross[oosm].mean() * 0.75), 2) if oosm.any() else None,
            "f_50pct": round(float(gross[oosm].mean() * 0.50), 2) if oosm.any() else None,
        },
    }
    for k, v in costs.items():
        row["net"][k] = {"is": block(gross[ism], v[ism]), "oos": block(gross[oosm], v[oosm])}
    for f in FLATS:
        row["net"][f"flat{int(f)}"] = {"is": block(gross[ism], f), "oos": block(gross[oosm], f)}
    RESULT["variants"].append(row)
    if not quiet:
        g_i, g_o = row["gross"]["is"], row["gross"]["oos"]
        t1 = row["net"]["tick1"]["oos"]
        print(f"  {name:<46} n={row['n']:>7} | IS mean {g_i.get('mean_bp'):>+7.2f} med "
              f"{g_i.get('median_bp'):>+6.2f} win {100*g_i.get('win_rate',0):>4.1f}% PF {str(g_i.get('pf')):>5} "
              f"| OOS mean {g_o.get('mean_bp'):>+7.2f} med {g_o.get('median_bp'):>+6.2f} "
              f"win {100*g_o.get('win_rate',0):>4.1f}% PF {str(g_o.get('pf')):>5} "
              f"| tick1({row['cost_model_bp']['tick1']['median']}bp) OOS {t1.get('mean_bp'):>+7.2f} PF {t1.get('pf')} "
              f"| WALL {row['cost_wall_pf13_oos_bp']}bp | BE {row['mean_breakeven_cost_oos_bp']}bp")
    return row


P1 = ["date", "univ", "close", "ov_bp", "prev_bp", "dv20_musd", "cs_bp", "ar_bp",
      "tick1_bp", "dow", "tde"]
P2 = ["date", "sym", "univ", "close", "dv20_musd", "cs_bp", "ar_bp", "tick1_bp",
      "sig", "ov_bp", "prev_bp", "c1", "c2", "c3", "c5", "o1", "o2", "o3", "o5"]


def load(cols, sig_only=False) -> pd.DataFrame:
    parts = sorted(f for f in os.listdir(FEAT_DIR) if f.endswith(".parquet"))
    frames = []
    for f in parts:
        d = pd.read_parquet(os.path.join(FEAT_DIR, f), columns=cols)
        if sig_only:
            d = d[d["sig"].astype(bool)]
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = df["date"].values.astype("datetime64[s]")
    return df


def main() -> None:
    print("[load] all symbol-days...", flush=True)
    df = load(P1)
    print(f"[load] {len(df):,} symbol-days, {str(df['date'].min())[:10]} .. {str(df['date'].max())[:10]}")

    sc = (df["univ"].to_numpy() & 1).astype(bool)
    lc = (df["univ"].to_numpy() & 2).astype(bool)
    px = df["close"].to_numpy(float)
    dv = df["dv20_musd"].to_numpy(float)
    ov = df["ov_bp"].to_numpy(float)
    prev = df["prev_bp"].to_numpy(float)
    dt = df["date"].to_numpy()
    dow = df["dow"].to_numpy()
    tde = df["tde"].to_numpy()
    t1 = df["tick1_bp"].to_numpy(float)
    COST = {"cs": df["cs_bp"].to_numpy(float), "ar": df["ar_bp"].to_numpy(float),
            "tick1": t1, "tick2": 2.0 * t1, "tick3": 3.0 * t1}

    gate_sc = sc & (px >= PX_LO) & (px <= PX_HI) & (dv >= DV_MIN)
    gate_lc = lc & (dv >= DV_MIN)
    print(f"[gates] smallcap tradeable symbol-days {gate_sc.sum():,}/{sc.sum():,}; "
          f"largecap {gate_lc.sum():,}/{lc.sum():,}")
    print(f"[cost ] gated smallcap median price ${np.median(px[gate_sc]):.2f} -> "
          f"1-tick round trip {np.median(t1[gate_sc]):.1f}bp; "
          f"largecap median price ${np.median(px[gate_lc]):.2f} -> {np.median(t1[gate_lc]):.1f}bp")
    RESULT["universe"] = {
        "smallcap_symbol_days_gated": int(gate_sc.sum()),
        "smallcap_symbol_days_all": int(sc.sum()),
        "largecap_symbol_days_gated": int(gate_lc.sum()),
        "smallcap_median_price_usd": round(float(np.median(px[gate_sc])), 2),
        "smallcap_median_tick1_bp": round(float(np.median(t1[gate_sc])), 2),
        "largecap_median_price_usd": round(float(np.median(px[gate_lc])), 2),
        "largecap_median_tick1_bp": round(float(np.median(t1[gate_lc])), 2),
    }

    def V(name, mask, note=""):
        return variant(name, ov[mask], dt[mask], {k: v[mask] for k, v in COST.items()}, note)

    print("\n=== (1) UNCONDITIONAL OVERNIGHT HOLD ===")
    V("1a_uncond_smallcap_gated", gate_sc,
      "sub-$50 universe, price $2-50 and 20d ADV>=$20M at trade time")
    V("1b_uncond_smallcap_ungated", sc, "same 522 names, no historical price/ADV gate")
    V("1c_uncond_largecap", gate_lc, "189 liquid large-caps (bot/live_equities.py STOCKS)")

    print("\n=== (3) CONDITIONAL ON PRIOR-DAY DOWN MOVE ===")
    V("3a_prevday_down_smallcap", gate_sc & (prev < 0), "prior-day close-to-close < 0")
    V("3b_prevday_down_largecap", gate_lc & (prev < 0), "prior-day close-to-close < 0")
    buckets = [(-100.0, 0.0), (-200.0, -100.0), (-300.0, -200.0),
               (-500.0, -300.0), (-1000.0, -500.0), (-1e9, -1000.0)]
    for tag, gate in [("3c_smallcap", gate_sc), ("3d_largecap", gate_lc)]:
        for lo, hi in buckets:
            lab = f"{-hi/100:.0f}%to{'inf' if lo < -1e8 else f'{-lo/100:.0f}%'}"
            V(f"{tag}_prevdown_{lab}", gate & (prev < hi) & (prev >= lo),
              f"prior-day move between {hi/100:+.0f}% and "
              f"{'-inf' if lo < -1e8 else f'{lo/100:+.0f}%'}")

    print("\n=== (4a/b) DAY-OF-WEEK OF THE ENTRY (close) DAY ===")
    names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    for d in range(5):
        V(f"4a_dow_{names[d]}_smallcap", gate_sc & (dow == d), f"buy at close on {names[d]}")
    for d in range(5):
        V(f"4b_dow_{names[d]}_largecap", gate_lc & (dow == d), f"buy at close on {names[d]}")

    print("\n=== (4c/d) MONTH-END / TURN OF MONTH ===")
    V("4c_monthend_last1_smallcap", gate_sc & (tde == 0), "buy on last trading day of month")
    V("4c_monthend_last2_smallcap", gate_sc & (tde <= 1), "buy in last 2 trading days")
    V("4c_monthend_last3_smallcap", gate_sc & (tde <= 2), "buy in last 3 trading days")
    V("4c_rest_of_month_smallcap", gate_sc & (tde > 2), "all other entry days")
    V("4d_monthend_last1_largecap", gate_lc & (tde == 0), "buy on last trading day of month")
    V("4d_monthend_last2_largecap", gate_lc & (tde <= 1), "buy in last 2 trading days")
    V("4d_rest_of_month_largecap", gate_lc & (tde > 1), "all other entry days")

    print("\n=== (5) IS-SELECTED COMBOS (overfit risk -- reported for completeness) ===")
    V("5a_smallcap_prevdown3pct_monthend2", gate_sc & (prev < -300.0) & (tde <= 1),
      "prior-day <-3% AND last 2 trading days of month")
    V("5b_smallcap_prevdown3pct_mon_tue", gate_sc & (prev < -300.0) & (dow <= 1),
      "prior-day <-3% AND entry Mon/Tue")
    V("5c_largecap_mon_prevdown", gate_lc & (dow == 0) & (prev < 0),
      "large-cap, Monday entry, prior-day down")

    print("\n=== (6) PORTFOLIO REALISM: <=3 whole-share positions/night ===")
    port = {}
    for label, mask in [("smallcap_gated_top3_prev_losers", gate_sc),
                        ("largecap_top3_prev_losers", gate_lc)]:
        sub = pd.DataFrame({"date": dt[mask], "ov": ov[mask], "prev": prev[mask],
                            "cs": COST["cs"][mask], "t1": COST["tick1"][mask]}).dropna()
        sub = sub[sub["prev"] < 0].sort_values(["date", "prev"])
        top = sub.groupby("date").head(3)
        daily = top.groupby("date").agg(ov=("ov", "mean"), cs=("cs", "mean"),
                                        t1=("t1", "mean"), k=("ov", "size"))
        d = daily.index.to_numpy()
        g = daily["ov"].to_numpy()
        ism = d <= IS_END
        port[label] = {
            "n_nights": int(len(daily)),
            "avg_positions_per_night": round(float(daily["k"].mean()), 2),
            "gross": {"is": block(g[ism], 0.0), "oos": block(g[~ism], 0.0)},
            "net_cs": {"is": block(g[ism], daily["cs"].to_numpy()[ism]),
                       "oos": block(g[~ism], daily["cs"].to_numpy()[~ism])},
            "net_tick1": {"is": block(g[ism], daily["t1"].to_numpy()[ism]),
                          "oos": block(g[~ism], daily["t1"].to_numpy()[~ism])},
            "net_flat": {f"flat{int(f)}": {"is": block(g[ism], f), "oos": block(g[~ism], f)}
                         for f in FLATS},
            "cost_wall_pf13_oos_bp": cost_wall_pf(g[~ism]),
            "mean_breakeven_cost_oos_bp": round(float(g[~ism].mean()), 2),
            "ann_gross_oos_pct": round(float(g[~ism].mean() * 252 / 100.0), 2),
        }
        b = port[label]
        print(f"  {label:<34} nights={b['n_nights']:>5} avgpos={b['avg_positions_per_night']} "
              f"| gross OOS {b['gross']['oos']['mean_bp']:+.2f}bp PF {b['gross']['oos']['pf']} "
              f"(~{b['ann_gross_oos_pct']:+.1f}%/yr) | tick1 net OOS "
              f"{b['net_tick1']['oos']['mean_bp']:+.2f}bp PF {b['net_tick1']['oos']['pf']} "
              f"| flat20 net OOS {b['net_flat']['flat20']['oos']['mean_bp']:+.2f}bp "
              f"PF {b['net_flat']['flat20']['oos']['pf']} | WALL {b['cost_wall_pf13_oos_bp']}bp")
    RESULT["portfolio_nightly_max3"] = port

    del df, ov, prev, dt, dow, tde, px, dv, sc, lc, gate_sc, gate_lc, COST, t1

    print("\n=== (2) CONDITIONAL ON THE DEPLOYED SIGNAL: RSI(2)<5 & close>SMA200 ===")
    sg = load(P2, sig_only=True)
    print(f"[signals] {len(sg):,} signal-days total")
    s_px = sg["close"].to_numpy(float)
    s_sc = ((sg["univ"].to_numpy() & 1).astype(bool) & (s_px >= PX_LO) & (s_px <= PX_HI)
            & (sg["dv20_musd"].to_numpy(float) >= DV_MIN))
    s_lc = (sg["univ"].to_numpy() & 2).astype(bool) & (sg["dv20_musd"].to_numpy(float) >= DV_MIN)
    sdt = sg["date"].to_numpy()
    st1 = sg["tick1_bp"].to_numpy(float)
    SCOST = {"cs": sg["cs_bp"].to_numpy(float), "ar": sg["ar_bp"].to_numpy(float),
             "tick1": st1, "tick2": 2 * st1, "tick3": 3 * st1}
    sov = sg["ov_bp"].to_numpy(float)
    print(f"[signals] gated smallcap {int(s_sc.sum())}, largecap {int(s_lc.sum())}")

    variant("2a_signal_overnight_only_smallcap", sov[s_sc], sdt[s_sc],
            {k: v[s_sc] for k, v in SCOST.items()},
            "RSI2<5 & close>SMA200: overnight leg only, close[t]->open[t+1]")
    variant("2b_signal_overnight_only_largecap", sov[s_lc], sdt[s_lc],
            {k: v[s_lc] for k, v in SCOST.items()},
            "RSI2<5 & close>SMA200: overnight leg only, close[t]->open[t+1]")

    print("\n  --- head-to-head: EVENING(close) entry vs NEXT-OPEN entry (deployed) ---")
    print(f"  {'variant':<16} {'n':>6} | {'CLOSE OOS gross':>15} {'PF':>5} | "
          f"{'OPEN OOS gross':>15} {'PF':>5} | {'C-O':>7} | CLOSE net tick1/flat20 PF")
    h2h = {}
    for uname, um in [("smallcap", s_sc), ("largecap", s_lc)]:
        for H in (1, 2, 3, 5):
            ce = sg[f"c{H}"].to_numpy(float)[um]
            oe = sg[f"o{H}"].to_numpy(float)[um]
            dd, cc, tt = sdt[um], SCOST["cs"][um], SCOST["tick1"][um]
            good = np.isfinite(ce) & np.isfinite(oe) & np.isfinite(cc) & np.isfinite(tt)
            ce, oe, dd, cc, tt = ce[good], oe[good], dd[good], cc[good], tt[good]
            ism = dd <= IS_END
            key = f"{uname}_H{H}"
            ent = {}
            for ename, r in [("close_entry", ce), ("open_entry", oe)]:
                ent[ename] = {
                    "gross": {"is": block(r[ism], 0.0), "oos": block(r[~ism], 0.0)},
                    "net_cs": {"is": block(r[ism], cc[ism]), "oos": block(r[~ism], cc[~ism])},
                    "net_tick1": {"is": block(r[ism], tt[ism]), "oos": block(r[~ism], tt[~ism])},
                    "net_flat": {f"flat{int(f)}": {"is": block(r[ism], f), "oos": block(r[~ism], f)}
                                 for f in FLATS},
                    "cost_wall_pf13_oos_bp": cost_wall_pf(r[~ism]),
                    "cost_wall_pf13_is_bp": cost_wall_pf(r[ism]),
                }
            d_co = ce - oe
            ent["n"] = int(ce.size)
            ent["paired_close_minus_open_bp"] = {
                "is_mean": round(float(d_co[ism].mean()), 2),
                "is_median": round(float(np.median(d_co[ism])), 2),
                "oos_mean": round(float(d_co[~ism].mean()), 2),
                "oos_median": round(float(np.median(d_co[~ism])), 2),
                "oos_pct_positive": round(float((d_co[~ism] > 0).mean()), 4),
                "oos_t_stat": round(float(d_co[~ism].mean() /
                                          (d_co[~ism].std(ddof=1) / np.sqrt(d_co[~ism].size))), 2),
            }
            h2h[key] = ent
            print(f"  {key:<16} {ent['n']:>6} | {ent['close_entry']['gross']['oos']['mean_bp']:>+14.2f}bp "
                  f"{str(ent['close_entry']['gross']['oos']['pf']):>5} | "
                  f"{ent['open_entry']['gross']['oos']['mean_bp']:>+14.2f}bp "
                  f"{str(ent['open_entry']['gross']['oos']['pf']):>5} | "
                  f"{ent['paired_close_minus_open_bp']['oos_mean']:>+6.2f}bp | "
                  f"tick1 {ent['close_entry']['net_tick1']['oos']['mean_bp']:+.1f}bp "
                  f"PF {ent['close_entry']['net_tick1']['oos']['pf']} / flat20 "
                  f"{ent['close_entry']['net_flat']['flat20']['oos']['mean_bp']:+.1f}bp "
                  f"PF {ent['close_entry']['net_flat']['flat20']['oos']['pf']} "
                  f"| wallC {ent['close_entry']['cost_wall_pf13_oos_bp']}bp "
                  f"wallO {ent['open_entry']['cost_wall_pf13_oos_bp']}bp")
    RESULT["signal_entry_head_to_head"] = h2h

    print("\n  --- signal x prior-day move size (overnight leg, gated smallcap) ---")
    sprev = sg["prev_bp"].to_numpy(float)
    for lo, hi in [(-1e9, -500.0), (-500.0, -300.0), (-300.0, -100.0), (-100.0, 0.0)]:
        m = s_sc & (sprev < hi) & (sprev >= lo)
        if m.sum() >= 100:
            lab = f"{-hi/100:.0f}%to{'inf' if lo < -1e8 else f'{-lo/100:.0f}%'}"
            variant(f"2c_signal_smallcap_prevdown_{lab}", sov[m], sdt[m],
                    {k: v[m] for k, v in SCOST.items()}, "signal AND prior-day move bucket")
    for lo, hi in [(-1e9, -300.0), (-300.0, 0.0)]:
        m = s_lc & (sprev < hi) & (sprev >= lo)
        if m.sum() >= 100:
            lab = f"{-hi/100:.0f}%to{'inf' if lo < -1e8 else f'{-lo/100:.0f}%'}"
            variant(f"2d_signal_largecap_prevdown_{lab}", sov[m], sdt[m],
                    {k: v[m] for k, v in SCOST.items()}, "signal AND prior-day move bucket")

    # ---------------- summary: which variants clear PF>=1.3 OOS at any cost ----
    survivors = [v for v in RESULT["variants"]
                 if isinstance(v["cost_wall_pf13_oos_bp"], (int, float))
                 and v["cost_wall_pf13_oos_bp"] > 0]
    survivors.sort(key=lambda v: -v["cost_wall_pf13_oos_bp"])
    RESULT["survivors_pf13_oos"] = [
        {"name": v["name"], "n_oos": v["n_oos"],
         "cost_wall_bp": v["cost_wall_pf13_oos_bp"],
         "tick1_median_bp": v["cost_model_bp"]["tick1"]["median"],
         "cs_median_bp": v["cost_model_bp"]["cs"]["median"],
         "oos_gross_mean_bp": v["gross"]["oos"]["mean_bp"],
         "is_gross_mean_bp": v["gross"]["is"]["mean_bp"],
         "is_pf": v["gross"]["is"]["pf"]}
        for v in survivors]
    print("\n" + "=" * 100)
    print("VARIANTS WITH A NON-ZERO PF>=1.3 OOS COST WALL (everything else fails at ZERO cost)")
    print("=" * 100)
    if not survivors:
        print("  NONE.")
    for s in RESULT["survivors_pf13_oos"]:
        print(f"  {s['name']:<46} wall {s['cost_wall_bp']:>7.2f}bp  vs tick1 "
              f"{s['tick1_median_bp']:>6.1f}bp / CS {s['cs_median_bp']:>6.1f}bp  "
              f"n_oos={s['n_oos']:>6}  IS mean {s['is_gross_mean_bp']:>+7.2f}bp PF {s['is_pf']}")

    json.dump(RESULT, open(OUT_JSON, "w"), indent=2, default=str)
    print(f"\nwrote {OUT_JSON}")


if __name__ == "__main__":
    main()
