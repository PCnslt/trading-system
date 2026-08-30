#!/usr/bin/env python3
"""Options-expiration (OPEX) week drift — honest backtest.

Queue item strat-20260828-opex-week. Claims under test (Stoll & Whaley 1997,
Ni-Pearson-Poteshman 2005 "gamma pinning", QuantPedia "Options Expiration Effect"):

  (1) PRE-OPEX week: LONG SPY/QQQ at the close of the last trading day BEFORE the
      monthly-expiration (3rd-Friday) week, EXIT at the expiration-day close (5d
      swing), or at the day-before-expiration close (4d).
  (2) POST-OPEX week: the week AFTER expiration (dealer-gamma unwind) as a
      separate contra/avoid leg.

~12 round-trips/yr, daily bars.  Monthly equity/index options expire on the 3rd
Friday of each month (the standard "OPEX"); if that Friday is a market holiday
(e.g. Good Friday), expiration shifts to the prior trading day (Thursday).

Honest fills (repo equities pattern): round-trip bps deducted from every trade,
PF on net returns.  Cost swept 5/10/15/20 bps.  IS/OOS = 60/40 chronological by
entry date + pre/post-2000 split + >=2016/>=2020.  Verdict bar = OOS PF >= 1.3
at 2x cost (10 bps).
"""
import json
import os
import datetime as dt

import numpy as np
import pandas as pd
import boto3

BUCKET = "trading-datalake-920641308584"
COST_BPS = [5.0, 10.0, 15.0, 20.0]
IS_CUT = 0.60


def load_etf(sym):
    s3 = boto3.client("s3", region_name="us-east-1")
    o = s3.get_object(Bucket=BUCKET, Key=f"yf/etfs/{sym}.json")
    d = json.loads(o["Body"].read().decode())
    df = pd.DataFrame(d["daily"])
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df[df["close"] > 0]


