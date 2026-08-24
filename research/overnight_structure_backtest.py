#!/usr/bin/env python3
"""Overnight-vs-intraday structure of the deployed RSI(2) buy-the-dip signal,
and a close-entry vs open-entry timing comparison.

QUESTION (from the parent task):
  Is the RSI2 short-term-reversal "buy-the-dip" bounce earned in the OVERNIGHT
  (close->open) component or the INTRADAY (open->close) component, and does
  entering at the signal CLOSE beat entering at the next OPEN (the current
  deployment) net of cost?

Academic motivation: the US equity risk premium is earned overnight (close->open)
while intraday (open->close) returns are flat-to-negative (Lou-Polk-Skouras 2019
JFE "A Tug of War"; Hendershott-Livdan-Roesch 2020 JFE; Bogousslavsky 2021 JFE);
short-term reversal is specifically an overnight phenomenon.

DEPLOYED RULE (bot/live_equities.py): Wilder RSI(2) < 5 AND close > SMA200,
signal at close[t], enter at open[t+1], hold 2-5 days.  RSI(2) here is the
STANDARD WILDER RSI (ewm alpha = 1/2) exactly as in the bot's rsi() helper.

METHOD:
  - Universe = the liquid STOCKS list in bot/live_equities.py (190 names),
    parsed READ-ONLY from the file (never imported, per repo convention).
  - Prices: S3 `ibkr/equities/daily/<SYM>.parquet` (daily OHLCV, split-adjusted,
    quality=BROKER, 2006-08-21 .. 2026-08-14).
  - For each signal bar t, decompose the H-day forward return (H in {1,2,3,5}):
        overnight[t+1]   = open[t+1] / close[t]     - 1   (close-entry captures,
                                                           open-entry misses)
        intraday[t+1]    = close[t+1] / open[t+1]   - 1
        remainder[t+1,H] = close[t+H] / close[t+1]  - 1
        total[t,H]       = close[t+H] / close[t]    - 1   (= close-entry)
        open_entry[t,H]  = close[t+H] / open[t+1]   - 1   (= open-entry, deployed)
    Report the MEAN of each component and its share of the mean total bounce.
  - Entry-timing head-to-head, net of COST bps round-trip (5 baseline, 10 = 2x
    stress): CLOSE-entry vs OPEN-entry, with n / win-rate / mean / PF split
    IS (2006-2019) vs OOS (2020-2026).
  - Market-neutral framing (cheap add): long losers (RSI2<5 & close>SMA200),
    short winners (RSI2>95 & close<SMA200), per-leg + spread, 2-leg cost.

HONEST CAVEATS (also printed at the end):
  - Survivorship bias: today's liquid names back-applied 20y -> upper bound.
  - CLOSE-entry is optimistic: it assumes you can transact AT close[t] after
    observing close[t] (and the RSI2<5 crossing) -- you'd realistically get the
    closing auction / last prints, capturing slightly less than the full gap.
    OPEN-entry (deployed) has no such same-bar signal/price coupling.
  - No intraday 2xATR stop or revert exit modeled here: this measures the raw
    signal's forward-return STRUCTURE, not the deployed exit stack.
  - Per-signal (event-study) pooling: signals can overlap across days / names;
    stats are per-signal observations, not a non-overlapping portfolio.
  - Split-adjusted but NOT dividend-adjusted -> the overnight gap on ex-div days
    includes the ex-div drop, so the measured overnight premium is a (slight)
    lower bound.
  - BRK-B has no parquet object in the datalake (1/190 symbols) -> dropped.
  - Data ends 2026-08-14 (backfill lag), so OOS = 2020-01 .. 2026-08.

Run:  ./venv/bin/python -u research/overnight_structure_backtest.py
"""
from __future__ import annotations

import io
import os
import re
import sys
import time

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"))

BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
PREFIX = "ibkr/equities/daily/"
CACHE = os.path.join(_ROOT, "research", ".overnight_structure_cache.pkl")

HORIZONS = [1, 2, 3, 5]
COST_BPS = 5.0                # round-trip baseline
COST = COST_BPS / 10000.0
COST_2X = 2.0 * COST
IS_END = pd.Timestamp("2019-12-31")
RSI2_LONG = 5.0               # deployed: RSI(2) < 5
RSI2_SHORT = 95.0             # market-neutral mirror: RSI(2) > 95
MIN_BARS = 260


