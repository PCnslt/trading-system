#!/usr/bin/env python3
"""Sector-ETF overnight (close->open) TIME-SERIES momentum backtest
(queue strat-20260911-1).

Salotra, Katikireddy, Anumolu & Pinsky 2026, Risks 14(4):84 (MDPI,
DOI 10.3390/risks14040084) claim overnight-MOMENTUM Sharpe ~0.95 vs 0.61
buy-and-hold on liquid US sector ETFs, 1999-2025, with an explicit 1-2bp
cost analysis.

This is the TIME-SERIES variant: LONG the overnight leg (close -> next open)
of an ETF when its TRAILING overnight (close->open) return is positive
(momentum); the reversal variant goes long when trailing overnight is
negative. Also a cross-sectional rank top-N leg. Distinct from Lane 66
(cross-sectional SINGLE-STOCK overnight momentum, sub-$50) and Lane 49
(unconditional close->open = dead).

Universe: SPY + the 9 Select Sector SPDRs (XLB XLE XLF XLI XLK XLP XLU XLV
XLY), daily bars from the S3 datalake (yf/etfs/SPY.json, yf/sectors/*.json),
common sample 1998-12-22 .. 2026-09-11.

Honest fills: ETF round-trip cost swept 0 (gross) / 1 / 2 / 5 bps (1-2bp is
the paper's cost; 5bp = repo RTH floor as a stress). PF on NET returns.
IS/OOS = 60/40 chronological split by entry date + post-2000 split.

VERDICT LOGIC: promote only if OOS PF >= 1.3 survives 2x cost (2bp).
"""

import json
import os

import numpy as np
import pandas as pd
import boto3

