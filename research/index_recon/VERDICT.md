# Index Reconstitution Drift (S&P 500 adds) — Backtest Verdict

**Date:** 2026-09-09
**Verdict:** EVIDENCE OF NO EDGE (long-only "buy the S&P 500 add" drift)

## Data provenance (all free, actual fetches)

- **Event list:** Wikipedia "Historical components of the S&P 500"
  (`en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500`).
  405 index changes, 386 ADDED names, effective dates **1976-07-01 → 2026-08-18**.
  - **Announcement dates:** extracted from the S&P press-release URLs cited in the
    table's References column (both `press.spglobal.com/YYYY-MM-DD-…` and
    `spglobal.com/…/announcements/YYYYMMDD-…`). **150 adds have an exact announcement
    date**, concentrated in **2019-2026** (pre-2019 coverage is sparse — see gap note).
    Median announcement→effective gap = **7 calendar days** (≈5 trading days);
    a second cluster at ~17 days (quarterly-rebalance announcements).
- **Price data:** yfinance (Yahoo Finance) daily **dividend+split-adjusted** closes,
  SPY as the market benchmark, 1998-2026. **304/378 tickers resolved**; 74 failed
  (Yahoo purges delisted/acquired symbols).
  - Missing 2019+ adds (survivorship note): **FRC, SBNY** (both failed banks — their
    exclusion makes the measured drift *less* negative than truth), **CDAY/DAY, CTLT, SATS**.
  - S3 datalake (`ibkr/equities/daily/*.parquet`) is a sub-$50 universe and contains
    **none** of the S&P 500 adds — not usable here.

## Method (per `trading-backtest-validation` skill)

- Market-adjusted (vs SPY, same trading-day window, close-to-close), **net of 6bp round-trip**.
- Date-clustered t-stat (Cameron-Gelbach-Miller cluster-robust SE by event date).
- Chronological OOS (last 30% of events by date).
- Era split pre/post-2015.

## Results (all market-adjusted, net 6bp)

### The entire "add drift" is the announcement GAP — untradeable
- Announcement pop (ann-day close → next-day close, 1 day): **+273bp, t=+5.79 (clust +5.52)**.
  S&P announces after the close; this jump is the overnight/next-day reaction.

### TRADEABLE pre-add drift (buy next-day close → effective date)
- **+4.1bp, t=+0.07** (n=137). Essentially **zero** — the "pre-add drift" in the papers
  is the announcement gap; nothing remains once you buy after the pop.

### TRADEABLE post-announcement drift (buy next-day close → +H days)
| H | n | mean | t | t_clust | PF |
|---|---|---|---|---|---|
| +5 | 141 | **−117bp** | −2.07 | — | 0.60 |
| +10 | 141 | **−142bp** | −1.89 | — | 0.64 |
| +20 | 140 | **−168bp** | −1.81 | — | 0.66 |

### Post-effective drift (buy at effective-date close → +H days, full 2000-2026)
| H | n | mean | t | t_clust | PF |
|---|---|---|---|---|---|
| +5 | 304 | **−101bp** | −3.35 | −3.08 | 0.56 |
| +10 | 304 | **−145bp** | −3.52 | −3.40 | 0.55 |
| +20 | 302 | **−163bp** | −3.13 | −2.96 | 0.61 |

### Era split (post-effective +20d, net 6bp) — negative in BOTH eras
- pre-2015 (n=82): −186bp (t=−2.17) · post-2015 (n=220): −154bp (t=−2.41)
- So this is **not a post-2015-only decay** — the tradeable long side is dead across the whole sample.

### Chronological OOS (last 30% by date)
- next-close +5/+10/+20d: **−121 / −15 / −188bp** (t −0.11..−1.25) — negative.
- eff-close +5/+10/+20d (2021-2026): **−71 / −174 / −185bp** (t −1.12 / **−2.11** / −1.58) — negative.

### Concentration check (post-effective +20d)
- Negative drift is **broad-based, not a few bad names**: the top-10 names by P&L are all
  POSITIVE winners (COHR, TSLA, ETSY, MRNA, …); the −163bp mean comes from the wide field
  of ~290 remaining events. (Opposite of a concentration artifact — makes the negative
  result *more* robust.)

## Interpretation

The only positive number is the **announcement-day-close entry (+156bp @ +5d)**, and that
entry is **physically impossible**: the announcement comes after the close, so you cannot
buy at the pre-announcement close. Decomposed into its parts:
1. **+273bp** overnight/next-day pop (the reaction — unpurchasable long-only after the fact).
2. **~0bp** residual pre-add drift (index-fund buying is fully front-run/priced in by the time
   you can trade).
3. **−100 to −168bp** post-add reversal over the following 5-20 days (arbitrageurs unwind the
   inclusion pop; added names are also prior outperformers that mean-revert).

This matches the post-2000 decay of the S&P inclusion premium (Chen-Norville-Pfeffer 2002 /
Wurgler-Zhuravskaya 2002 documented the 1990s peak; the effect has been arbitraged down since).
The surviving feature is a **pop-then-fade**, which is only harvestable by *shorting* the add
post-pop — not the long-only form requested.

## Acceptance bar vs result
Required: OOS PF > 1.2 net @ 6bp AND date-clustered t-stat. Every tradeable form fails:
PF 0.55-0.66, negative t-stats. **No long-only variant passes.**

## Files
- `research/index_recon/fetch_data.py` — yfinance fetcher + cache
- `research/index_recon/backtest.py` — Test 1-5 (announcement/effective/OOS/era)
- `research/index_recon/backtest2.py` — pop, tradeable pre-add, concentration, by-year
- `research/index_recon/backtest3.py` — tradeable-entry OOS + era split
- `research/index_recon/cache/*.parquet` — 304 ticker series + SPY
- `research/index_recon/events.json` — 405 changes (386 adds) w/ eff + ann dates
