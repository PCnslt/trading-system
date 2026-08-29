#!/usr/bin/env python3
"""Day-of-week overnight seasonality backtest (Lin 2025 AEF; Kallinterakis et al. 2023).

Signal: LONG SPY/QQQ/DIA at the CLOSE of a given weekday, EXIT at the NEXT trading
day's OPEN (a close->next-open overnight hold). Tests the paper's claim that the
Monday->Tuesday overnight is positive while the Friday->Monday (weekend) overnight is
negative, plus a '3-night' Mon/Tue/Thu model and an 'every-night' benchmark.

This is an OVERNIGHT (close->next-open) strategy, NOT close->close. Both legs are
regular-hours (Mon close ~16:00, Tue open 09:30) so the honest-fill convention is the
repo RTH round-trip. We sweep cost 5/10/15/20 bps (5.9 bp = the measured RTH
mid-session round-trip floor from overnight_cost_floor.json; the 16:00 closing-print
half-spread was measured at 1.9 bp, so 5-6 bp round-trip is the realistic bar).

Data: yf/etfs/{SPY,QQQ,DIA}.json daily bars from the S3 datalake
(trading-datalake-920641308584). SPY 1993-2026, QQQ 1999-2026, DIA 1998-2026.

Cost model: round-trip bps deducted from every overnight leg. PF = grossWins /
grossLosses on NET returns. IS/OOS = BOTH the repo 60/40 chronological split by entry
date AND a pre-2000 / 2000-2026 split (calendar effects are documented to decay
post-publication, and the cross-citing Kallinterakis sample is 1993-2021).

VERDICT LOGIC: promote only if OOS PF >= 1.3 survives 2x cost (10 bps).
"""
import json

import numpy as np
import pandas as pd
import boto3

BUCKET = "trading-datalake-920641308584"
SYMS = ["SPY", "QQQ", "DIA"]
COST_BPS = [5.0, 10.0, 15.0, 20.0]
IS_CUT = 0.60  # repo 60/40 chronological split by entry date
POST2000 = pd.Timestamp("2000-01-01")

# dayofweek: Mon=0 .. Fri=4
NIGHTS = {
    "MON": [0],
    "TUE": [1],
    "WED": [2],
    "THU": [3],
    "FRI_WEEKEND": [4],
    "3NIGHT_MON_TUE_THU": [0, 1, 3],
    "ALL_NIGHTS": [0, 1, 2, 3, 4],
}


def load_etf(sym):
    s3 = boto3.client("s3", region_name="us-east-1")
    o = s3.get_object(Bucket=BUCKET, Key=f"yf/etfs/{sym}.json")
    d = json.loads(o["Body"].read().decode())
    df = pd.DataFrame(d["daily"])
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[df["close"] > 0]
    return df


def build_overnight_trades(df, dow_list, cost_bps):
    """Entry = close of a weekday in dow_list; exit = open of the NEXT trading day.
    Return list of trade dicts with net = ret - cost_bps/10000."""
    dates = df.index
    opens = df["open"].to_numpy()
    closes = df["close"].to_numpy()
    dow = dates.dayofweek.to_numpy()
    trades = []
    for i in range(len(df) - 1):
        if dow[i] not in dow_list:
            continue
        entry_px = closes[i]
        exit_px = opens[i + 1]
        ret = exit_px / entry_px - 1.0
        net = ret - cost_bps / 10000.0
        trades.append({
            "entry_date": dates[i], "exit_date": dates[i + 1],
            "ret": ret, "net": net,
        })
    return trades


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
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


def summarize(trades):
    if not trades:
        return None
    d = pd.DataFrame(trades).sort_values("entry_date").reset_index(drop=True)
    n = len(d)
    win = (d["net"] > 0).mean()
    avg_bps = d["net"].mean() * 10000
    gross_bps = d["ret"].mean() * 10000
    t = tstat(d["net"])
    pf = pf_of(d)
    # repo 60/40 split by entry date
    cut = d["entry_date"].quantile(IS_CUT, interpolation="nearest")
    isd = d[d["entry_date"] <= cut]
    oosd = d[d["entry_date"] > cut]
    # literature split: pre-2000 vs 2000+
    is00 = d[d["entry_date"] < POST2000]
    oos00 = d[d["entry_date"] >= POST2000]
    return {
        "n": n, "win_rate": round(float(win), 4), "gross_bps": round(gross_bps, 2),
        "avg_bps": round(avg_bps, 2), "t": round(t, 3), "pf": round(pf, 3),
        "is_pf": round(pf_of(isd), 3), "oos_pf": round(pf_of(oosd), 3),
        "n_is": len(isd), "n_oos": len(oosd),
        "pre2000_pf": round(pf_of(is00), 3), "post2000_pf": round(pf_of(oos00), 3),
        "n_pre2000": len(is00), "n_post2000": len(oos00),
    }