BUCKET = "trading-datalake-920641308584"
SYMS = ["SPY", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
SECTOR_PREFIX = "yf/sectors"   # SPY lives under yf/etfs
COSTS = [0.0, 1.0, 2.0, 5.0]   # round-trip bps
LOOKBACKS = [1, 5, 10, 21]
TOP_N = [2, 3, 5]
IS_FRAC = 0.60
POST2000 = pd.Timestamp("2000-01-01")


def key_for(sym):
    return "yf/etfs/SPY.json" if sym == "SPY" else f"{SECTOR_PREFIX}/{sym}.json"


def load_etf(sym):
    s3 = boto3.client("s3", region_name="us-east-1")
    o = s3.get_object(Bucket=BUCKET, Key=key_for(sym))
    d = json.loads(o["Body"].read().decode())
    df = pd.DataFrame(d["daily"])
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[df["close"] > 0]
    return df


def overnight_series(df):
    """close->next-open overnight return aligned to the EXIT day (day t+1)."""
    o = df["open"]
    c = df["close"]
    on = o / c.shift(1) - 1.0   # overnight return for day t (open_t / close_{t-1})
    return on


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def pf_of(nets):
    nets = np.asarray(nets, dtype=float)
    nets = nets[~np.isnan(nets)]
    if len(nets) == 0:
        return float("nan")
    wins = nets[nets > 0].sum()
    losses = -nets[nets < 0].sum()
    return (wins / losses) if losses > 0 else float("inf")


def tstat(x):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 2 or x.std() == 0:
        return float("nan")
    return float(x.mean() / (x.std() / np.sqrt(len(x))))


def sharpe(daily_net):
    x = np.asarray(daily_net, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 2 or x.std() == 0:
        return float("nan")
    return float(x.mean() / x.std() * np.sqrt(252))


def summarize_net_bp(net_bp, dates):
    """net_bp: array of per-trade net bp; dates: aligned entry/exit dates."""
    net_bp = np.asarray(net_bp, dtype=float)
    dates = pd.Series(pd.to_datetime(dates))
    m = ~np.isnan(net_bp)
    net_bp = net_bp[m]
    dates = dates[m]
    if len(net_bp) == 0:
        return None
    n = len(net_bp)
    win = (net_bp > 0).mean()
    avg = net_bp.mean()
    t = tstat(net_bp)
    pf = pf_of(net_bp)
    cut = dates.quantile(IS_FRAC, interpolation="nearest")
    isd = net_bp[dates <= cut]
    oosd = net_bp[dates > cut]
    is00 = net_bp[dates < POST2000]
    oos00 = net_bp[dates >= POST2000]
    return {
        "n": n, "win": round(float(win), 4), "avg_bp": round(float(avg), 2),
        "t": round(t, 3), "pf": round(pf, 3),
        "is_pf": round(pf_of(isd), 3), "oos_pf": round(pf_of(oosd), 3),
        "n_is": int(len(isd)), "n_oos": int(len(oosd)),
        "pre2000_pf": round(pf_of(is00), 3), "post2000_pf": round(pf_of(oos00), 3),
    }


def main():
    print("=" * 104)
    print("SECTOR-ETF OVERNIGHT (close->next-open) TIME-SERIES MOMENTUM")
    print("Salotra et al. 2026 Risks 14(4):84 — overnight-mom Sharpe ~0.95 vs B&H 0.61")
    print("Universe SPY + 9 sector SPDRs, S3 daily bars; cost 0/1/2/5bp RT; PF on net")
    print("=" * 104)

    frames = {}
    for sym in SYMS:
        frames[sym] = load_etf(sym)
        print(f"  {sym:>4}: {frames[sym].index[0].date()} .. {frames[sym].index[-1].date()} "
              f"({len(frames[sym])} bars)")

    # Common sample: intersection of dates with a valid overnight (need close[t-1])
    common = None
    for sym in SYMS:
        on = overnight_series(frames[sym])
        valid = on.dropna().index
        common = valid if common is None else common.intersection(valid)
    common = common.sort_values()
    print(f"\n  common overnight sample: {len(common)} days "
          f"({common[0].date()} .. {common[-1].date()})")

    # Build a DataFrame of overnight returns: rows=dates, cols=ETFs
    ON = pd.DataFrame({sym: overnight_series(frames[sym]) for sym in SYMS}).loc[common]
    # trailing N-day mean overnight (signal), shifted so signal uses only PAST nights
    results = {}

    # ---------------------------------------------------------------- 1) time-series momentum / reversal (per-ETF)
    ts_rows = []
    for N in LOOKBACKS:
        for direction, sign in [("mom", ">0"), ("rev", "<0"), ("mom_ge", ">=0")]:
            for cost in COSTS:
                net_all, dates_all = [], []
                exposure = []
                for sym in SYMS:
                    on = ON[sym]
                    sig = on.rolling(N).mean().shift(1)   # trailing N nights BEFORE entry day
                    if sign == ">0":
                        long_m = sig > 0
                    elif sign == ">=0":
                        long_m = sig >= 0
                    else:
                        long_m = sig < 0
                    # entry at close[t-1], exit at open[t] = the overnight return on day t
                    sel = long_m & on.notna() & sig.notna()
                    trade_net = on[sel] * 10000 - cost
                    net_all.extend(trade_net.values)
                    dates_all.extend(sel[sel].index)
                    exposure.append(float(sel.mean()))
                m = summarize_net_bp(np.array(net_all), dates_all)
                if m:
                    m.update({"N": N, "direction": direction, "cost_bp": cost,
                              "long_exposure": round(float(np.mean(exposure)), 3)})
                    ts_rows.append(m)

    TS = pd.DataFrame(ts_rows)
    print("\n" + "=" * 104)
    print("1) TIME-SERIES per-ETF (pooled across 10 ETFs) — momentum(>0) / reversal(<0)")
    print(TS[["N", "direction", "cost_bp", "n", "win", "avg_bp", "t", "pf",
              "is_pf", "oos_pf", "post2000_pf", "long_exposure"]].round(3).to_string(index=False))
    results["time_series"] = ts_rows

    # ---------------------------------------------------------------- 2) portfolio daily series (paper's Sharpe framing)
    # Each day: basket = ETFs whose trailing-N overnight signal > 0 (equal weight).
    # Compare vs buy-and-hold-overnight (all 10 equal weight).
    port_rows = []
    for N in LOOKBACKS:
        sig = ON.rolling(N).mean().shift(1)
        for direction, mask_fn in [("mom", lambda s: s > 0), ("rev", lambda s: s < 0)]:
            m = mask_fn(sig)
            for cost in COSTS:
                # equal-weight mean overnight across the selected ETFs (0 if none selected)
                sel_on = ON.where(m)
                basket_ret = sel_on.mean(axis=1) * 10000 - cost
                valid = m.any(axis=1) & ON.notna().any(axis=1)
                daily = basket_ret[valid]
                m2 = summarize_net_bp(daily.values, daily.index)
                if m2:
                    m2.update({"N": N, "direction": direction, "cost_bp": cost,
                               "sharpe": round(sharpe(daily.values), 3),
                               "exposure": round(float(valid.mean()), 3)})
                    port_rows.append(m2)
    # buy-and-hold overnight baseline (always long all 10 equal weight)
    bh_rows = []
    for cost in COSTS:
        daily = ON.mean(axis=1) * 10000 - cost
        m = summarize_net_bp(daily.values, daily.index)
        m.update({"N": -1, "direction": "buyhold", "cost_bp": cost,
                  "sharpe": round(sharpe(daily.values), 3)})
        bh_rows.append(m)
    PORT = pd.DataFrame(port_rows)
    print("\n" + "=" * 104)
    print("2) PORTFOLIO daily series — momentum / reversal basket (equal weight)")
    print(PORT[["N", "direction", "cost_bp", "n", "win", "avg_bp", "t", "pf",
                "is_pf", "oos_pf", "sharpe", "exposure"]].round(3).to_string(index=False))
    print("\n   BUY-AND-HOLD overnight baseline (always long all 10, equal weight):")
    print(pd.DataFrame(bh_rows)[["direction", "cost_bp", "n", "win", "avg_bp", "t",
                                 "pf", "is_pf", "oos_pf", "sharpe"]].round(3).to_string(index=False))
    results["portfolio"] = port_rows
    results["buyhold_baseline"] = bh_rows

    # ---------------------------------------------------------------- 3) cross-sectional rank top-N
    rank_rows = []
    for N in LOOKBACKS:
        sig = ON.rolling(N).mean().shift(1)
        # rank each day across the 10 ETFs (descending trailing overnight)
        rnk = sig.rank(axis=1, ascending=False, method="first")
        for topn in TOP_N:
            for cost in COSTS:
                sel = rnk <= topn
                basket_ret = ON.where(sel).mean(axis=1) * 10000 - cost
                valid = sel.any(axis=1) & ON.notna().any(axis=1)
                daily = basket_ret[valid]
                m = summarize_net_bp(daily.values, daily.index)
                if m:
                    m.update({"N": N, "topn": topn, "cost_bp": cost,
                              "sharpe": round(sharpe(daily.values), 3)})
                    rank_rows.append(m)
    RANK = pd.DataFrame(rank_rows)
    print("\n" + "=" * 104)
    print("3) CROSS-SECTIONAL rank top-N by trailing overnight (equal weight, daily)")
    print(RANK[["N", "topn", "cost_bp", "n", "win", "avg_bp", "t", "pf",
                "is_pf", "oos_pf", "sharpe"]].round(3).to_string(index=False))
    results["rank_topn"] = rank_rows

    # ---------------------------------------------------------------- 4) raw overnight drift benchmarks
    bench = {}
    for sym in SYMS:
        on = ON[sym] * 10000
        bench[sym] = {"avg_bp": round(float(on.mean()), 2),
                      "win": round(float((on > 0).mean()), 4),
                      "t": round(tstat(on.values), 3)}
    print("\n" + "=" * 104)
    print("4) UNCONDITIONAL overnight drift per ETF (gross bp)")
    print(pd.DataFrame(bench).T.round(3).to_string())
    results["drift_benchmarks"] = bench

    out = {
        "meta": {
            "idea": "Sector-ETF overnight (close->open) TIME-SERIES momentum "
                    "(Salotra et al. 2026 Risks 14(4):84)",
            "universe": "SPY + XLB XLE XLF XLI XLK XLP XLU XLV XLY, S3 daily bars, "
                       "common sample 1998-12-22..2026-09-11",
            "cost_bps": "round-trip 0/1/2/5 (1-2bp = paper; 5bp = repo RTH floor stress)",
            "is_oos": "60/40 chronological + post-2000 split; PF on net returns",
            "note": "promote only if OOS PF >= 1.3 at 2x cost (2bp)",
        },
        "time_series": ts_rows,
        "portfolio": port_rows,
        "buyhold_baseline": bh_rows,
        "rank_topn": rank_rows,
        "drift_benchmarks": bench,
    }
    with open("/home/ubuntu/trading-system/research/sector_etf_overnight_momentum_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nwrote research/sector_etf_overnight_momentum_results.json")


if __name__ == "__main__":
    main()
