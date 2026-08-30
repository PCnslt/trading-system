#!/usr/bin/env python3
"""Post-FOMC announcement drift + CMVJ even-week overlay — honest backtest.

Queue item strat-20260828-fomc-post-drift. Claims under test:

  (1) "Post-FOMC Drift": LONG SPY/QQQ at the CLOSE of the FOMC announcement day,
      EXIT after 2-3 trading days (the announcement is at 14:00 ET so a close
      entry has no lookahead).  Also the "buy-after-bad-news" variant (condition
      on the announcement-day return < 0).
  (2) "Post-FOMC Announcement Reversal": the day AFTER the announcement is
      claimed to be negative over the last ~15yrs.
  (3) Cieslak-Morse-Vissing-Jorgensen (2019) "even-week" overlay: the equity
      premium is earned almost entirely in even FOMC-cycle weeks 0/2/4/6, odd
      weeks are ~flat.  Tested as a long-even/flat-odd weekly overlay.

Distinct from retired pre-FOMC Lane 52 (which entered the day BEFORE and exited
on announcement day).  Same FOMC calendar (263 scheduled meetings 1994-2026,
research/fomc_calendar.json).

Honest fills (repo equities pattern): round-trip bps deducted from every trade,
PF on net returns. Cost swept 5/10/15/20 bps. IS/OOS = 60/40 chronological by
entry date + >=2016 + >=2020 splits. Verdict bar = OOS PF >= 1.3 at 2x cost (10bps).
"""
import json
import os
import bisect
import datetime as dt

import numpy as np
import pandas as pd
import boto3

BUCKET = "trading-datalake-920641308584"
COST_BPS = [5.0, 10.0, 15.0, 20.0]
IS_CUT = 0.60
HOLDS = [2, 3, 5]


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
    cal = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "fomc_calendar.json")))
    df = pd.DataFrame(cal)
    df["announce_date"] = pd.to_datetime(df["announce_date"])
    return df.sort_values("announce_date").reset_index(drop=True)


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