def pf_of(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return float("nan")
    wins = x[x > 0].sum()
    losses = -x[x < 0].sum()
    return wins / losses if losses > 0 else float("inf")


def tstat(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 2 or x.std() == 0:
        return float("nan")
    return float(x.mean() / (x.std() / np.sqrt(len(x))))


def summarize(rets, entry_dates, cost_bps):
    net = np.asarray([r - cost_bps / 10000.0 for r in rets], float)
    ed = pd.Series(pd.to_datetime(entry_dates))
    cut = ed.quantile(IS_CUT, interpolation="nearest")
    isd = ed <= cut
    oosd = ed > cut
    pre2k = ed < "2000-01-01"
    post2k = ed >= "2000-01-01"
    o16 = ed >= "2016-01-01"
    o20 = ed >= "2020-01-01"
    return {
        "n": int(len(net)),
        "avg_bps": float(np.nanmean(net) * 10000),
        "win": float((net > 0).mean()),
        "t": tstat(net),
        "pf": pf_of(net),
        "is_pf": pf_of(net[isd]), "oos_pf": pf_of(net[oosd]),
        "n_is": int(isd.sum()), "n_oos": int(oosd.sum()),
        "pre2000_pf": pf_of(net[pre2k]), "post2000_pf": pf_of(net[post2k]),
        "pf_2016": pf_of(net[o16]), "pf_2020": pf_of(net[o20]),
    }


def third_fridays(start_year, end_year):
    out = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            d = dt.date(y, m, 1)
            while d.weekday() != 4:      # first Friday
                d += dt.timedelta(days=1)
            d += dt.timedelta(days=14)   # 3rd Friday
            out.append(d)
    return sorted(out)


def build_opex_dates(df):
    """3rd Fridays adjusted onto the trading calendar (holiday -> prior trade day)."""
    dates = df.index
    yrs = (dates[0].year, dates[-1].year)
    out = []
    for f in third_fridays(*yrs):
        f = pd.Timestamp(f)
        # if not a trading day (holiday), walk back to the prior trading day
        while f not in dates and f >= dates[0]:
            f -= pd.Timedelta(days=1)
        if f in dates:
            out.append(f)
    # dedupe preserving order
    seen = set()
    uniq = []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def pre_opex_trades(df, opex_dates, exit_day_before=False):
    """Entry = close 5 trading days before expiration (the Friday before the OPEX
    week). Exit = close of expiration day, or the day before (4d hold)."""
    dates = df.index
    c = df["close"]
    trades = []
    for ex in opex_dates:
        exi = dates.get_loc(ex)
        ei = exi - 5
        if ei < 0:
            continue
        xi = exi - 1 if exit_day_before else exi
        e = c.iloc[ei]
        x = c.iloc[xi]
        trades.append({"entry_date": dates[ei], "ret": x / e - 1.0})
    return trades


def post_opex_trades(df, opex_dates):
    """Entry = close of expiration day. Exit = close 5 trading days later (the
    following week)."""
    dates = df.index
    c = df["close"]
    trades = []
    for ex in opex_dates:
        exi = dates.get_loc(ex)
        xi = exi + 5
        if xi >= len(dates):
            continue
        trades.append({"entry_date": dates[exi], "ret": c.iloc[xi] / c.iloc[exi] - 1.0})
    return trades


def drift_benchmark(df, hold=5):
    c = df["close"].to_numpy()
    r = c[hold:] / c[:-hold] - 1.0
    return {"mean_bps": r.mean() * 10000, "std_bps": r.std() * 10000,
            "win": (r > 0).mean(), "n": len(r)}


def main():
    print("=" * 100)
    print("OPEX (options-expiration) week drift — LONG into monthly 3rd-Friday expiration")
    print("=" * 100)
    out = {}

    for sym in ["SPY", "QQQ"]:
        df = load_etf(sym)
        opex = build_opex_dates(df)
        bm5 = drift_benchmark(df, 5)
        print(f"\n### {sym}  ({df.index[0].date()} .. {df.index[-1].date()}, {len(df)} bars)")
        print(f"  OPEX dates: {len(opex)} ({opex[0].date()} .. {opex[-1].date()})")
        print(f"  UNCONDITIONAL 5d drift: mean {bm5['mean_bps']:+.2f}bp  win {bm5['win']*100:.1f}%  (n={bm5['n']})")

        out[sym] = {}
        # pre-OPEX week: exit at expiration close (5d) and day-before (4d)
        for tag, exit_before in [("pre_opex_5d", False), ("pre_opex_4d", True)]:
            tr = pre_opex_trades(df, opex, exit_day_before=exit_before)
            print(f"  {tag} (n={len(tr)}):")
            for cost in COST_BPS:
                s = summarize([t["ret"] for t in tr], [t["entry_date"] for t in tr], cost)
                out[sym][f"{tag}@{int(cost)}bp"] = s
                if cost in (5.0, 10.0):
                    print(f"    @{int(cost)}bp: avg={s['avg_bps']:+.1f}bp t={s['t']:.2f} "
                          f"PF={s['pf']:.2f} (IS {s['is_pf']:.2f}/OOS {s['oos_pf']:.2f}) "
                          f"pre2000 {s['pre2000_pf']:.2f}/post2000 {s['post2000_pf']:.2f} "
                          f">=2016 {s['pf_2016']:.2f} >=2020 {s['pf_2020']:.2f}")

        # post-OPEX week (dealer gamma unwind)
        tr = post_opex_trades(df, opex)
        print(f"  post_opex_5d (n={len(tr)}):")
        for cost in COST_BPS:
            s = summarize([t["ret"] for t in tr], [t["entry_date"] for t in tr], cost)
            out[sym][f"post_opex_5d@{int(cost)}bp"] = s
            if cost in (5.0, 10.0):
                print(f"    @{int(cost)}bp: avg={s['avg_bps']:+.1f}bp t={s['t']:.2f} "
                      f"PF={s['pf']:.2f} (IS {s['is_pf']:.2f}/OOS {s['oos_pf']:.2f}) "
                      f"pre2000 {s['pre2000_pf']:.2f}/post2000 {s['post2000_pf']:.2f} "
                      f">=2016 {s['pf_2016']:.2f} >=2020 {s['pf_2020']:.2f}")

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "opex_week_results.json")
    with open(outpath, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f"\nWrote {outpath}")


if __name__ == "__main__":
    main()
