# Backtest Caveats — read before trusting any strategy number

Every backtest result in this repo is an **upper bound**. These caveats were found in
the 2026-08-28 deep audit and apply to ALL universe-based studies (indicator_sweep,
stoch_trailing, intraday_strategies_eval, rsi14_robustness, gap_go_backtest, etc.).

## 1. SURVIVORSHIP BIAS (CRITICAL — inflates every result)

Universes are built from **today's** index constituents / today's liquid listings,
back-applied through history (`universe_1500.json` ← current S&P 500/400/600;
small-cap ← current Nasdaq listings). Any name that delisted, went bankrupt, or left
the index before today is **excluded**, so the backtest only ever sees survivors.

This is worst for buy-the-dip mean-reversion (RSI2, STOCH, Bollinger, Pivot): the
beaten-down names that kept falling to zero are exactly the trades the backtest omits.
**All reported PF / avg-bp / t are upper bounds — the true edge is lower, possibly much
lower for small/mid-caps.**

Fix (not yet done): point-in-time universe from CRSP/Compustat (or reconstructed
historical index membership) with delisting returns. Until then, every result carries
the label "survivorship-biased upper bound."

## 2. t-stats are inflated (trade-level, correlated same-day trades)

Per-trade t = mean/(std/√n) treats thousands of same-day trades across hundreds of
symbols as independent. They are strongly cross-sectionally correlated (market beta),
so effective n ≪ nominal n. A "t = 9.98" is not 10σ of independent evidence — a chunk
of it is beta. Fix: date-clustered t (block bootstrap / Newey-West) or t on the daily
cross-sectional mean.

## 3. Cost under-estimation

Headline results use 5bp/side. Measured open-sell leg is ~12bp, and sub-$50 small/mid
spreads are wider. Realistic headline is ≥10bp/side with 15–20bp stress.

## 4. OOS splits are sometimes by symbol, not time

Some studies concatenate symbol-by-symbol then split 75/25 — the "OOS" is the last
~25% of symbols in directory order, not the last 25% of time. Any temporal claim needs
a chronological split.

## 5. Intraday trailing-stop ATR has look-ahead

`gap_go_backtest.py` (trail) and `stock_mr_engine.py` size the trailing stop from the
full day's (or current bar's) ATR, then apply it from the first minute — using future
volatility to set an earlier stop. Trailing results are further biased (and trailing
still LOSES even with the bias, so the "trailing is bad" conclusion is safe).

---

Net: the strategies that still look good *after* honest costs and *despite*
survivorship bias (RSI reversal on large caps, gap-and-go next-open) are the ones worth
forward-testing. The small/mid-cap dip-buy results should be treated with most
skepticism until a point-in-time universe is available.