def simple_stats(rets):
    """Gross stats without IS/OOS (for daily-return diagnostics)."""
    x = np.asarray(rets, float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return {"n": 0, "avg_bps": float("nan"), "t": float("nan"),
                "win": float("nan"), "pf": float("nan")}
    return {"n": int(len(x)), "avg_bps": float(x.mean() * 10000),
            "t": tstat(x), "win": float((x > 0).mean()), "pf": pf_of(x)}


def two_sample_diff(a, b):
    """Welch two-sample difference in means (a - b), t-stat, in bp."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    a = a[~np.isnan(a)]; b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    va = a.var(ddof=1) / len(a)
    vb = b.var(ddof=1) / len(b)
    se = np.sqrt(va + vb)
    diff = a.mean() - b.mean()
    return float(diff * 10000), float(diff / se) if se > 0 else float("nan")


def summarize(rets, entry_dates, cost_bps):
    """PF etc. on NET returns. IS/OOS 60/40 by entry date, plus >=2016/>=2020."""
    net = np.asarray([r - cost_bps / 10000.0 for r in rets], float)
    ed = pd.Series(pd.to_datetime(entry_dates))
    cut = ed.quantile(IS_CUT, interpolation="nearest")
    isd = ed <= cut
    oosd = ed > cut
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
        "pf_2016": pf_of(net[o16]), "pf_2020": pf_of(net[o20]),
    }


def post_fomc_trades(df, fomc, hold, entry="close"):
    """LONG at entry price of announcement day (close, or next-day open),
    EXIT at close 'hold' trading days after the announcement day."""
    dates = df.index
    trades = []
    for ann in fomc["announce_date"]:
        if ann not in dates:
            continue
        ai = dates.get_loc(ann)
        if entry == "close":
            e = df["close"].iloc[ai]
            entry_date = ann
        else:  # next open
            if ai + 1 >= len(df):
                continue
            e = df["open"].iloc[ai + 1]
            entry_date = dates[ai + 1]
        xi = ai + hold
        if xi >= len(df):
            continue
        x = df["close"].iloc[xi]
        ann_ret = df["close"].iloc[ai] / df["close"].iloc[ai - 1] - 1.0 if ai > 0 else np.nan
        trades.append({"entry_date": entry_date, "ret": x / e - 1.0,
                       "ann_ret": ann_ret, "presser": bool(
            fomc.loc[fomc["announce_date"] == ann, "presser"].iloc[0])})
    return trades


def next_day_reversal(df, fomc):
    """Return of the trading day AFTER the announcement (announcement-day close
    -> next-day close).  The 'post-FOMC reversal' claim."""
    dates = df.index
    rets, eds = [], []
    for ann in fomc["announce_date"]:
        if ann not in dates:
            continue
        ai = dates.get_loc(ann)
        if ai + 1 >= len(df):
            continue
        rets.append(df["close"].iloc[ai + 1] / df["close"].iloc[ai] - 1.0)
        eds.append(dates[ai + 1])
    return rets, eds


def classify_week(day, ann_sorted):
    """Return ('even'|'odd', week_idx) of the FOMC-cycle week containing 'day'.
    Cycle resets at each announcement. week 0 = announcement week."""
    pos = bisect.bisect_right(ann_sorted, day) - 1
    if pos < 0:
        return None, None
    ann = ann_sorted[pos]
    ann_mon = ann - dt.timedelta(days=ann.weekday())
    day_mon = day - dt.timedelta(days=day.weekday())
    week = (day_mon - ann_mon).days // 7
    week = min(week, 7)
    return ("even" if week % 2 == 0 else "odd"), week


def even_week_analysis(df, fomc):
    """Daily close-to-close returns split by even/odd FOMC-cycle week."""
    ann_sorted = sorted(fomc["announce_date"])
    c = df["close"]
    dates = df.index
    even, odd = [], []
    for i in range(1, len(df)):
        w, _ = classify_week(dates[i], ann_sorted)
        if w is None:
            continue
        r = c.iloc[i] / c.iloc[i - 1] - 1.0
        (even if w == "even" else odd).append(r)
    return even, odd


def weekly_overlay_trades(df, fomc, cost_bps):
    """Long every 'even' week: enter at the close of the last trading day of the
    prior (odd) week, exit at the close of the last trading day of the even week."""
    ann_sorted = sorted(fomc["announce_date"])
    dates = df.index
    c = df["close"]
    # map each trading day -> (week_label, week_idx, cycle_ann)
    info = {}
    for d in dates:
        info[d] = classify_week(d, ann_sorted)
    trades = []
    i = 0
    while i < len(dates):
        lab, _ = info[dates[i]]
        if lab != "even":
            i += 1
            continue
        # even week: find its last trading day
        j = i
        while j + 1 < len(dates) and info[dates[j + 1]][0] == "even":
            j += 1
        # entry = close of prior day (i-1), if exists and is odd week
        if i - 1 < 0 or info[dates[i - 1]][0] != "odd":
            i = j + 1
            continue
        e = c.iloc[i - 1]
        x = c.iloc[j]
        ret = x / e - 1.0 - cost_bps / 10000.0
        trades.append({"entry_date": dates[i], "ret": ret})
        i = j + 1
    return trades


def main():
    fomc = load_fomc_calendar()
    print("=" * 100)
    print(f"FOMC calendar: {len(fomc)} scheduled meetings "
          f"{fomc['announce_date'].min().date()} .. {fomc['announce_date'].max().date()}")
    print("=" * 100)

    out = {"fomc_meetings": len(fomc), "post_fomc_drift": {},
           "next_day_reversal": {}, "even_week": {}}

    for sym in ["SPY", "QQQ"]:
        df = load_etf(sym)
        print(f"\n### {sym}  ({df.index[0].date()} .. {df.index[-1].date()}, {len(df)} bars)")

        # 1. post-FOMC drift, close entry, all meetings
        print("  POST-FOMC DRIFT (LONG at announcement-day close, exit H days later):")
        for hold in HOLDS:
            for cost in [COST_BPS[0], COST_BPS[1]]:
                tr = post_fomc_trades(df, fomc, hold, entry="close")
                s = summarize([t["ret"] for t in tr], [t["entry_date"] for t in tr], cost)
                out["post_fomc_drift"][f"{sym}_H{hold}_close@{int(cost)}bp"] = s
                print(f"    H={hold} @{int(cost)}bp: n={s['n']} avg={s['avg_bps']:+.1f}bp "
                      f"t={s['t']:.2f} PF={s['pf']:.2f} (IS {s['is_pf']:.2f}/OOS {s['oos_pf']:.2f}) "
                      f">=2016 {s['pf_2016']:.2f} >=2020 {s['pf_2020']:.2f}")

        # 2. post-FOMC drift, bad-news conditioned (announcement-day ret < 0)
        print("  POST-FOMC DRIFT (bad-news conditioned: announcement-day return < 0):")
        for hold in HOLDS:
            tr = post_fomc_trades(df, fomc, hold, entry="close")
            bad = [t for t in tr if t["ann_ret"] < 0]
            s = summarize([t["ret"] for t in bad], [t["entry_date"] for t in bad], COST_BPS[1])
            out["post_fomc_drift"][f"{sym}_H{hold}_badnews@10bp"] = s
            print(f"    H={hold} @10bp: n={s['n']} avg={s['avg_bps']:+.1f}bp t={s['t']:.2f} "
                  f"PF={s['pf']:.2f} (IS {s['is_pf']:.2f}/OOS {s['oos_pf']:.2f}) "
                  f">=2020 {s['pf_2020']:.2f}")

        # 3. next-open entry robustness (H=2)
        tr = post_fomc_trades(df, fomc, 2, entry="open")
        s = summarize([t["ret"] for t in tr], [t["entry_date"] for t in tr], COST_BPS[1])
        out["post_fomc_drift"][f"{sym}_H2_nextopen@10bp"] = s
        print(f"    H=2 next-open entry @10bp: n={s['n']} avg={s['avg_bps']:+.1f}bp "
              f"PF={s['pf']:.2f} (OOS {s['oos_pf']:.2f})")

        # 4. next-day reversal
        ndr, nded = next_day_reversal(df, fomc)
        s = summarize(ndr, nded, 0.0)
        out["next_day_reversal"][sym] = s
        print(f"  POST-FOMC NEXT-DAY (ann+1) reversal: n={s['n']} avg={s['avg_bps']:+.1f}bp "
              f"t={s['t']:.2f} win={s['win']:.0%} PF(gross)={s['pf']:.2f}")

        # 5. even-week overlay
        even, odd = even_week_analysis(df, fomc)
        se = simple_stats(even)
        so = simple_stats(odd)
        diff_bp, diff_t = two_sample_diff(even, odd)
        out["even_week"][sym] = {"even": se, "odd": so,
                                 "spread_bp": diff_bp, "spread_t": diff_t}
        print(f"  EVEN-WEEK overlay (daily, gross): even n={se['n']} avg={se['avg_bps']:+.2f}bp "
              f"t={se['t']:.2f} | odd n={so['n']} avg={so['avg_bps']:+.2f}bp t={so['t']:.2f} | "
              f"spread={diff_bp:+.2f}bp t={diff_t:.2f}")
        for cost in [COST_BPS[0], COST_BPS[1]]:
            wt = weekly_overlay_trades(df, fomc, cost)
            sw = summarize([t["ret"] for t in wt], [t["entry_date"] for t in wt], 0.0)
            out["even_week"][f"{sym}_weekly@{int(cost)}bp"] = sw
            print(f"    weekly long-even/flat-odd @{int(cost)}bp: n={sw['n']} "
                  f"avg={sw['avg_bps']:+.1f}bp t={sw['t']:.2f} PF={sw['pf']:.2f} "
                  f"(IS {sw['is_pf']:.2f}/OOS {sw['oos_pf']:.2f}) >=2020 {sw['pf_2020']:.2f}")

    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "fomc_post_drift_results.json")
    with open(outpath, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f"\nWrote {outpath}")


if __name__ == "__main__":
    main()
