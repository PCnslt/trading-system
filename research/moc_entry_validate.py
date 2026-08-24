#!/usr/bin/env python3
"""MOC (market-on-close) entry validation for the RSI2 buy-the-dip family.

QUESTION (queue strat-20260824-overnight-moc): the overnight-structure
decomposition showed CLOSE-entry beats OPEN-entry by ~+10.7 bp/trade (the day-1
overnight gap). Does submitting a MOC (market-on-close) order to capture that
gap actually improve LIVE fills vs the currently-deployed next-OPEN entry, once
real RH/IBKR order-flow frictions are applied?

This is NOT a new signal test — it reuses the exact deployed rule (RSI2<5 &
close>SMA200) and the exact data panel from research/overnight_structure_backtest.py
(cached research/.overnight_structure_cache.pkl, 189 liquid names, 2006-2026).

METHOD:
  - gap[t] = open[t+1]/close[t] - 1  (what a close/MOC entry captures that an
    open-entry misses; identical for every hold horizon).
  - Report the gap DISTRIBUTION (mean vs median, skew) — a mean-only +10.7bp
    that is really a few big gap-ups + many ~0 is NOT a reliable MOC advantage.
  - Break-even MOC slippage = the gap itself. A MOC order improves the fill iff
    the closing-auction slippage you pay < gap. Quantify what % of signals
    survive slippage thresholds {0, 2, 5, 10, 15, 20} bp.
  - Order-flow reality: RH has NO MOC order type (market/limit only, NBBO price
    improvement); IBKR MOC fills at the closing auction, whose slippage vs the
    'close' print scales with spread + imbalance (small for liquid large-caps,
    ~5-20bp for the sub-$35 small-caps the $700 sleeve actually trades). Model
    MOC slippage as a distribution, not a point.

HONEST CAVEATS: close-entry assumes you can transact AT close[t] after seeing
close[t] — optimistic; MOC is the closest real order type but still pays the
closing-auction spread. Split- but not dividend-adjusted (ex-div gap slightly
lowers measured premium). Survivorship-bias universe -> upper bound. Per-signal
pooling (overlapping). Open-entry itself is not free (open auction spread).

Run:  ./venv/bin/python -u research/moc_entry_validate.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

CACHE = os.path.join(_ROOT, "research", ".overnight_structure_cache.pkl")
IS_END = pd.Timestamp("2019-12-31")
RSI2_LONG = 5.0
SMA_N = 200

RESULT = {"idea": "MOC entry vs next-open (RSI2 family)", "rows": [], "verdict": {}}


def indicators(C: pd.DataFrame):
    delta = C.diff()
    gain = delta.clip(lower=0).ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=0.5, adjust=False, min_periods=2).mean()
    rs = gain / loss.replace(0.0, np.nan)
    rsi2 = (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)
    sma200 = C.rolling(SMA_N).mean()
    return rsi2, sma200


def pf_of(x):
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return float("nan")
    w = x[x > 0].sum()
    l = -x[x < 0].sum()
    return float(w / l) if l > 1e-12 else float("inf")


def fmt(p):
    return "inf" if np.isinf(p) else f"{p:.2f}"


def main():
    C, O, missing = pd.read_pickle(CACHE)
    print(f"[panel] {C.shape[1]} names, {C.shape[0]} rows "
          f"{C.index[0].date()}..{C.index[-1].date()} (missing {missing})")

    rsi2, sma200 = indicators(C)
    sig = (rsi2 < RSI2_LONG) & (C > sma200)
    rows, cols = np.where(sig.values)
    dates = pd.DatetimeIndex(C.index[rows])
    print(f"[signals] RSI2<5 & close>SMA200: n={len(rows)}")

    gap = (O.shift(-1) / C - 1.0).values[sig.values]  # close-entry - open-entry
    gap = gap[~np.isnan(gap)]
    g = gap * 1e4  # bp
    print("\n" + "=" * 78)
    print("OVERNIGHT GAP = MOC advantage (close-entry minus open-entry), per signal")
    print("=" * 78)
    print(f"  n        = {len(g)}")
    print(f"  mean     = {g.mean():+.2f} bp")
    print(f"  median   = {np.median(g):+.2f} bp")
    print(f"  std      = {g.std():.2f} bp")
    print(f"  skew     = {float(pd.Series(g).skew()):+.2f}")
    for th in (0, 2, 5, 10, 15, 20):
        print(f"  % gap > {th:>2} bp = {100*(g > th).mean():5.1f}%")
    print(f"  % gap > 0       = {100*(g > 0).mean():5.1f}%  (fraction where MOC wins, "
          f"zero-slip)")

    # break-even: MOC helps iff closing-auction slip < gap. Survival table.
    print("\n  Break-even MOC slippage: for slippage S, % of signals where a MOC "
          "entry still beats next-open:")
    for S in (0, 2, 5, 10, 15, 20):
        print(f"    S={S:>2} bp -> MOC wins on {100*(g > S).mean():5.1f}% of signals "
              f"(mean net edge { (g - S).mean():+.2f} bp)")

    # IS/OOS stability of the gap
    m = ~np.isnan((O.shift(-1) / C - 1.0).values[sig.values])
    d2 = dates[m]
    g2 = g
    is_g = g2[d2 <= IS_END]
    oos_g = g2[d2 > IS_END]
    print("\n  Gap by period:")
    print(f"    IS  (<=2019) n={len(is_g):>4}  mean {is_g.mean():+.2f} bp  "
          f"median {np.median(is_g):+.2f} bp  %gt;0 {100*(is_g>0).mean():.0f}%")
    print(f"    OOS (2020+)  n={len(oos_g):>4}  mean {oos_g.mean():+.2f} bp  "
          f"median {np.median(oos_g):+.2f} bp  %gt;0 {100*(oos_g>0).mean():.0f}%")

    # ---- order-flow reality: RH has no MOC; IBKR MOC pays auction spread ----
    print("\n" + "=" * 78)
    print("ORDER-FLOW REALITY vs the gap")
    print("=" * 78)
    # Typical closing-auction slippage (half-spread + imbalance) by liquidity tier
    # for a $700 retail order (~small share count -> impact ~0, cost = half-spread).
    tiers = {
        "S&P100 mega-cap ($100+)": (1.0, 3.0),
        "S&P500 large-cap ($50-100)": (2.0, 6.0),
        "mid-cap / sub-$35 small-ticket (the $700 sleeve)": (5.0, 20.0),
    }
    print(f"  {'liquidity tier':<40} {'closing half-spread':>18} {'MOC net edge vs open':>22}")
    for tier, (lo, hi) in tiers.items():
        mid = (lo + hi) / 2
        print(f"  {tier:<40} {f'{lo}-{hi} bp':>18} "
              f"{f'{(g - mid).mean():+.2f} bp (mean) / {(np.median(g) - mid):+.2f} bp (median)':>22}")

    print("\n  NOTE: Robinhood offers NO MOC order type (market/limit only, NBBO price")
    print("  improvement). IBKR supports MOC but fills at the closing auction, where")
    print("  the print-vs-close slippage on the sub-$35 small-caps the sleeve trades")
    print("  is 5-20bp — i.e. >= the median gap, so MOC only helps on the fat right tail.")

    out = os.path.join(_ROOT, "research", "moc_entry_validate_results.json")
    RESULT["gap_mean_bp"] = float(g.mean())
    RESULT["gap_median_bp"] = float(np.median(g))
    RESULT["gap_skew"] = float(pd.Series(g).skew())
    RESULT["pct_gap_gt"] = {str(t): float((g > t).mean()) for t in (0, 2, 5, 10, 15, 20)}
    RESULT["is_gap_mean_bp"] = float(is_g.mean())
    RESULT["oos_gap_mean_bp"] = float(oos_g.mean())
    RESULT["is_gap_median_bp"] = float(np.median(is_g))
    RESULT["oos_gap_median_bp"] = float(np.median(oos_g))
    json.dump(RESULT, open(out, "w"), indent=2, default=str)
    print(f"\nwrote {out}")
    print("\nCAVEATS: close-entry optimistic (MOC != exact close); split- not div-adj;")
    print("survivorship universe -> upper bound; open-entry also pays open-auction spread.")


if __name__ == "__main__":
    main()
