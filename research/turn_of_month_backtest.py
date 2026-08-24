#!/usr/bin/env python3
"""Turn-of-month (and calendar) short-horizon edge study on US index ETFs.

Hunt for a NEW short-horizon (1-3 day) edge that is NOT already ruled out in
docs/STRATEGY_PORTFOLIO.md. Calendar / turn-of-month seasonality is the one
documented short-horizon anomaly family with zero prior test in this repo.

Data: yf/etfs/{SPY,QQQ,DIA,IWM,VTI}.json daily bars (20-33y), pulled from the
S3 datalake (trading-datalake-920641308584) with EC2 instance-role creds.

Strategies (all close-to-close, honest fills):
  A) TOM_LONG      - long the turn-of-month window (last trading day of month M
                     + first 3 trading days of M+1). Enter close of the trading
                     day before the window, exit close of the last window day.
  B) TOM_LS        - market-neutral calendar spread: long the TOM window, short
                     a mid-month window (trading days 10-13). Strips the long-beta
                     drift so the anomaly itself is measured.
  C) DOW_EFX       - day-of-week: long Monday-close -> Friday-close ("sell the
                     weekend" complement) AND long Friday-close -> Monday-close.
                     Reported separately as EFX_MF (Mon->Fri) and EFX_FM (Fri->Mon).
  D) DRIFT_BENCH   - all overlapping 4-day close-to-close returns (the drift the
                     calendar effect must beat to be a real signal).

Cost model: round-trip bps deducted from every leg. Baseline 5 bps (equities),
stress at 10 / 15 / 20 bps (2x / 3x / 4x). IS/OOS = 60/40 chronological split by
entry date. PF = grossWins/grossLosses; maxDD chronological on cumulative net.
"""
import json
import io
import datetime as dt

import numpy as np
import pandas as pd
import boto3

BUCKET = "trading-datalake-920641308584"
ETFS = ["SPY", "QQQ", "DIA", "IWM", "VTI"]
COST_BPS = [5.0, 10.0, 15.0, 20.0]  # round-trip, per leg (L/S pays twice)


def load_etf(sym):
    s3 = boto3.client("s3")
    o = s3.get_object(Bucket=BUCKET, Key=f"yf/etfs/{sym}.json")
    d = json.loads(o["Body"].read().decode())
    daily = d["daily"]
    df = pd.DataFrame(daily)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[df["close"] > 0]
    return df


def trading_day_rank(dates):
    """Trading-day-of-month rank (1 = first trading day of the month)."""
    s = pd.Series(dates).to_frame("ts")
    s["ym"] = s["ts"].dt.to_period("M")
    return s.groupby("ym")["ts"].rank(method="first").astype(int)


def build_windows(df, n=4):
    """Return boolean masks: tom (turn-of-month window) and mid (mid-month window).

    tom  = last trading day of month M + first 3 trading days of M+1 (n days).
    mid  = trading days 10 .. 9+n of each month (same length window).
    Also returns the drift-benchmark 4-day overlapping returns.
    """
    dates = df.index
    rank = trading_day_rank(dates).to_numpy()
    # day-within-month: total trading days in each month
    ym = pd.Series(dates).dt.to_period("M").to_numpy()
    # last trading day of month: rank == max rank in that month
    maxrank = pd.Series(rank).groupby(pd.Series(ym)).transform("max").to_numpy()
    is_last = (rank == maxrank)

    tom = np.zeros(len(df), dtype=bool)
    mid = np.zeros(len(df), dtype=bool)
    for i in range(len(df)):
        # TOM: last day of month, or first 3 days of next month
        if is_last[i]:
            tom[i] = True
        elif rank[i] <= 3:
            tom[i] = True
        # mid-month: trading days 10..13
        if 10 <= rank[i] <= 13:
            mid[i] = True

    return tom, mid


def run_calendar_strategy(df, leg_mask, direction, hold=4, cost_bps=5.0):
    """Enter at close of the day BEFORE the first day of `leg_mask` window,
    exit at close `hold` trading days later. Returns list of trade dicts."""
    dates = list(df.index)
    closes = df["close"].to_numpy()
    idx = np.arange(len(df))
    pos = np.zeros(len(df), dtype=int)  # 0 flat, +1 long, -1 short
    mask = leg_mask.astype(int)

    # find window start indices: first day of each contiguous run of mask==1
    # that is preceded by a mask==0 day
    starts = []
    for i in range(1, len(df)):
        if mask[i] == 1 and mask[i - 1] == 0:
            starts.append(i)

    trades = []
    used_entry = set()
    for s in starts:
        entry_idx = s - 1  # close of the day before the window
        if entry_idx < 0 or entry_idx in used_entry:
            continue
        exit_idx = entry_idx + hold
        if exit_idx >= len(df):
            continue
        used_entry.add(entry_idx)
        ret = closes[exit_idx] / closes[entry_idx] - 1.0
        if direction < 0:
            ret = -ret
        net = ret - cost_bps / 10000.0
        trades.append({
            "entry_date": dates[entry_idx],
            "exit_date": dates[exit_idx],
            "direction": direction,
            "ret": ret,
            "net": net,
        })
    return trades


