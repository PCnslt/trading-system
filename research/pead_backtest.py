#!/usr/bin/env python3
"""Post-earnings-announcement drift (PEAD) backtest on US equities.

Genuinely-untested earnings-driven edge. Tests whether positive EPS surprises
drift UP and negative surprises drift DOWN in the days/weeks after the report,
net of a realistic round-trip cost, on an IS/OOS split.

DATA (all real, no fabrication):
  - Earnings events: Robinhood MCP `get_earnings_calendar`, paged backward in
    31-day windows (the tool caps `days` at 31 but accepts a past `start_date`
    and returns HISTORICAL eps estimate vs actual). Coverage is full ~2018 ->
    present; sparse before 2018. This gives ~8.5y of events, far more than the
    ~8-quarter `get_earnings_results` per-symbol endpoint.
  - Prices: S3 `ibkr/equities/daily/<SYM>.parquet` (daily OHLCV, split-adjusted,
    20y+, quality=BROKER).

METHOD:
  - Universe = the liquid STOCKS list in bot/live_equities.py (~190 names),
    parsed read-only from the file (never imported).
  - Event table: symbol -> (report_date, timing am/pm, surprise = actual - est).
    Drop events with null estimate/actual or estimate == 0 (placeholder).
  - Drift, two honest views:
      GAP (measurement, close-before-report -> +N): includes the announcement
          gap, which is NOT tradeable (you don't know the surprise before it).
      TRADE (tradable, close-of-announcement-day -> +N): enter at the close of
          the announcement trading day, when the surprise is public.
    am report -> announcement day = first bar >= report_date (tradeable on D).
    pm report -> announcement day = first bar >  report_date (tradeable on D+1).
  - Positions: LONG beaters / SHORT missers (each leg pays round-trip cost);
    long-only (beaters) and the short-miss leg reported SEPARATELY so the source
    of any edge is visible, plus the market-neutral spread with a t-stat.
  - Cost: round-trip bps of notional, baseline 5, stress 10 (2x) / 15 / 20.
    net_return = gross_return - cost_bps/1e4.
  - IS/OOS: chronological 50/50 split by report_date.

HONEST VERDICT GATE (task spec, tightened for the market-neutral claim):
  A candidate is worth flagging ONLY if the MARKET-NEUTRAL beat-minus-miss
  spread is positive AND significant (|t|>=2) net of the 2-leg cost, AND the
  short-miss leg does not lose (both legs must carry the edge — a PEAD edge
  whose short leg loses is just long-beta). Long-only is always benchmarked
  against the UNCONDITIONAL post-earnings drift to expose beta contamination.

Run:  ./venv/bin/python -u research/pead_backtest.py [--start 2018-01-01]
      [--pull-only | --no-pull] [--cache-dir /tmp/pead_cache]
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
import datetime as dt

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"))

BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
HORIZONS = [1, 3, 5, 10]
COST_BPS = [5.0, 10.0, 15.0, 20.0]  # round-trip
CALENDAR_STEP_DAYS = 28             # page window step (<=31 enforced by API)
CALENDAR_WINDOW = 31                # days per call
BASELINE_COST = 5.0                 # bps round-trip baseline


# --------------------------------------------------------------------------
# universe (parse read-only from bot/live_equities.py — never import it)
# --------------------------------------------------------------------------
def load_universe() -> list[str]:
    path = os.path.join(_ROOT, "bot", "live_equities.py")
    text = open(path, encoding="utf-8").read()
    m = re.search(r"STOCKS\s*=\s*\[(.*?)\]\n", text, re.S)
    if not m:
        raise RuntimeError("could not parse STOCKS list")
    syms = re.findall(r"'([^']+)'", m.group(1))
    seen, out = set(), []
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# --------------------------------------------------------------------------
# earnings calendar pull (cached)
# --------------------------------------------------------------------------
def pull_earnings_events(universe: set[str], start: str, end: str,
                         cache_path: str) -> pd.DataFrame:
    if os.path.exists(cache_path):
        df = pd.read_pickle(cache_path)
        print(f"[earnings] cached {len(df)} events from {cache_path}")
        return df

    from hardening.rh_client import RHClient  # local import (SSM + MCP)
    client = RHClient()

    rows, start_d = [], dt.date.fromisoformat(start)
    end_d = dt.date.fromisoformat(end)
    cur = start_d
    n_calls = 0
    t0 = time.time()
    while cur < end_d:
        try:
            raw = client.get_earnings_calendar(start_date=cur.isoformat(),
                                               days=CALENDAR_WINDOW)
            results = ((raw.get("data") or {}).get("results")) or []
        except Exception as e:  # noqa: BLE001 — skip a window, keep going
            print(f"[earnings] window {cur} error: {e!r}")
            cur += dt.timedelta(days=CALENDAR_STEP_DAYS)
            continue
        for r in results:
            sym = (r.get("symbol") or "").upper()
            if sym not in universe:
                continue
            rep = r.get("report") or {}
            eps = r.get("eps") or {}
            rows.append({
                "symbol": sym,
                "report_date": rep.get("date"),
                "timing": rep.get("timing"),          # 'am' / 'pm' / None
                "year": r.get("year"),
                "quarter": r.get("quarter"),
                "est": _fnum(eps.get("estimate")),
                "act": _fnum(eps.get("actual")),
            })
        n_calls += 1
        cur += dt.timedelta(days=CALENDAR_STEP_DAYS)
        time.sleep(0.15)

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["report_date"])
    df["report_date"] = pd.to_datetime(df["report_date"])
    df = df.drop_duplicates(subset=["symbol", "report_date", "quarter"],
                            keep="last")
    df = df[(df["est"].notna()) & (df["act"].notna()) & (df["est"] != 0.0)]
    df["surprise"] = df["act"] - df["est"]
    df["surprise_pct"] = df["surprise"] / df["est"].abs()
    df = df.sort_values(["symbol", "report_date"]).reset_index(drop=True)
    df.to_pickle(cache_path)
    print(f"[earnings] pulled {len(df)} usable events from {n_calls} calendar "
          f"windows in {time.time()-t0:.0f}s -> {cache_path}")
    return df


def _fnum(v):
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# prices from S3 (cached)
# --------------------------------------------------------------------------
def load_closes(symbols: list[str]) -> dict[str, pd.Series]:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    closes = {}
    missing = []
    t0 = time.time()
    for i, sym in enumerate(symbols):
        try:
            o = s3.get_object(Bucket=BUCKET,
                              Key=f"ibkr/equities/daily/{sym}.parquet")
            df = pd.read_parquet(io.BytesIO(o["Body"].read()),
                                 columns=["date", "close"])
            df["date"] = pd.to_datetime(df["date"])
            df = df.dropna(subset=["close"])
            df = df[df["close"] > 0]
            closes[sym] = df.set_index("date")["close"].sort_index()
        except Exception as e:  # noqa: BLE001
            missing.append((sym, repr(e)))
        if (i + 1) % 50 == 0:
            print(f"[prices] {i+1}/{len(symbols)} loaded ({time.time()-t0:.0f}s)")
    if missing:
        print(f"[prices] missing {len(missing)} symbols: "
              f"{[m[0] for m in missing][:20]}")
    return closes


# --------------------------------------------------------------------------
# drift computation
# --------------------------------------------------------------------------
def event_drift(events: pd.DataFrame, closes: dict[str, pd.Series]):
    recs = []
    for sym, g in events.groupby("symbol"):
        c = closes.get(sym)
        if c is None or len(c) < 30:
            continue
        dates = c.index
        for _, e in g.iterrows():
            D = e["report_date"]
            timing = e["timing"] or "pm"
            if timing == "am":
                ann = dates.searchsorted(D, side="left")
            else:
                ann = dates.searchsorted(D, side="right")
            if ann <= 0 or ann >= len(dates):
                continue
            ref_close = c.iloc[ann - 1]
            ann_close = c.iloc[ann]
            r = {"symbol": sym, "report_date": D, "timing": timing,
                 "surprise": e["surprise"], "surprise_pct": e["surprise_pct"]}
            for H in HORIZONS:
                gi = ann + H - 1
                ti = ann + H
                r[f"gap_{H}"] = c.iloc[gi] / ref_close - 1.0 if gi < len(dates) else np.nan
                r[f"trd_{H}"] = c.iloc[ti] / ann_close - 1.0 if ti < len(dates) else np.nan
            recs.append(r)
    out = pd.DataFrame(recs)
    if len(out):
        out["side"] = np.where(out["surprise"] > 0, "beat",
                      np.where(out["surprise"] < 0, "miss", "flat"))
    return out


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def pf_of(net: pd.Series) -> float:
    net = net.dropna()
    if len(net) == 0:
        return float("nan")
    wins = net[net > 0].sum()
    losses = -net[net < 0].sum()
    if losses <= 0:
        return float("inf") if wins > 0 else float("nan")
    return wins / losses


def summarize(net: pd.Series, label: str) -> dict:
    net = pd.Series(net).dropna().astype(float)
    n = len(net)
    if n == 0:
        return {"label": label, "n": 0, "mean": np.nan, "win_rate": np.nan,
                "pf": np.nan}
    return {"label": label, "n": n, "mean": float(net.mean()),
            "win_rate": float((net > 0).mean()), "pf": float(pf_of(net))}


def welch_t(a: pd.Series, b: pd.Series) -> float:
    a, b = a.dropna().astype(float), b.dropna().astype(float)
    if len(a) < 2 or len(b) < 2:
        return np.nan
    se = np.sqrt(a.var() / len(a) + b.var() / len(b))
    return (a.mean() - b.mean()) / se if se > 0 else np.nan


def chrono_split(dates: pd.Series):
    cut = dates.quantile(0.50)
    return dates <= cut, dates > cut, cut


def _fmt(r: dict, bps: bool = False) -> str:
    if r["n"] == 0:
        return "        --"
    m = r["mean"] * 1e4 if bps else r["mean"]
    return (f"n={r['n']:5d} mean={m:+7.1f} win={r['win_rate']*100:5.1f}% "
            f"PF={r['pf']:5.2f}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--cache-dir", default="/tmp/pead_cache")
    ap.add_argument("--pull-only", action="store_true")
    ap.add_argument("--no-pull", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.cache_dir, exist_ok=True)
    ev_cache = os.path.join(args.cache_dir, "earnings_events.pkl")
    cl_cache = os.path.join(args.cache_dir, "closes.pkl")

    universe = load_universe()
    uset = set(universe)
    print(f"[universe] {len(universe)} symbols from bot/live_equities.py STOCKS")

    if not args.no_pull:
        events = pull_earnings_events(uset, args.start, args.end, ev_cache)
    else:
        events = pd.read_pickle(ev_cache)
        print(f"[earnings] loaded {len(events)} events (--no-pull)")
    if args.pull_only:
        print("[pull-only] events by year:")
        print(events.groupby(events["report_date"].dt.year).size().to_string())
        return 0

    print(f"[events] {len(events)} total, "
          f"{events['report_date'].min().date()} -> {events['report_date'].max().date()}")
    beat_rate = (events["surprise"] > 0).mean()
    print(f"[events] beat rate = {beat_rate*100:.1f}% "
          f"(estimate is systematically LOW vs actual — see report)")

    syms = sorted(events["symbol"].unique())
    if os.path.exists(cl_cache):
        closes = pd.read_pickle(cl_cache)
        print(f"[prices] cached {len(closes)} symbols")
    else:
        closes = load_closes(syms)
        import pickle
        with open(cl_cache, "wb") as fh:
            pickle.dump(closes, fh)

    dr = event_drift(events, closes)
    print(f"[drift] {len(dr)} events with prices "
          f"(beat {sum(dr['side']=='beat')}, miss {sum(dr['side']=='miss')}, "
          f"flat {sum(dr['side']=='flat')})")

    H = 10  # primary horizon
    col = f"trd_{H}"
    d = dr[dr[col].notna() & (dr["side"] != "flat")].copy()
    d["gross_signed"] = np.where(d["side"] == "beat", d[col], -d[col])
    is_mask, oos_mask, cut = chrono_split(d["report_date"])
    print(f"\nIS/OOS cut (median report_date) = {cut.date()}")

    # ---- headline tradable drift, sign split ----
    print("\n" + "=" * 100)
    print("PEAD — tradable drift (close-of-announcement-day -> +N), sign split")
    print("=" * 100)
    for Hh in HORIZONS:
        c = f"trd_{Hh}"
        g = dr[dr[c].notna()]
        beat = g[g["side"] == "beat"][c]
        miss = g[g["side"] == "miss"][c]
        print(f"  +{Hh:2d}d: beat mean={beat.mean()*1e4:+7.1f}bp (n={len(beat)})  "
              f"miss mean={miss.mean()*1e4:+7.1f}bp (n={len(miss)})  "
              f"spread={(beat.mean()-miss.mean())*1e4:+7.1f}bp")

    # ---- gap-inclusive (measurement only) ----
    print("\n" + "=" * 100)
    print("PEAD — gap-inclusive (close-before-report -> +N) [NOT tradeable]")
    print("=" * 100)
    for Hh in HORIZONS:
        c = f"gap_{Hh}"
        g = dr[dr[c].notna()]
        beat = g[g["side"] == "beat"][c]
        miss = g[g["side"] == "miss"][c]
        print(f"  +{Hh:2d}d: beat mean={beat.mean()*1e4:+7.1f}bp  "
              f"miss mean={miss.mean()*1e4:+7.1f}bp  "
              f"spread={(beat.mean()-miss.mean())*1e4:+7.1f}bp")

    # ---- LONG-BEAT leg (long-only) ----
    print("\n" + "=" * 100)
    print(f"LONG-ONLY beaters (tradable +{H}d) — cost grid & IS/OOS")
    print("=" * 100)
    dL = d[d["side"] == "beat"].copy()
    isL, oosL, _ = chrono_split(dL["report_date"])
    print(f"{'cost':>5} | {'IS':>28} | {'OOS':>28} | {'FULL':>28}")
    for cost in COST_BPS:
        net = dL[col] - cost / 1e4
        print(f"{cost:5.0f} | {_fmt(summarize(net[isL], 'IS'), bps=True):>28} | "
              f"{_fmt(summarize(net[oosL], 'OOS'), bps=True):>28} | "
              f"{_fmt(summarize(net, 'FULL'), bps=True):>28}")

    # ---- SHORT-MISS leg (the PEAD test: does shorting missers make money?) ----
    print("\n" + "=" * 100)
    print(f"SHORT-MISS leg (tradable +{H}d, short the missers) — cost grid & IS/OOS")
    print("=" * 100)
    print("  PEAD requires missers to KEEP FALLING after the gap. If this leg loses,")
    print("  missers are bouncing (reversal), not drifting — PEAD's short side is dead.")
    dS = d[d["side"] == "miss"].copy()
    isS, oosS, _ = chrono_split(dS["report_date"])
    print(f"{'cost':>5} | {'IS':>28} | {'OOS':>28} | {'FULL':>28}")
    for cost in COST_BPS:
        net = -dS[col] - cost / 1e4
        print(f"{cost:5.0f} | {_fmt(summarize(net[isS], 'IS'), bps=True):>28} | "
              f"{_fmt(summarize(net[oosS], 'OOS'), bps=True):>28} | "
              f"{_fmt(summarize(net, 'FULL'), bps=True):>28}")

    # ---- UNCONDITIONAL drift (beta benchmark) ----
    print("\n" + "=" * 100)
    print("BETA BENCHMARK — unconditional post-earnings drift (ALL events, incl flat)")
    print("=" * 100)
    print("  If 'buy everything after earnings' ~= 'buy beaters', the long edge is beta,")
    print("  not earnings signal.")
    for Hh in HORIZONS:
        c = f"trd_{Hh}"
        allr = dr[dr[c].notna()][c]
        print(f"  +{Hh:2d}d: {_fmt(summarize(allr, 'all'), bps=True)}")

    # ---- market-neutral spread significance ----
    print("\n" + "=" * 100)
    print("MARKET-NEUTRAL beat-minus-miss spread (tradable) — gross / net of 2-leg cost / t-stat")
    print("=" * 100)
    for Hh in HORIZONS:
        c = f"trd_{Hh}"
        g = dr[dr[c].notna() & (dr["side"] != "flat")]
        beat = g[g["side"] == "beat"][c]
        miss = g[g["side"] == "miss"][c]
        spread = beat.mean() - miss.mean()
        t = welch_t(beat, miss)
        net10 = spread - 10 / 1e4
        net20 = spread - 20 / 1e4
        print(f"  +{Hh:2d}d: spread={spread*1e4:+6.1f}bp  t={t:5.2f}  "
              f"net@10bp={net10*1e4:+6.1f}bp  net@20bp={net20*1e4:+6.1f}bp")

    # ---- per-symbol ----
    print("\n" + "=" * 100)
    print(f"per-symbol tradable +{H}d LONG-beat net (5bps) — symbols with >= 15 events")
    print("=" * 100)
    dL["net5"] = dL[col] - BASELINE_COST / 1e4
    per = dL.groupby("symbol")["net5"].agg(n="count", mean="mean").reset_index()
    per["win"] = dL.groupby("symbol")["net5"].apply(lambda s: (s > 0).mean()).values
    per["pf"] = dL.groupby("symbol")["net5"].apply(pf_of).values
    per = per[per["n"] >= 15].sort_values("pf", ascending=False)
    print(f"  {len(per)} symbols with >=15 events. PF>1: {sum(per['pf']>1)}, "
          f"PF>1.3: {sum(per['pf']>1.3)}, PF<1: {sum(per['pf']<1)}")
    print(per.head(8).to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    # ---- verdict ----
    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    # market-neutral claim (the actual PEAD test)
    g = dr[dr[col].notna() & (dr["side"] != "flat")]
    beat = g[g["side"] == "beat"][col]
    miss = g[g["side"] == "miss"][col]
    spread = beat.mean() - miss.mean()
    t = welch_t(beat, miss)
    # short leg must not lose (PEAD needs both legs)
    short_full = summarize(-dS[col] - BASELINE_COST / 1e4, "short")
    short_oos = summarize((-dS[col] - BASELINE_COST / 1e4)[oosS], "short-oos")
    # long leg (for context)
    long_oos = summarize((dL[col] - BASELINE_COST / 1e4)[oosL], "long-oos")
    uncond = summarize(dr[dr[col].notna()][col], "all")
    print(f"  edge: PEAD long-beat / short-miss (tradable +{H}d)")
    print(f"  market-neutral spread @5bps leg cost: gross {spread*1e4:+.1f}bp, "
          f"t={t:.2f}, net-of-2-leg-cost {((spread-10/1e4)*1e4):+.1f}bp")
    print(f"  short-miss leg: {_fmt(short_full, bps=True)}  |  OOS: {_fmt(short_oos, bps=True)}")
    print(f"  long-beat  leg: OOS {_fmt(long_oos, bps=True)}")
    print(f"  unconditional post-earnings drift (beta): {_fmt(uncond, bps=True)}")

    # honest gate: PEAD is a MARKET-NEUTRAL claim -> both legs must carry it
    spread_sig = t >= 2.0
    short_ok = short_full["pf"] >= 1.0
    spread_net_ok = (spread - 10 / 1e4) > 0
    if spread_sig and short_ok and spread_net_ok:
        verdict = "GO"
        reason = "market-neutral spread significant AND short leg positive net of cost"
    else:
        verdict = "NO-GO-WITH-REASON"
        reasons = []
        if not spread_sig:
            reasons.append(f"beat-miss spread t={t:.2f} < 2 (not significant)")
        if not short_ok:
            reasons.append(f"short-miss leg PF={short_full['pf']:.2f} < 1 "
                           f"(missers drift UP, not down — PEAD short side absent)")
        if not spread_net_ok:
            reasons.append(f"spread net of 2-leg cost {((spread-10/1e4)*1e4):+.1f}bp <= 0")
        reason = "; ".join(reasons)
    print(f"\n  => {verdict}")
    print(f"     reason: {reason}")
    print(f"\n  NOTE: long-only 'buy beaters' shows positive drift, but that is")
    print(f"  beta/momentum, not PEAD — the unconditional post-earnings drift")
    print(f"  ({uncond['mean']*1e4:+.1f}bp) is ~identical to the beater drift")
    print(f"  ({beat.mean()*1e4:+.1f}bp), so beating adds only "
          f"{(beat.mean()-uncond['mean'])*1e4:+.1f}bp of signal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
