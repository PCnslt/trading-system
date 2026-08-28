#!/usr/bin/env python3
"""Pre-holiday drift backtest (Ariel 1990 JF; Lakonishok & Smidt 1988 RFS).

Signal: LONG SPY/QQQ/DIA at the CLOSE of the trading day BEFORE the pre-holiday
session, EXIT at the CLOSE of the pre-holiday (last) trading day -> harvests the
pre-holiday day's return (1-day hold, ~9-10 US market holidays/yr, ~10 round
trips/yr). Also tests the post-holiday (reopen) day, which the literature says
is typically NEGATIVE (the contra/avoid leg).

This supersedes the old research/preholiday_backtest.py (which used the imprecise
pandas USFederalHolidayCalendar via IBKR and only measured gross excess return).
Here we use a precise hand-built NYSE market-holiday calendar (observed closure
dates, Good Friday via Computus, Juneteenth since 2022, MLK since 1998) and the
repo's honest-fill / IS-OOS / cost-stress convention.

Data: yf/etfs/{SPY,QQQ,DIA}.json daily bars from the S3 datalake
(trading-datalake-920641308584). SPY 1993-2026, QQQ 1999-2026, DIA 1998-2026.

Cost model: equities round-trip bps deducted from every trade (baseline 5 bps,
stress 10/15/20 = 2x/3x/4x). PF = grossWins/grossLosses on NET returns.
IS/OOS = BOTH the repo 60/40 chronological split AND the literature-aligned
pre-2000 / 2000-2026 split (Hansen & Lunde 2005: calendar effects diminished
post-late-1980s except small caps).

Special closures (9/11, presidential funerals, Hurricane Sandy) are EXCLUDED:
they are not predictable in advance and would contaminate a calendar-tradeable
pre-holiday signal.

VERDICT LOGIC: promote only if OOS PF >= 1.3 survives 2x cost (10 bps).
"""
import json
import datetime as dt
from datetime import date, timedelta

import numpy as np
import pandas as pd
import boto3

BUCKET = "trading-datalake-920641308584"
SYMS = ["SPY", "QQQ", "DIA"]
COST_BPS = [5.0, 10.0, 15.0, 20.0]
IS_CUT = 0.60  # repo 60/40 chronological split by entry date
POST2000 = pd.Timestamp("2000-01-01")


# ----------------------------------------------------------------------------
# NYSE market-holiday calendar (observed closure dates)
# ----------------------------------------------------------------------------
def easter_sunday(year):
    """Anonymous Gregorian (Meeus/Jones/Butcher) algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def nth_weekday(year, month, weekday, n):
    """nth occurrence of `weekday` (Mon=0..Sun=6) in a month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def last_weekday(year, month, weekday):
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def observed(year, month, day):
    """NYSE fixed-date rule: Sat -> prior Fri, Sun -> following Mon."""
    d = date(year, month, day)
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def nyse_holidays(start_year, end_year):
    """Return (set of observed closure dates, dict date->holiday name)."""
    days = {}
    for y in range(start_year, end_year + 1):
        days[observed(y, 1, 1)] = "New Year"        # New Year's Day
        if y >= 1998:
            days[nth_weekday(y, 1, 0, 3)] = "MLK"   # 3rd Mon Jan (NYSE since 1998)
        days[nth_weekday(y, 2, 0, 3)] = "Presidents"  # 3rd Mon Feb
        days[easter_sunday(y) - timedelta(days=2)] = "Good Friday"
        days[last_weekday(y, 5, 0)] = "Memorial"    # last Mon May
        if y >= 2022:
            days[observed(y, 6, 19)] = "Juneteenth"  # since 2022
        days[observed(y, 7, 4)] = "Independence"
        days[nth_weekday(y, 9, 0, 1)] = "Labor"     # 1st Mon Sep
        days[nth_weekday(y, 11, 3, 4)] = "Thanksgiving"  # 4th Thu Nov
        days[observed(y, 12, 25)] = "Christmas"
    return set(days.keys()), days


# ----------------------------------------------------------------------------
# Data + trade construction
# ----------------------------------------------------------------------------
def load_etf(sym):
    s3 = boto3.client("s3", region_name="us-east-1")
    o = s3.get_object(Bucket=BUCKET, Key=f"yf/etfs/{sym}.json")
    d = json.loads(o["Body"].read().decode())
    df = pd.DataFrame(d["daily"])
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df[df["close"] > 0]


def mark_preholiday(df, holiday_dates):
    """A session is 'pre-holiday' if the NEXT calendar day is an observed NYSE
    closure (holiday). Return a boolean Series aligned to df.index."""
    dates = df.index
    next_day_is_hol = [d.date() + timedelta(days=1) in holiday_dates for d in dates]
    return pd.Series(next_day_is_hol, index=df.index)


def build_preholiday_trades(df, prehol, names, cost_bps):
    """Entry = close of the trading day BEFORE the pre-holiday session;
    exit = close of the pre-holiday session. Net of round-trip cost."""
    dates = df.index
    closes = df["close"].to_numpy()
    trades = []
    idx = np.where(prehol.to_numpy())[0]
    for i in idx:
        if i == 0:
            continue
        entry_px = closes[i - 1]
        exit_px = closes[i]
        ret = exit_px / entry_px - 1.0
        net = ret - cost_bps / 10000.0
        hol_name = names.get(dates[i].date() + timedelta(days=1), "?")
        trades.append({
            "entry_date": dates[i - 1], "exit_date": dates[i],
            "holiday": hol_name, "ret": ret, "net": net,
        })
    return trades


