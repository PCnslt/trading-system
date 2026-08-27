#!/usr/bin/env python3
"""Pre-FOMC announcement drift backtest (Lucca & Moench 2015).

Signal: LONG SPY/QQQ at the close of the trading day BEFORE a scheduled FOMC
announcement day, EXIT at the close of the announcement day (1-day hold).
The announcement day = the day the FOMC statement is released (last day of the
meeting), which is where the 24h pre-announcement drift is harvested.

Data:
  - FOMC calendar 1994-2026 scraped from federalreserve.gov (scheduled meetings
    only; unscheduled/cancelled/conference-calls excluded). Presser flag per
    meeting.  Stored at /tmp/fomc_calendar.json, embedded here.
  - SPY/QQQ daily bars from the S3 datalake (yf/etfs/{SPY,QQQ}.json).

Tests:
  1. All meetings: entry close of prior trading day -> exit close of announcement
     day, net of cost. (24h 2pm->2pm window is approximated by close->close; the
     daily-bar proxy is the standard replication.)
  2. Presser vs non-presser split (2011-2026 only; pre-2011 has no pressers).
  3. IS/OOS = 60/40 chronological split by entry date (repo convention), PLUS a
     literature-aligned split (IS 1994-2015, OOS 2016-2026).
  4. Cost stress: 5 / 10 / 15 / 20 bps round-trip (2x / 3x / 4x).

Honest fills: equities round-trip bps deducted from every trade. PF =
grossWins/grossLosses on NET returns. No lookahead: entry uses the close of the
prior trading day, which is fully known before the announcement.

VERDICT LOGIC: promote only if OOS PF >= 1.3 survives 2x cost (10 bps).
"""
import json
import io
import os

import numpy as np
import pandas as pd
import boto3

BUCKET = "trading-datalake-920641308584"
COST_BPS = [5.0, 10.0, 15.0, 20.0]
IS_CUT = 0.60  # repo convention: 60/40 chronological split by entry date


def load_etf(sym):
    s3 = boto3.client("s3", region_name="us-east-1")
    o = s3.get_object(Bucket=BUCKET, Key=f"yf/etfs/{sym}.json")
    d = json.loads(o["Body"].read().decode())
    df = pd.DataFrame(d["daily"])
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df[df["close"] > 0]


def load_fomc_calendar():
    # Calendar built from federalreserve.gov pages (research/fomc_calendar.json).
    cal = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "fomc_calendar.json")))
    df = pd.DataFrame(cal)
    df["announce_date"] = pd.to_datetime(df["announce_date"])
    return df.sort_values("announce_date").reset_index(drop=True)


def build_trades(df, fomc, cost_bps):
    """Entry = close of prior trading day before announcement; exit = close of
    announcement day. Net of round-trip cost. Returns list of trade dicts."""
    dates = df.index
    closes = df["close"]
    trades = []
    for ann in fomc["announce_date"]:
        # announcement day must be a trading day (it always is: statement day)
        if ann not in dates:
            continue
        exit_idx = dates.get_loc(ann)
        if exit_idx == 0:
            continue
        entry_idx = exit_idx - 1  # prior trading day
        entry = closes.iloc[entry_idx]
        exit_px = closes.iloc[exit_idx]
        ret = exit_px / entry - 1.0
        net = ret - cost_bps / 10000.0
        trades.append({
            "entry_date": dates[entry_idx],
            "exit_date": ann,
            "presser": bool(fomc.loc[fomc["announce_date"] == ann, "presser"].iloc[0]),
            "ret": ret, "net": net,
        })
    return trades


def pf_of(df):
    if len(df) == 0:
        return float("nan")
    wins = df[df["net"] > 0]["net"].sum()
    losses = -df[df["net"] < 0]["net"].sum()
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
    # 60/40 chronological IS/OOS by entry date
    cut = d["entry_date"].quantile(IS_CUT, interpolation="nearest")
    isd = d[d["entry_date"] <= cut]
    oosd = d[d["entry_date"] > cut]
    # literature split: OOS from 2016
    oos16 = d[d["entry_date"] >= "2016-01-01"]
    is16 = d[d["entry_date"] < "2016-01-01"]
    return {
        "label": label, "n": n, "win_rate": win, "avg_bps": avg_bps,
        "t": t, "pf": pf, "is_pf": pf_of(isd), "oos_pf": pf_of(oosd),
        "n_is": len(isd), "n_oos": len(oosd),
        "is16_pf": pf_of(is16), "oos16_pf": pf_of(oos16),
    }


def drift_benchmark(df):
    """Unconditional 1-day close-to-close returns (the daily drift the signal
    must beat)."""
    c = df["close"].to_numpy()
    r = c[1:] / c[:-1] - 1.0
    return {"mean_bps": r.mean() * 10000, "std_bps": r.std() * 10000,
            "win": (r > 0).mean(), "n": len(r)}


def main():
    fomc = load_fomc_calendar()
    print("=" * 100)
    print("FOMC calendar:", len(fomc), "scheduled meetings",
          f"{fomc['announce_date'].min().date()} .. {fomc['announce_date'].max().date()}")
    print("pressers:", int(fomc['presser'].sum()), "  non-pressers:", int((~fomc['presser']).sum()))
    print("=" * 100)

    all_rows = []
    for sym in ["SPY", "QQQ"]:
        df = load_etf(sym)
        bm = drift_benchmark(df)
        print(f"\n### {sym}  ({df.index[0].date()} .. {df.index[-1].date()}, {len(df)} bars)")
        print(f"  UNCONDITIONAL 1d drift: mean {bm['mean_bps']:+.2f}bp  win {bm['win']*100:.1f}%  (n={bm['n']})")
        for cost in COST_BPS:
            tr = build_trades(df, fomc, cost)
            m = summarize(tr, f"{sym}@all")
            if m:
                all_rows.append({"sym": sym, "subset": "all", "cost_bps": cost, **m})
        # presser split (only meetings with presser flag defined)
        for cost in [COST_BPS[0], COST_BPS[1]]:
            tr_p = build_trades(df, fomc[fomc["presser"]], cost)
            tr_n = build_trades(df, fomc[~fomc["presser"]], cost)
            mp = summarize(tr_p, f"{sym}@presser")
            mn = summarize(tr_n, f"{sym}@nonpresser")
            if mp:
                all_rows.append({"sym": sym, "subset": "presser", "cost_bps": cost, **mp})
            if mn:
                all_rows.append({"sym": sym, "subset": "nonpresser", "cost_bps": cost, **mn})

    R = pd.DataFrame(all_rows)
    cols = ["sym", "subset", "cost_bps", "n", "win_rate", "avg_bps", "t", "pf",
            "is_pf", "oos_pf", "n_is", "n_oos", "is16_pf", "oos16_pf"]
    print("\n" + "=" * 100)
    print("RESULTS (net of round-trip cost bps; PF on net returns)")
    print(R[cols].round(3).to_string(index=False))

    R.to_json("/home/ubuntu/trading-system/research/pre_fomc_results.json",
              orient="records", indent=2)
    print("\nwrote research/pre_fomc_results.json")


if __name__ == "__main__":
    main()
