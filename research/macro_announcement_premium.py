#!/usr/bin/env python3
"""Macroeconomic announcement-day premium backtest (Savor & Wilson 2013, JFQA).

Signal: LONG SPY/QQQ at the CLOSE of the trading day BEFORE a scheduled macro
release and EXIT at the CLOSE of the announcement day (1-day hold). The
announcement-day return is close-to-close, which is the standard replication of
the "on-day risk premium" (Savor-Wilson: avg excess daily return 11.4 bp on
announcement days vs ~1 bp otherwise, 1958-2009).

Announcement calendar (three BLS releases + FOMC):
  - CPI   (Consumer Price Index)      — ALFRED release rid=10
  - PPI   (Producer Price Index)      — ALFRED release rid=46
  - EMP   (Employment Situation/NFP)  — ALFRED release rid=50
  - FOMC  (FOMC statement day)        — federalreserve.gov (research/fomc_calendar.json)
ALFRED release dates downloaded keyless from
alfred.stlouisfed.org/release/downloaddates?rid=<n>&ff=txt on 2026-08-27 and
parsed into research/macro_release_dates.json.

Tests:
  1. Pooled macro (CPI+PPI+EMP+FOMC, deduped by date), long-only, net of cost.
  2. Split FOMC vs non-FOMC (CPI+PPI+EMP) — is this a DISTINCT premium from the
     pre-FOMC drift (Lane 52), or just the FOMC effect riding along?
  3. Announcement-day vs non-announcement-day 1-day return spread (the raw
     "risk premium" that the trade must beat).
  4. IS/OOS = 60/40 chronological split by entry date (repo convention) PLUS a
     literature-aligned split (IS <2016, OOS >=2016 — Kurov 2020 "disappearing
     drift").
  5. Cost stress: 5 / 10 / 15 / 20 bps round-trip.

Honest fills: equities round-trip bps deducted from every trade; PF on NET
returns. No lookahead: entry uses the close of the prior trading day, fully
known before the announcement. VERDICT LOGIC: promote only if OOS PF >= 1.3
survives 2x cost (10 bps).
"""
import json
import os

import numpy as np
import pandas as pd
import boto3

BUCKET = "trading-datalake-920641308584"
COST_BPS = [5.0, 10.0, 15.0, 20.0]
IS_CUT = 0.60  # repo convention: 60/40 chronological split by entry date

HERE = os.path.dirname(os.path.abspath(__file__))


def load_etf(sym):
    s3 = boto3.client("s3", region_name="us-east-1")
    o = s3.get_object(Bucket=BUCKET, Key=f"yf/etfs/{sym}.json")
    d = json.loads(o["Body"].read().decode())
    df = pd.DataFrame(d["daily"])
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df[df["close"] > 0]


def load_macro_calendar():
    """Returns dict of {type: [date strings]}. FOMC from research/fomc_calendar.json,
    CPI/PPI/EMP from research/macro_release_dates.json (ALFRED)."""
    rel = json.load(open(os.path.join(HERE, "macro_release_dates.json")))
    fomc = json.load(open(os.path.join(HERE, "fomc_calendar.json")))
    cal = {
        "cpi": rel["cpi"],
        "ppi": rel["ppi"],
        "employment": rel["employment"],
        "fomc": [r["announce_date"] for r in fomc],
    }
    return cal


def build_trades(df, dates, cost_bps):
    """Entry = close of prior trading day before announcement; exit = close of
    announcement day. Net of round-trip cost. Dates is a list of date strings."""
    idx = df.index
    closes = df["close"]
    dateset = set(pd.to_datetime(d) for d in dates)
    trades = []
    for ann in sorted(dateset):
        if ann not in idx:
            continue
        exit_i = idx.get_loc(ann)
        if exit_i == 0:
            continue
        entry_i = exit_i - 1
        entry = closes.iloc[entry_i]
        exit_px = closes.iloc[exit_i]
        ret = exit_px / entry - 1.0
        net = ret - cost_bps / 10000.0
        trades.append({
            "entry_date": idx[entry_i],
            "exit_date": ann,
            "ret": ret, "net": net,
        })
    return trades


def pf_of(rows):
    """PF on net returns. `rows` is a DataFrame with a 'net' column."""
    if len(rows) == 0:
        return float("nan")
    nets = rows["net"].astype(float)
    wins = nets[nets > 0].sum()
    losses = -nets[nets < 0].sum()
    return (wins / losses) if losses > 0 else float("inf")