def build_postholiday_trades(df, prehol, names, cost_bps):
    """Contra/avoid leg: entry = close of pre-holiday session, exit = close of
    the reopen (post-holiday) session. Long-only (to measure the negative drift)."""
    dates = df.index
    closes = df["close"].to_numpy()
    trades = []
    idx = np.where(prehol.to_numpy())[0]
    for i in idx:
        if i + 1 >= len(df):
            continue
        entry_px = closes[i]
        exit_px = closes[i + 1]
        ret = exit_px / entry_px - 1.0
        net = ret - cost_bps / 10000.0
        hol_name = names.get(dates[i].date() + timedelta(days=1), "?")
        trades.append({
            "entry_date": dates[i], "exit_date": dates[i + 1],
            "holiday": hol_name, "ret": ret, "net": net,
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
    d = pd.DataFrame(trades).sort_values("exit_date").reset_index(drop=True)
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


def drift_benchmark(df):
    c = df["close"].to_numpy()
    r = c[1:] / c[:-1] - 1.0
    return {"mean_bps": float(r.mean() * 10000), "std_bps": float(r.std() * 10000),
            "win": float((r > 0).mean()), "n": int(len(r))}


def main():
    holiday_dates, names = nyse_holidays(1992, 2026)
    print("=" * 100)
    print(f"NYSE market holidays constructed: {len(holiday_dates)} observed closure dates "
          f"(1992-2026, predictable scheduled holidays only; special closures excluded)")
    print("=" * 100)

    all_rows = []
    per_hol = []
    post_rows = []
    drift_rows = []
    for sym in SYMS:
        df = load_etf(sym)
        prehol = mark_preholiday(df, holiday_dates)
        drift_rows.append({"sym": sym, **drift_benchmark(df)})
        print(f"\n### {sym}  ({df.index[0].date()} .. {df.index[-1].date()}, {len(df)} bars, "
              f"{int(prehol.sum())} pre-holiday sessions)")
        print(f"  UNCONDITIONAL 1d drift: mean {drift_rows[-1]['mean_bps']:+.2f}bp  "
              f"win {drift_rows[-1]['win']*100:.1f}%  (n={drift_rows[-1]['n']})")

        # pre-holiday strategy at each cost
        for cost in COST_BPS:
            tr = build_preholiday_trades(df, prehol, names, cost)
            m = summarize(tr)
            if m:
                all_rows.append({"sym": sym, "leg": "pre_holiday", "cost_bps": cost, **m})

        # post-holiday contra leg
        for cost in [COST_BPS[0], COST_BPS[1]]:
            tr = build_postholiday_trades(df, prehol, names, cost)
            m = summarize(tr)
            if m:
                post_rows.append({"sym": sym, "leg": "post_holiday", "cost_bps": cost, **m})

        # per-holiday breakdown (gross + net @5bps)
        tr5 = pd.DataFrame(build_preholiday_trades(df, prehol, names, 5.0))
        if len(tr5):
            g = tr5.groupby("holiday").agg(
                n=("net", "size"),
                gross_bps=("ret", lambda x: x.mean() * 10000),
                net_bps=("net", lambda x: x.mean() * 10000),
                win=("net", lambda x: (x > 0).mean()),
            ).reset_index().sort_values("n", ascending=False)
            g["sym"] = sym
            per_hol.append(g)

    R = pd.DataFrame(all_rows)
    P = pd.DataFrame(post_rows)
    print("\n" + "=" * 100)
    print("PRE-HOLIDAY STRATEGY (long close[H-1] -> close[H], net of round-trip cost)")
    cols = ["sym", "cost_bps", "n", "win_rate", "gross_bps", "avg_bps", "t", "pf",
            "is_pf", "oos_pf", "n_is", "n_oos", "pre2000_pf", "post2000_pf",
            "n_pre2000", "n_post2000"]
    print(R[cols].round(3).to_string(index=False))

    print("\n" + "=" * 100)
    print("POST-HOLIDAY CONTRA LEG (long close[H] -> close[reopen], net)")
    print(P[cols].round(3).to_string(index=False))

    print("\n" + "=" * 100)
    print("PER-HOLIDAY BREAKDOWN @5bps (gross / net bp, win rate)")
    if per_hol:
        print(pd.concat(per_hol).round(2).to_string(index=False))

    out = {
        "meta": {
            "idea": "Pre-holiday drift (Ariel 1990; Lakonishok-Smidt 1988)",
            "universe": "SPY/QQQ/DIA daily, S3 datalake",
            "cost_bps": "round-trip, 5/10/15/20",
            "is_oos": "60/40 chronological + pre-2000/2000+ split",
            "holidays": "NYSE scheduled, observed closure dates, special closures excluded",
            "note": "PF on net returns; promote only if OOS PF >= 1.3 at 10bps",
        },
        "drift_benchmark": drift_rows,
        "pre_holiday": all_rows,
        "post_holiday": post_rows,
        "per_holiday": [g.to_dict("records") for g in per_hol],
    }
    with open("/home/ubuntu/trading-system/research/preholiday_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nwrote research/preholiday_results.json")


if __name__ == "__main__":
    main()
