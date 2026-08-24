#!/usr/bin/env python3
"""Intraday short-term reversal on single-name mega-cap equities (1-min bars).

The one intraday family with a documented premium is mean-reversion (fades).
All PRIOR intraday fade tests in this repo were on INDEX futures / ETFs
(VWAP 2s, OR-fade, CR-model, FADESHORT, gap-fade) — all NO-GO. This is the
genuinely-untested variant: intraday reversal on SINGLE liquid mega-cap stocks,
where the premium is idiosyncratic (liquidity provision), not index-level.

Signal: within a session, when a stock's return from its day OPEN falls to
<= -X%, buy (the intraday "dip"), exit at the 4pm close (EOD flatten) or on a
protective stop. One position per day. Honest fills: entry at NEXT bar open +
1-cent adverse slip, stop intraday (open<stop -> fill at open else stop), EOD
exit at last-bar close - slip. Cost = round-trip bps (5 baseline, stress 10).

Data: ibkr/equities/1min/<TICKER>/<YYYY-MM>.parquet, 16 liquid names,
2024-09 .. 2026-08 (2y), S3 datalake, EC2 instance-role creds.
"""
import io
import os
import datetime as dt

import numpy as np
import pandas as pd
import boto3

BUCKET = "trading-datalake-920641308584"
CACHE = "/tmp/eq1m_cache"
TICKERS = ["AAPL", "AMD", "AMZN", "AVGO", "GOOG", "GOOGL", "INTC",
           "META", "MSFT", "MU", "NBIS", "NVDA", "PLTR", "SNDK", "SPCX", "TSLA"]
SLIP = 0.01          # 1 cent per side adverse selection
COST_BPS = [5.0, 10.0, 15.0]  # round-trip
DROP_PCTS = [1.0, 1.5, 2.0]   # entry threshold (% below day open)
STOP_PCT = 2.0                # protective stop below entry (%)


def load_ticker(sym):
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, f"{sym}.pkl")
    if os.path.exists(cp):
        return pd.read_pickle(cp)
    s3 = boto3.client("s3")
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"ibkr/equities/1min/{sym}/")
    keys = [o["Key"] for o in r.get("Contents", []) if o["Key"].endswith(".parquet")]
    frames = []
    for k in keys:
        o = s3.get_object(Bucket=BUCKET, Key=k)
        frames.append(pd.read_parquet(io.BytesIO(o["Body"].read())))
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("America/New_York")
    df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    df["day"] = df["ts"].dt.date
    df = df[df["open"] > 0]
    df.to_pickle(cp)
    return df


def run_intraday_reversal(df, drop_pct, stop_pct, cost_bps):
    days = df.groupby("day")
    trades = []
    for day, g in days:
        g = g.reset_index(drop=True)
        n = len(g)
        if n < 100:            # skip truncated sessions
            continue
        open_ref = g["open"].iloc[0]
        in_trade = False
        for i in range(n - 1):
            if in_trade:
                break
            cum_ret = g["close"].iloc[i] / open_ref - 1.0
            if cum_ret <= -drop_pct / 100.0:
                # enter at next bar open + adverse slip
                entry_px = g["open"].iloc[i + 1] + SLIP
                stop_px = entry_px * (1.0 - stop_pct / 100.0)
                in_trade = True
                # scan forward to exit (stop-first, else EOD close)
                exit_px = None
                exit_reason = "eod"
                for j in range(i + 1, n):
                    bar_o = g["open"].iloc[j]
                    bar_l = g["low"].iloc[j]
                    if bar_l <= stop_px:
                        exit_px = bar_o if bar_o < stop_px else stop_px
                        exit_px = exit_px - SLIP
                        exit_reason = "stop"
                        break
                if exit_px is None:
                    exit_px = g["close"].iloc[n - 1] - SLIP
                ret = exit_px / entry_px - 1.0
                net = ret - cost_bps / 10000.0
                trades.append({
                    "entry_date": pd.Timestamp(day),
                    "direction": 1,
                    "ret": ret,
                    "net": net,
                    "reason": exit_reason,
                })
    return trades


def metrics(trades, label):
    if not trades:
        return None
    df = pd.DataFrame(trades).sort_values("entry_date").reset_index(drop=True)
    wins = df[df["net"] > 0]["net"].sum()
    losses = -df[df["net"] < 0]["net"].sum()
    pf = wins / losses if losses > 0 else float("inf")
    win_rate = (df["net"] > 0).mean()
    cum = df["net"].cumsum()
    maxdd = (cum - cum.cummax()).min()
    cut = df["entry_date"].quantile(0.60, interpolation="nearest")
    def pf_of(d):
        if len(d) == 0:
            return float("nan")
        w = d[d["net"] > 0]["net"].sum()
        l = -d[d["net"] < 0]["net"].sum()
        return w / l if l > 0 else float("inf")
    return {"label": label, "n": len(df), "win_rate": win_rate, "pf": pf,
            "is_pf": pf_of(df[df["entry_date"] <= cut]),
            "oos_pf": pf_of(df[df["entry_date"] > cut]),
            "avg_bps": df["net"].mean() * 10000,
            "maxdd_bps": maxdd * 10000,
            "stop_frac": (df["reason"] == "stop").mean()}


def main():
    all_trades = {d: [] for d in DROP_PCTS}
    for sym in TICKERS:
        df = load_ticker(sym)
        ndays = df["day"].nunique()
        print(f"{sym}: {len(df)} bars, {ndays} sessions, "
              f"{df['ts'].min().date()} .. {df['ts'].max().date()}", flush=True)
        for drop in DROP_PCTS:
            tr = run_intraday_reversal(df, drop, STOP_PCT, 5.0)
            for t in tr:
                t["sym"] = sym
                t["drop"] = drop
            all_trades[drop].extend(tr)

    print()
    print("=" * 110)
    for drop in DROP_PCTS:
        trades = all_trades[drop]
        # pooled across tickers, cost stress
        base = metrics(trades, f"drop{drop}%")
        print(f"--- Intraday reversal, entry <= -{drop}% from day-open, stop -{STOP_PCT}%, EOD exit ---")
        if base is None:
            print("  (no trades)")
            continue
        for cb in COST_BPS:
            adj = [{**t, "net": t["ret"] - cb / 10000.0} for t in trades]
            m = metrics(adj, "x")
            print(f"  @{cb:>4.0f}bps RT: n={m['n']:5d}  win={m['win_rate']:.3f}  "
                  f"PF={m['pf']:.3f}  IS_PF={m['is_pf']:.3f}  OOS_PF={m['oos_pf']:.3f}  "
                  f"avg={m['avg_bps']:6.2f}bps  maxDD={m['maxdd_bps']:8.0f}bps  "
                  f"stop_frac={m['stop_frac']:.2f}")
        # per-ticker OOS at 5bps
        print("   per-ticker @5bps (n, PF, OOS_PF):")
        for sym in TICKERS:
            sub = [t for t in trades if t["sym"] == sym]
            if not sub:
                continue
            m = metrics([{**t, "net": t["ret"] - 5.0 / 10000.0} for t in sub], sym)
            if m and m["n"] >= 30:
                print(f"     {sym:6s}: n={m['n']:4d}  PF={m['pf']:.2f}  "
                      f"OOS_PF={m['oos_pf']:.2f}  win={m['win_rate']:.2f}")
    print("=" * 110)


if __name__ == "__main__":
    main()