def tstat(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2 or x.std() == 0:
        return float("nan")
    return float(x.mean() / (x.std() / np.sqrt(len(x))))


def summarize(trades, label):
    if not trades:
        return None
    d = pd.DataFrame(trades).sort_values("exit_date").reset_index(drop=True)
    n = len(d)
    win = (d["net"] > 0).mean()
    avg_bps = d["net"].mean() * 10000
    t = tstat(d["net"])
    pf = pf_of(d)
    cut = d["entry_date"].quantile(IS_CUT, interpolation="nearest")
    isd = d[d["entry_date"] <= cut]
    oosd = d[d["entry_date"] > cut]
    oos16 = d[d["entry_date"] >= "2016-01-01"]
    is16 = d[d["entry_date"] < "2016-01-01"]
    return {
        "label": label, "n": n, "win_rate": win, "avg_bps": avg_bps,
        "t": t, "pf": pf, "is_pf": pf_of(isd), "oos_pf": pf_of(oosd),
        "n_is": len(isd), "n_oos": len(oosd),
        "is16_pf": pf_of(is16), "oos16_pf": pf_of(oos16),
        "n_is16": len(is16), "n_oos16": len(oos16),
    }


def drift_benchmark(df):
    c = df["close"].to_numpy()
    r = c[1:] / c[:-1] - 1.0
    return {"mean_bps": r.mean() * 10000, "std_bps": r.std() * 10000,
            "win": (r > 0).mean(), "n": len(r)}


def ann_vs_nonann(df, all_dates):
    """Announcement-day vs non-announcement-day 1-day close-to-close return."""
    idx = df.index
    closes = df["close"].to_numpy()
    dateset = set(pd.to_datetime(d) for d in all_dates)
    ann, non = [], []
    for i in range(1, len(idx)):
        day = idx[i]
        r = closes[i] / closes[i - 1] - 1.0
        (ann if day in dateset else non).append(r)
    def s(x):
        x = np.asarray(x)
        return {"n": len(x), "mean_bps": x.mean() * 10000, "win": (x > 0).mean(),
                "t": tstat(x)}
    a, b = s(ann), s(non)
    # spread = difference in means with Welch t-test
    sa, sb = np.asarray(ann), np.asarray(non)
    va, vb = sa.var(ddof=1), sb.var(ddof=1)
    se = np.sqrt(va / len(sa) + vb / len(sb))
    t_diff = (sa.mean() - sb.mean()) / se if se > 0 else float("nan")
    return {"ann": a, "nonann": b,
            "spread_bps": (sa.mean() - sb.mean()) * 10000, "spread_t": t_diff}


def main():
    cal = load_macro_calendar()
    # pooled calendars (deduped by date)
    nonfomc = sorted(set(cal["cpi"] + cal["ppi"] + cal["employment"]))
    allm = sorted(set(nonfomc + cal["fomc"]))
    print("=" * 100)
    print("Macro announcement calendar:")
    for k, v in cal.items():
        print(f"  {k:12s} n={len(v):5d}")
    print(f"  non-FOMC (CPI+PPI+EMP, dedup) n={len(nonfomc)}")
    print(f"  ALL macro (dedup)             n={len(allm)}")
    print("=" * 100)

    all_rows = []
    for sym in ["SPY", "QQQ"]:
        df = load_etf(sym)
        bm = drift_benchmark(df)
        print(f"\n### {sym}  ({df.index[0].date()} .. {df.index[-1].date()}, {len(df)} bars)")
        print(f"  UNCONDITIONAL 1d drift: mean {bm['mean_bps']:+.2f}bp  win {bm['win']*100:.1f}%  (n={bm['n']})")

        # announcement vs non-announcement spread (gross)
        sp = ann_vs_nonann(df, allm)
        print(f"  ANN-day 1d ret: mean {sp['ann']['mean_bps']:+.2f}bp (n={sp['ann']['n']}, win {sp['ann']['win']*100:.1f}%)")
        print(f"  NON-ann  1d ret: mean {sp['nonann']['mean_bps']:+.2f}bp (n={sp['nonann']['n']}, win {sp['nonann']['win']*100:.1f}%)")
        print(f"  SPREAD (ann - nonann): {sp['spread_bps']:+.2f}bp  t={sp['spread_t']:.2f}")

        # tradeable lane tests
        for cost in COST_BPS:
            m = summarize(build_trades(df, allm, cost), f"{sym}@ALL")
            if m:
                all_rows.append({"sym": sym, "subset": "ALL", "cost_bps": cost, **m})
        # split FOMC vs non-FOMC at 5 and 10 bps
        for cost in [5.0, 10.0]:
            mf = summarize(build_trades(df, cal["fomc"], cost), f"{sym}@FOMC")
            mn = summarize(build_trades(df, nonfomc, cost), f"{sym}@nonFOMC")
            if mf:
                all_rows.append({"sym": sym, "subset": "FOMC", "cost_bps": cost, **mf})
            if mn:
                all_rows.append({"sym": sym, "subset": "nonFOMC", "cost_bps": cost, **mn})

    R = pd.DataFrame(all_rows)
    cols = ["sym", "subset", "cost_bps", "n", "win_rate", "avg_bps", "t", "pf",
            "is_pf", "oos_pf", "n_is", "n_oos", "is16_pf", "oos16_pf"]
    print("\n" + "=" * 100)
    print("RESULTS (net of round-trip cost bps; PF on net returns)")
    print(R[cols].round(3).to_string(index=False))

    R.to_json(os.path.join(HERE, "macro_announcement_results.json"),
              orient="records", indent=2)
    print("\nwrote research/macro_announcement_results.json")


if __name__ == "__main__":
    main()
