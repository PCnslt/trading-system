# Pre-Registered Test — Option Order Imbalance → Next-Day Direction

**Frozen before first forward observation (2026-09-01). Do not modify after results begin.**

## Primary hypothesis
Abnormally POSITIVE option order imbalance (OOI) during the FINAL 30 minutes (15:30–16:00 ET) predicts POSITIVE next-day stock returns, conditional on high option liquidity and low stock liquidity. Bearish equivalent (negative OOI → negative next-day return) tested symmetrically.

## Definitions (frozen)
- **Universe:** SPY, QQQ, IWM + top-10 liquid single stocks (NVDA, AAPL, MSFT, AMZN, META, TSLA, AMD, GOOGL, NFLX, AVGO).
- **Option liquidity gate:** minimum 100 contracts/day total volume; else exclude.
- **Stock liquidity gate:** median daily dollar volume > $500M.
- **OOI (IBKR proxy, labeled `IBKR_PROXY_OOI`):** `(buy_vol − sell_vol) / (buy_vol + sell_vol)` where buy/sell is inferred from trade price vs contemporaneous mid (trade ≥ mid+1tick = buy; ≤ mid−1tick = sell). Explicitly NOT signed aggressor-side data. `TRUE_OOI` is unavailable from IBKR and is never asserted.
- **Window:** 15:30–16:00 ET each trading day.
- **Horizons tested:** next-day open, next-day close, +30m, +60m, close-to-close.
- **Cost assumption (for any option leg):** entry = ask, exit = bid (Robinhood executable). Midpoint never used for a "pass."
- **Minimum sample:** 120 qualifying observations before any conclusion.
- **Split:** first 60% train / next 20% validation / final 20% untouched OOS.
- **Significance:** t > 2.0 on OOS AND sign survives a ±1-day entry perturbation.
- **Placebo:** (a) shuffle OOI across days, (b) use midday (12:00–12:30) OOI instead of close. If placebos match the signal, kill it.

## Kill criteria (pre-registered)
1. OOI does not predict next-day return OOS.
2. Effect disappears after excluding top-decile borrow-cost / hard-to-borrow names.
3. Effect is fully subsumed by the underlying's own close-to-close return.
4. Placebo (midday OOI) is as strong as close OOI.
5. Proxy OOI fails but cannot be distinguished from no-signal (i.e., we can't conclude TRUE_OOI would work).

## Status
PENDING — first observation 2026-09-01. No data inspected yet.