def drift_benchmarks(df):
    """Unconditional overnight (close->next open) and 1d close->close drift."""
    c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    c2o = o[1:] / c[:-1] - 1.0          # overnight
    c2c = c[1:] / c[:-1] - 1.0          # 1-day close->close
    return {
        "overnight_mean_bps": float(c2o.mean() * 10000),
        "overnight_win": float((c2o > 0).mean()),
        "close_to_close_mean_bps": float(c2c.mean() * 10000),
        "close_to_close_win": float((c2c > 0).mean()),
    }


def main():
    print("=" * 100)
    print("DAY-OF-WEEK OVERNIGHT SEASONALITY (long close[weekday] -> next open, net RT cost)")
    print("Universe SPY/QQQ/DIA daily bars from S3 datalake; cost swept 5/10/15/20 bps RT")
    print("IS/OOS = 60/40 chronological + pre-2000/2000+ split; PF on net returns")
    print("=" * 100)

    all_rows = []
    drift_rows = []
    for sym in SYMS:
        df = load_etf(sym)
        drift_rows.append({"sym": sym, **drift_benchmarks(df)})
        print(f"\n### {sym}  ({df.index[0].date()} .. {df.index[-1].date()}, {len(df)} bars)")
        for night, dows in NIGHTS.items():
            for cost in COST_BPS:
                tr = build_overnight_trades(df, dows, cost)
                m = summarize(tr)
                if m:
                    all_rows.append({"sym": sym, "night": night, "cost_bps": cost, **m})

    R = pd.DataFrame(all_rows)
    cols = ["sym", "night", "cost_bps", "n", "win_rate", "gross_bps", "avg_bps", "t",
            "pf", "is_pf", "oos_pf", "n_is", "n_oos", "pre2000_pf", "post2000_pf",
            "n_pre2000", "n_post2000"]
    print("\n" + "=" * 100)
    print("ALL CONSTRUCTIONS (net of round-trip cost)")
    print(R[cols].round(3).to_string(index=False))

    print("\n" + "=" * 100)
    print("UNCONDITIONAL DRIFT BENCHMARKS (bp/trade, gross)")
    print(pd.DataFrame(drift_rows).round(2).to_string(index=False))

    # Focus: the paper's headline (Mon->Tue) and the 3-night model at each cost
    print("\n" + "=" * 100)
    print("HEADLINE: MON->TUE overnight vs FRI->MON weekend, per sym per cost")
    foc = R[R["night"].isin(["MON", "FRI_WEEKEND", "3NIGHT_MON_TUE_THU", "ALL_NIGHTS"])]
    fcols = ["sym", "night", "cost_bps", "n", "win_rate", "gross_bps", "avg_bps", "t",
             "pf", "oos_pf", "post2000_pf"]
    print(foc[fcols].round(3).to_string(index=False))

    # Pooled 3-night model across symbols (equal-weight by trade) at 5bp and 10bp
    print("\n" + "=" * 100)
    print("POOLED 3-NIGHT MODEL (Mon+Tue+Thu overnight, all symbols concatenated)")
    for cost in [5.0, 10.0]:
        pooled = []
        for sym in SYMS:
            df = load_etf(sym)
            pooled += build_overnight_trades(df, NIGHTS["3NIGHT_MON_TUE_THU"], cost)
        m = summarize(pooled)
        if m:
            print(f"  @{cost:.0f}bp: {m}")

    out = {
        "meta": {
            "idea": "Day-of-week overnight seasonality (Lin 2025 AEF; Kallinterakis 2023 IRAF)",
            "universe": "SPY/QQQ/DIA daily, S3 datalake, close->next-open",
            "cost_bps": "round-trip 5/10/15/20 (5.9bp = measured RTH floor)",
            "is_oos": "60/40 chronological + pre-2000/2000+ split",
            "note": "PF on net returns; promote only if OOS PF >= 1.3 at 10bps",
        },
        "drift_benchmarks": drift_rows,
        "constructions": all_rows,
    }
    with open("/home/ubuntu/trading-system/research/dow_overnight_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nwrote research/dow_overnight_results.json")


if __name__ == "__main__":
    main()