# --------------------------------------------------------------------------
# universe (parse read-only from bot/live_equities.py — never import it)
# --------------------------------------------------------------------------
def load_universe() -> list[str]:
    path = os.path.join(_ROOT, "bot", "live_equities.py")
    text = open(path, encoding="utf-8").read()
    m = re.search(r"^STOCKS\s*=\s*\[(.*?)\]\n", text, re.S | re.M)
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
# data loading (S3 -> cached pickle of close/open panels)
# --------------------------------------------------------------------------
def load_panel(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    if os.path.exists(CACHE):
        c, o, missing = pd.read_pickle(CACHE)
        print(f"[cache] loaded close/open panel from {os.path.basename(CACHE)}")
        return c, o, missing

    s3 = boto3.client("s3", region_name=AWS_REGION)
    closes, opens, missing = {}, {}, []
    t0 = time.time()
    for i, s in enumerate(symbols):
        try:
            obj = s3.get_object(Bucket=BUCKET, Key=PREFIX + s + ".parquet")
            df = pd.read_parquet(io.BytesIO(obj["Body"].read()),
                                 columns=["date", "open", "close"])
        except Exception as e:  # noqa: BLE001
            missing.append(s)
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df = df[(df["close"].notna()) & (df["close"] > 0) & (df["open"].notna()) & (df["open"] > 0)]
        closes[s] = df["close"]
        opens[s] = df["open"]
        if (i + 1) % 50 == 0:
            print(f"  loaded {i+1}/{len(symbols)} ({time.time()-t0:.0f}s)", flush=True)
    c = pd.DataFrame(closes)
    o = pd.DataFrame(opens)
    # align columns of open to close (open may lag close by one NaN row for
    # names that IPO mid-panel, but the panel column order must match)
    o = o.reindex(index=c.index, columns=c.columns)
    pd.to_pickle((c, o, missing), CACHE)
    print(f"[cache] wrote {os.path.basename(CACHE)}")
    return c, o, missing


# --------------------------------------------------------------------------
# indicators (Wilder RSI(2) exactly as bot/live_equities.rsi)
# --------------------------------------------------------------------------
def indicators(C: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    delta = C.diff()
    gain = delta.clip(lower=0).ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    rs = gain / loss.replace(0.0, np.nan)
    rsi2 = (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)
    sma200 = C.rolling(200).mean()
    return rsi2, sma200


# --------------------------------------------------------------------------
# metrics helpers
# --------------------------------------------------------------------------
def pf_of(x: np.ndarray) -> float:
    x = x[~np.isnan(x)]
    wins = x[x > 0].sum()
    losses = -x[x < 0].sum()
    return float(wins / losses) if losses > 1e-12 else float("inf")


def tstat(x: np.ndarray) -> float:
    x = x[~np.isnan(x)]
    if len(x) < 2:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def fmt_pf(p: float) -> str:
    return "inf" if np.isinf(p) else f"{p:.2f}"


def two_sample_t(a: np.ndarray, b: np.ndarray) -> float:
    """Welch t-stat for mean(a) - mean(b)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = np.sqrt(va / len(a) + vb / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else float("nan")


# --------------------------------------------------------------------------
# a metrics row for a return series with an IS/OOS split by date
# --------------------------------------------------------------------------
def series_metrics(net: np.ndarray, dates: pd.DatetimeIndex, label: str,
                   is_oos_split: bool = True) -> dict:
    net = np.asarray(net, dtype=float)
    dates = pd.DatetimeIndex(dates)
    m = ~np.isnan(net)
    net, dates = net[m], dates[m]
    out = {
        "label": label,
        "n": int(len(net)),
        "win_rate": float((net > 0).mean()) if len(net) else float("nan"),
        "mean_bps": float(net.mean() * 1e4) if len(net) else float("nan"),
        "pf": pf_of(net) if len(net) else float("nan"),
    }
    if is_oos_split:
        ism = dates <= IS_END
        oos = dates > IS_END
        out["is_pf"] = pf_of(net[ism]) if ism.any() else float("nan")
        out["oos_pf"] = pf_of(net[oos]) if oos.any() else float("nan")
        out["is_n"] = int(ism.sum())
        out["oos_n"] = int(oos.sum())
        out["is_win"] = float((net[ism] > 0).mean()) if ism.any() else float("nan")
        out["oos_win"] = float((net[oos] > 0).mean()) if oos.any() else float("nan")
    return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    symbols = load_universe()
    print(f"[universe] {len(symbols)} STOCKS symbols parsed from bot/live_equities.py")

    C, O, missing = load_panel(symbols)
    loaded = [s for s in symbols if s not in missing]
    print(f"[data] loaded {C.shape[1]} names, {C.shape[0]} rows "
          f"({C.index[0].date()} .. {C.index[-1].date()})")
    if missing:
        print(f"[data] MISSING ({len(missing)}): {missing}")

    rsi2, sma200 = indicators(C)

    sig_long = (rsi2 < RSI2_LONG) & (C > sma200)
    sig_short = (rsi2 > RSI2_SHORT) & (C < sma200)

    n_long = int(sig_long.values.sum())
    n_short = int(sig_short.values.sum())
    print(f"\n[signals] RSI2<5 & close>SMA200 (long dip-buy): {n_long}")
    print(f"[signals] RSI2>95 & close<SMA200 (short winner-fade): {n_short}")
    if n_long == 0:
        print("NO LONG SIGNALS — aborting (bug check).")
        return

    # forward components (panel-wide)
    overnight = O.shift(-1) / C - 1.0          # open[t+1]/close[t] - 1
    intraday = C.shift(-1) / O.shift(-1) - 1.0  # close[t+1]/open[t+1] - 1
    day1 = C.shift(-1) / C - 1.0                # close[t+1]/close[t] - 1

    # long-signal observation indices (row-major, matches .values[mask])
    rows, cols = np.where(sig_long.values)
    sig_dates = pd.DatetimeIndex(C.index[rows])
    sig_syms = np.asarray(C.columns)[cols]

    ov = overnight.values[sig_long.values]
    iv = intraday.values[sig_long.values]
    d1 = day1.values[sig_long.values]

    # ---------------- decomposition ----------------
    print("\n" + "=" * 78)
    print("OVERNIGHT vs INTRADAY DECOMPOSITION of the RSI2 bounce (all signals, pooled)")
    print("=" * 78)
    ov_m, iv_m, d1_m = np.nanmean(ov) * 1e4, np.nanmean(iv) * 1e4, np.nanmean(d1) * 1e4
    print(f"  overnight[t+1] = open[t+1]/close[t] - 1 : mean {ov_m:+.2f} bp  "
          f"(t={tstat(ov):+.2f}, n={int((~np.isnan(ov)).sum())}, {100*np.nanmean(ov>0):.1f}% > 0)")
    print(f"  intraday[t+1]  = close[t+1]/open[t+1] - 1: mean {iv_m:+.2f} bp  "
          f"(t={tstat(iv):+.2f}, {100*np.nanmean(iv>0):.1f}% > 0)")
    print(f"  day-1 total    = close[t+1]/close[t] - 1 : mean {d1_m:+.2f} bp")

    for H in HORIZONS:
        remain = (C.shift(-H) / C.shift(-1) - 1.0).values[sig_long.values]
        total = (C.shift(-H) / C - 1.0).values[sig_long.values]
        rm = np.nanmean(remain) * 1e4
        tm = np.nanmean(total) * 1e4
        print(f"\n  --- H = {H} day(s) ---")
        print(f"    overnight          {ov_m:+.2f} bp   share {100*ov_m/tm:+.1f}%")
        print(f"    intraday           {iv_m:+.2f} bp   share {100*iv_m/tm:+.1f}%")
        print(f"    remainder (d2..H)  {rm:+.2f} bp   share {100*rm/tm:+.1f}%")
        print(f"    total bounce       {tm:+.2f} bp   (close-entry gross)")
        print(f"    overnight+intraday share of total: {100*(ov_m+iv_m)/tm:+.1f}%")

    # ---------------- entry-timing head-to-head ----------------
    print("\n" + "=" * 78)
    print("CLOSE-ENTRY vs OPEN-ENTRY (net of round-trip cost), IS 2006-2019 / OOS 2020-2026")
    print("=" * 78)
    print(f"  {'H':>2} | {'entry':<10} | {'cost':>4} | {'n':>5} | {'win%':>5} | "
          f"{'mean bp':>7} | {'PF':>5} | {'IS PF':>6} | {'OOS PF':>6} | {'IS win':>6} | {'OOS win':>6}")
    print("  " + "-" * 76)
    for H in HORIZONS:
        close_ret = (C.shift(-H) / C - 1.0).values[sig_long.values]          # enter close[t]
        open_ret = (C.shift(-H) / O.shift(-1) - 1.0).values[sig_long.values]  # enter open[t+1]
        for cost_bps, cost_label in [(5.0, "5"), (10.0, "10")]:
            cost = cost_bps / 10000.0
            for entry, ret in [("CLOSE", close_ret), ("OPEN", open_ret)]:
                net = ret - cost
                r = series_metrics(net, sig_dates, entry)
                print(f"  {H:>2} | {entry:<10} | {cost_label:>4} | {r['n']:>5} | "
                      f"{100*r['win_rate']:>4.0f}% | {r['mean_bps']:>+7.2f} | "
                      f"{fmt_pf(r['pf']):>5} | {fmt_pf(r['is_pf']):>6} | {fmt_pf(r['oos_pf']):>6} | "
                      f"{100*r['is_win']:>5.0f}% | {100*r['oos_win']:>5.0f}%")

    # paired close - open = the overnight gap captured (identical for every H)
    print("\n  Paired (CLOSE - OPEN) per signal == overnight gap (same across H):")
    gap = close_ret - open_ret  # == overnight
    print(f"    mean {np.nanmean(gap)*1e4:+.2f} bp, {100*np.nanmean(gap>0):.1f}% of gaps > 0, "
          f"t={tstat(gap):+.2f}")

    # ---------------- market-neutral framing ----------------
    print("\n" + "=" * 78)
    print("MARKET-NEUTRAL: long losers (RSI2<5 & >SMA200) / short winners (RSI2>95 & <SMA200)")
    print("=" * 78)
    # close-entry gross returns for both legs (H=2 default hold for spread)
    H = 2
    long_ret = (C.shift(-H) / C - 1.0).values[sig_long.values]
    short_ret = (C.shift(-H) / C - 1.0).values[sig_short.values]
    lr, _ = np.where(sig_long.values)
    sr, _ = np.where(sig_short.values)
    long_dates = pd.DatetimeIndex(C.index[lr])
    short_dates = pd.DatetimeIndex(C.index[sr])
    print(f"  (hold H={H}d, close-entry; short-side borrow cost NOT modeled -> short leg is optimistic)")
    for cost_bps in (5.0, 10.0):
        cost = cost_bps / 10000.0
        print(f"\n  --- cost = {cost_bps:.0f} bp round-trip per leg ---")
        # LONG leg: long losers, P&L = +long_ret
        rl = series_metrics(long_ret - cost, long_dates, "LONG losers")
        # SHORT leg: short winners, P&L = -short_ret
        rs = series_metrics(-short_ret - cost, short_dates, "SHORT winners")
        print(f"    {'LONG (losers)':<16} n={rl['n']:>5}  win {100*rl['win_rate']:>4.0f}%  "
              f"mean {rl['mean_bps']:>+7.2f} bp  PF {fmt_pf(rl['pf']):>5}  "
              f"IS PF {fmt_pf(rl['is_pf']):>5}  OOS PF {fmt_pf(rl['oos_pf']):>5}")
        print(f"    {'SHORT (winners)':<16} n={rs['n']:>5}  win {100*rs['win_rate']:>4.0f}%  "
              f"mean {rs['mean_bps']:>+7.2f} bp  PF {fmt_pf(rs['pf']):>5}  "
              f"IS PF {fmt_pf(rs['is_pf']):>5}  OOS PF {fmt_pf(rs['oos_pf']):>5}")
        # SPREAD = mean(long) - mean(short) [pooled, per-signal], net of 2 legs
        spread_bps = (np.nanmean(long_ret) - np.nanmean(short_ret)) * 1e4
        spread_net = spread_bps - 2 * cost_bps
        t = two_sample_t(long_ret, short_ret)
        print(f"    {'SPREAD (L-S)':<16} gross mean {spread_bps:+.2f} bp  (t={t:+.2f}, Welch)  "
              f"-> net of 2-leg cost: {spread_net:+.2f} bp")

    # ---------------- caveats ----------------
    print("\n" + "=" * 78)
    print("CAVEATS")
    print("=" * 78)
    for line in [
        "1. Survivorship bias: today's liquid names back-applied 20y -> all edges are UPPER bounds.",
        "2. CLOSE-entry is optimistic: buying AT close[t] requires knowing close[t] (and the RSI2<5",
        "   crossing) before the close. Realistically you'd get the closing auction / last prints and",
        "   capture slightly less than the full overnight gap. OPEN-entry (deployed) has no such",
        "   same-bar signal/price coupling.",
        "3. No intraday 2xATR stop or revert exit modeled: this is the raw signal's forward-return",
        "   STRUCTURE, not the full deployed exit stack (which trades MORE often and pays more cost).",
        "4. Per-signal (event-study) pooling: signals overlap across days/names; stats are per-signal",
        "   observations, not a non-overlapping, position-capped portfolio.",
        "5. Split-adjusted but NOT dividend-adjusted: overnight gap on ex-div days includes the ex-div",
        "   drop, so measured overnight premium is a (small) lower bound.",
        f"6. Missing symbols dropped: {missing if missing else 'none'}.",
        "7. Data ends 2026-08-14 (backfill lag) -> OOS = 2020-01 .. 2026-08 (~6.6y).",
    ]:
        print("   " + line)


if __name__ == "__main__":
    main()
