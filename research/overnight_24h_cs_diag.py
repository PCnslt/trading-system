#!/usr/bin/env python3
"""Diagnostic: is the Corwin-Schultz implementation sane?

Compares, per symbol-year:
  cs_floor0 = mean over the year of two-day CS estimates with NEGATIVE two-day
              estimates floored at 0  (upward biased: floors symmetric noise)
  cs_avg    = mean over the year of RAW two-day CS estimates, then the YEARLY
              MEAN floored at 0       (CS 2012's recommended aggregation)
  tick1     = 100/price bp = round-trip cost of crossing a ONE-CENT spread
              (a hard lower bound given the $0.01 tick)
against reality (AAPL/MSFT effective spreads are ~1-5bp post-2010).
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
CACHE_DIR = os.path.join(_ROOT, "research", ".ohlc_cache")
K = 3.0 - 2.0 * math.sqrt(2.0)


def cs_two_day(df: pd.DataFrame) -> np.ndarray:
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    h1, l1 = h[:-1], l[:-1]
    h2, l2 = h[1:].copy(), l[1:].copy()
    gap = np.where(l2 > h1, l2 - h1, 0.0)
    gap = np.where(h2 < l1, h2 - l1, gap)
    h2, l2 = h2 - gap, l2 - gap
    with np.errstate(divide="ignore", invalid="ignore"):
        r1 = np.log(h1 / l1)
        r2 = np.log(h2 / l2)
        rg = np.log(np.maximum(h1, h2) / np.minimum(l1, l2))
    beta = r1 ** 2 + r2 ** 2
    gamma = rg ** 2
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / K - np.sqrt(np.maximum(gamma, 0) / K)
    ea = np.exp(alpha)
    S = 2.0 * (ea - 1.0) / (1.0 + ea) * 1e4
    return np.where(np.isfinite(S), S, np.nan)


def ar_terms(df: pd.DataFrame) -> np.ndarray:
    """Abdi-Ranaldo (2017) close-high-low per-pair term; E[term] = S^2.
    S = sqrt(max(0, mean(term))) -> averaging BEFORE the sqrt kills the
    zero-flooring bias that wrecks Corwin-Schultz at the per-day level."""
    c = np.log(df["close"].to_numpy(float))
    eta = 0.5 * (np.log(df["high"].to_numpy(float)) + np.log(df["low"].to_numpy(float)))
    t = 4.0 * (c[:-1] - eta[:-1]) * (c[:-1] - eta[1:])
    return np.where(np.isfinite(t), t, np.nan)


for sym in ["AAPL", "MSFT", "PFE", "T", "F", "SOFI", "SMCI", "IREN", "AAL"]:
    p = os.path.join(CACHE_DIR, f"{sym}.parquet")
    if not os.path.exists(p):
        print(f"{sym}: no data")
        continue
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    S = cs_two_day(df)
    AR = ar_terms(df)
    yr = df.index[:-1].year
    px = df["close"].to_numpy(float)[:-1]
    out = []
    for y in (2010, 2015, 2019, 2023, 2025):
        m = yr == y
        if m.sum() < 100:
            continue
        s = S[m]
        s = s[np.isfinite(s)]
        if s.size == 0:
            continue
        f0 = np.maximum(s, 0).mean()
        av = max(s.mean(), 0.0)
        a = AR[m]
        a = a[np.isfinite(a)]
        ar = math.sqrt(max(a.mean(), 0.0)) * 1e4 if a.size else float("nan")
        tick = float(np.nanmean(100.0 / px[m]))
        out.append(f"{y}: px${np.nanmean(px[m]):.0f} CSfloor0={f0:.1f} CSavg={av:.1f} "
                   f"AR={ar:.1f} tick1={tick:.1f}")
    print(f"{sym:<6} " + " | ".join(out))