def metrics(trades, label):
    if not trades:
        return None
    df = pd.DataFrame(trades).sort_values("exit_date").reset_index(drop=True)
    wins = df[df["net"] > 0]["net"].sum()
    losses = -df[df["net"] < 0]["net"].sum()
    pf = (wins / losses) if losses > 0 else float("inf")
    win_rate = (df["net"] > 0).mean()
    n = len(df)
    # chronological maxDD on cumulative net return (bps)
    cum = df["net"].cumsum()
    peak = cum.cummax()
    dd = (cum - peak)
    maxdd = dd.min()
    avg_bps = df["net"].mean() * 10000
    # IS/OOS split by entry date (60/40)
    cut = df["entry_date"].quantile(0.60, interpolation="nearest")
    is_df = df[df["entry_date"] <= cut]
    oos_df = df[df["entry_date"] > cut]
    def pf_of(d):
        if len(d) == 0:
            return float("nan")
        w = d[d["net"] > 0]["net"].sum()
        l = -d[d["net"] < 0]["net"].sum()
        return (w / l) if l > 0 else float("inf")
    return {
        "label": label, "n": n, "win_rate": win_rate, "pf": pf,
        "is_pf": pf_of(is_df), "oos_pf": pf_of(oos_df),
        "n_is": len(is_df), "n_oos": len(oos_df),
        "avg_bps": avg_bps, "maxdd_bps": maxdd * 10000,
    }


def drift_benchmark(df, hold=4):
    """Distribution of all overlapping `hold`-day close-to-close returns (bps)."""
    c = df["close"].to_numpy()
    rets = c[hold:] / c[:-hold] - 1.0
    return {"mean_bps": rets.mean() * 10000, "std_bps": rets.std() * 10000,
            "win_rate": (rets > 0).mean(), "n": len(rets)}


def main():
    rows = []
    drift_rows = []
    for sym in ETFS:
        df = load_etf(sym)
        tom, mid = build_windows(df)
        drift_rows.append({"sym": sym, **drift_benchmark(df)})
        # A) TOM_LONG (hold 4 days = window length)
        for cost in COST_BPS:
            tr = run_calendar_strategy(df, tom, +1, hold=4, cost_bps=cost)
            m = metrics(tr, f"TOM_LONG")
            if m and cost == COST_BPS[0]:
                base = m.copy()
            if m:
                rows.append({"sym": sym, "strat": "TOM_LONG",
                             "cost_bps": cost, **m})
        # B) TOM_LS (long TOM, short mid-month) — cost on both legs
        for cost in COST_BPS:
            lt = run_calendar_strategy(df, tom, +1, hold=4, cost_bps=cost)
            st = run_calendar_strategy(df, mid, -1, hold=4, cost_bps=cost)
            # pair by entry date (approx: use same hold, both 4d)
            lt = pd.DataFrame(lt).sort_values("entry_date").reset_index(drop=True)
            st = pd.DataFrame(st).sort_values("entry_date").reset_index(drop=True)
            # merge on entry month
            lt["ym"] = lt["entry_date"].dt.to_period("M")
            st["ym"] = st["entry_date"].dt.to_period("M")
            m = lt.merge(st, on="ym", suffixes=("_l", "_s"))
            if len(m):
                m["net"] = m["net_l"] + m["net_s"]
                m["ret"] = m["ret_l"] + m["ret_s"]
                m["entry_date"] = m["entry_date_l"]
                m["exit_date"] = m["exit_date_l"]
                mm = metrics(m.to_dict("records"), "TOM_LS")
                if mm:
                    rows.append({"sym": sym, "strat": "TOM_LS",
                                 "cost_bps": cost, **mm})
        # C) day-of-week: Monday->Friday (long) and Friday->Monday (long)
        dow = df.index.dayofweek  # Mon=0 .. Fri=4
        def dow_trades(direction_label, entry_dow, exit_shift):
            out = []
            for i in range(len(df)):
                if dow[i] != entry_dow:
                    continue
                j = i + exit_shift
                if j >= len(df):
                    continue
                ret = df["close"].iloc[j] / df["close"].iloc[i] - 1.0
                out.append({"entry_date": df.index[i], "exit_date": df.index[j],
                            "direction": +1, "ret": ret,
                            "net": ret - COST_BPS[0] / 10000.0})
            return out
        # Mon close -> Fri close (4 days later)
        tr = dow_trades("EFX_MF", 0, 4)
        mm = metrics(tr, "EFX_MF")
        if mm:
            rows.append({"sym": sym, "strat": "EFX_MF", "cost_bps": COST_BPS[0], **mm})
        # Fri close -> Mon close (next Mon, 3 days later)
        tr = dow_trades("EFX_FM", 4, 3)
        mm = metrics(tr, "EFX_FM")
        if mm:
            rows.append({"sym": sym, "strat": "EFX_FM", "cost_bps": COST_BPS[0], **mm})

    R = pd.DataFrame(rows)
    print("=" * 100)
    print("DRIFT BENCHMARK (all overlapping 4-day close-to-close returns, bps)")
    print(pd.DataFrame(drift_rows).round(1).to_string(index=False))
    print()
    print("=" * 100)
    print("STRATEGY RESULTS (net of round-trip cost; L/S pays cost on both legs)")
    cols = ["sym", "strat", "cost_bps", "n", "win_rate", "pf", "is_pf", "oos_pf",
            "n_is", "n_oos", "avg_bps", "maxdd_bps"]
    print(R[cols].round(3).to_string(index=False))

    # summary: TOM_LONG and TOM_LS at 5bps pooled across ETFs
    print()
    print("=" * 100)
    print("POOLED ACROSS ETFs @5bps (unweighted mean of per-ETF PF/win-rate)")
    for strat in ["TOM_LONG", "TOM_LS"]:
        sub = R[(R["strat"] == strat) & (R["cost_bps"] == COST_BPS[0])]
        if len(sub):
            print(f"  {strat}: n_total={sub['n'].sum()}  "
                  f"mean_PF={sub['pf'].mean():.3f}  mean_win={sub['win_rate'].mean():.3f}  "
                  f"mean_OOS_PF={sub['oos_pf'].mean():.3f}  "
                  f"min_OOS_PF={sub['oos_pf'].min():.3f}  "
                  f"mean_avg_bps={sub['avg_bps'].mean():.1f}")


if __name__ == "__main__":
    main()
