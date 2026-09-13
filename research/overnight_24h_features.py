#!/usr/bin/env python3
"""Stage 2: per-symbol feature build for the 24h-market overnight-hold study.

For every cached symbol emit one row per trading day with everything the
analysis needs, so stage 3 never touches raw parquet again:

  sym, date, univ (bitmask 1=smallcap 2=largecap), close,
  ov_bp        = 1e4*(open[t+1]/close[t] - 1)      <- THE TRADE (buy close t, sell open t+1)
  prev_bp      = 1e4*(close[t]/close[t-1] - 1)     <- prior-day move (conditioner)
  dv20_musd    = 20d mean dollar volume, $M        <- historical liquidity gate
  cs_bp        = Corwin-Schultz (2012) proportional effective spread for that
                 symbol-YEAR, in bp, round-trip (buy at ask / sell at bid)
  ar_bp        = Abdi-Ranaldo (2017) close-high-low spread, same symbol-YEAR,
                 in bp (averages the product BEFORE the sqrt, so it does not
                 suffer CS's zero-flooring bias -- but is still very noisy)
  tick1_bp     = 100/close = round-trip cost of crossing a ONE-CENT quoted
                 spread. Physically binding lower bound given the $0.01 tick.
  dow          = 0..4 for the ENTRY day t
  tde          = trading days from end of calendar month for day t (0 = last)
  sig          = deployed dip signal on day t: Wilder RSI(2) < 5 AND close > SMA200
  c1..c5/o1..o5= close-entry vs open-entry hold-H total returns in bp, H in 1,2,3,5
                 c_H = 1e4*(close[t+H]/close[t]-1)      (evening / close entry)
                 o_H = 1e4*(close[t+H]/open[t+1]-1)     (next-open entry = deployed)

Corwin-Schultz: beta = sum of two consecutive squared log HL ranges, gamma =
squared log two-day range, alpha = (sqrt(2b)-sqrt(b))/(3-2sqrt2) - sqrt(g/(3-2sqrt2)),
S = 2(e^a-1)/(1+e^a); overnight-gap adjustment applied to day t+1 H/L; negative
two-day spreads floored at 0 before averaging into the yearly mean (CS 2012 p.727).

Run: ./venv/bin/python -u research/overnight_24h_features.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

CACHE_DIR = os.path.join(_ROOT, "research", ".ohlc_cache")
MANIFEST = os.path.join(CACHE_DIR, "_manifest.json")
OUT_DIR = os.path.join(_ROOT, "research", ".overnight24_features")

K = 3.0 - 2.0 * math.sqrt(2.0)


def corwin_schultz_by_year(df: pd.DataFrame) -> pd.Series:
    """Yearly mean CS proportional effective spread (round-trip, bp), by year."""
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    if len(h) < 3:
        return pd.Series(dtype=float)
    h1, l1 = h[:-1], l[:-1]          # day t
    h2, l2 = h[1:].copy(), l[1:].copy()  # day t+1 (adjusted)

    # overnight-gap adjustment (CS 2012): shift day t+1 range back onto day t's
    up = l2 > h1
    gap = np.where(up, l2 - h1, 0.0)
    down = h2 < l1
    gap = np.where(down, h2 - l1, gap)   # negative -> shifts up
    h2 = h2 - gap
    l2 = l2 - gap

    valid = (h1 > 0) & (l1 > 0) & (h2 > 0) & (l2 > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r1 = np.log(h1 / l1)
        r2 = np.log(h2 / l2)
        hi2 = np.maximum(h1, h2)
        lo2 = np.minimum(l1, l2)
        rg = np.log(hi2 / lo2)
    beta = r1 ** 2 + r2 ** 2
    gamma = rg ** 2
    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / K - np.sqrt(np.maximum(gamma, 0.0) / K)
    ea = np.exp(alpha)
    S = 2.0 * (ea - 1.0) / (1.0 + ea)
    S = np.where(valid & np.isfinite(S), S, np.nan)
    S = np.where(S < 0, 0.0, S)      # CS: floor negative two-day estimates at 0
    # the two-day estimate at index i covers days i and i+1 -> attribute to day i
    yrs = df.index[:-1].year
    s = pd.Series(S * 1e4, index=yrs)
    return s.groupby(level=0).mean()


def abdi_ranaldo_by_year(df: pd.DataFrame) -> pd.Series:
    """Abdi-Ranaldo (2017) close-high-low spread per year, bp round-trip.

    term_t = 4*(c_t - eta_t)*(c_t - eta_{t+1}) with c = log close and
    eta = (log high + log low)/2;  E[term] = S^2.  Average the terms across the
    year FIRST, then sqrt (floored at 0) -- this avoids the per-observation
    zero-flooring bias that inflates Corwin-Schultz.
    """
    c = np.log(df["close"].to_numpy(dtype=float))
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    eta = 0.5 * (np.log(hi) + np.log(lo))
    term = 4.0 * (c[:-1] - eta[:-1]) * (c[:-1] - eta[1:])
    term = np.where(np.isfinite(term), term, np.nan)
    s = pd.Series(term, index=df.index[:-1].year)
    mean_by_year = s.groupby(level=0).mean()
    return np.sqrt(mean_by_year.clip(lower=0.0)) * 1e4


def rsi_wilder2(c: pd.Series) -> pd.Series:
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


def trading_days_to_month_end(idx: pd.DatetimeIndex) -> np.ndarray:
    ym = idx.year * 100 + idx.month
    s = pd.Series(np.arange(len(idx)), index=ym)
    last = s.groupby(level=0).transform("max").to_numpy()
    return (last - np.arange(len(idx))).astype(np.int16)


def main() -> None:
    man = json.load(open(MANIFEST))
    sc = set(man["smallcap"])
    lc = set(man["largecap"])
    syms = sorted(sc | lc)
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        os.remove(os.path.join(OUT_DIR, f))
    print(f"[build] {len(syms)} symbols (smallcap {len(sc)}, largecap {len(lc)})")

    buf, part, nrows, t0 = [], 0, 0, time.time()
    for i, sym in enumerate(syms):
        p = os.path.join(CACHE_DIR, f"{sym}.parquet")
        if not os.path.exists(p):
            continue
        df = pd.read_parquet(p)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df = df[(df["close"] > 0) & (df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0)]
        if len(df) < 260:
            continue

        c, o = df["close"], df["open"]
        cs_year = corwin_schultz_by_year(df)
        ar_year = abdi_ranaldo_by_year(df)
        out = pd.DataFrame(index=df.index)
        out["ov_bp"] = (o.shift(-1) / c - 1.0) * 1e4
        out["prev_bp"] = (c / c.shift(1) - 1.0) * 1e4
        out["close"] = c
        out["dv20_musd"] = (c * df["volume"]).rolling(20).mean() / 1e6
        out["cs_bp"] = pd.Series(df.index.year, index=df.index).map(cs_year)
        out["ar_bp"] = pd.Series(df.index.year, index=df.index).map(ar_year)
        out["tick1_bp"] = 100.0 / c
        out["dow"] = df.index.dayofweek.astype("int8")
        out["tde"] = trading_days_to_month_end(df.index)
        rsi2 = rsi_wilder2(c)
        sma200 = c.rolling(200).mean()
        out["sig"] = ((rsi2 < 5.0) & (c > sma200)).to_numpy()
        for H in (1, 2, 3, 5):
            out[f"c{H}"] = (c.shift(-H) / c - 1.0) * 1e4
            out[f"o{H}"] = (c.shift(-H) / o.shift(-1) - 1.0) * 1e4
        out["sym"] = sym
        out["univ"] = np.int8((1 if sym in sc else 0) + (2 if sym in lc else 0))
        out = out[out["ov_bp"].notna()]
        for col in out.columns:
            if out[col].dtype == np.float64:
                out[col] = out[col].astype(np.float32)
        buf.append(out.reset_index().rename(columns={"index": "date"}))
        nrows += len(out)

        if len(buf) >= 100:
            pd.concat(buf, ignore_index=True).to_parquet(
                os.path.join(OUT_DIR, f"part{part:03d}.parquet"), index=False)
            part += 1
            buf = []
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(syms)} rows={nrows} ({time.time()-t0:.0f}s)", flush=True)

    if buf:
        pd.concat(buf, ignore_index=True).to_parquet(
            os.path.join(OUT_DIR, f"part{part:03d}.parquet"), index=False)
        part += 1
    print(f"[done] {nrows} rows in {part} parts -> {OUT_DIR} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
