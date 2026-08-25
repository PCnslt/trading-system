# 24-Hour / Overnight Session Execution Cost — Measured, Sub-$50 Universe

**Date:** 2026-08-25 · **Sample:** 36 names from `research/smallcap_universe_full.json`
(524-name sub-$50, ADV≥$50M universe) · **Order size modelled:** $250/side (real
per-position size on the ~$700 RH account)

**Verdict: NO-GO on a 20:00–04:00 overnight strategy on measured evidence. The
16:05–20:00 evening session is CONDITIONALLY viable but must clear ≥45 bp
round-trip — 3.2× the regular-hours cost.**

> **REVISION (same session, more data):** pooling **4 clean extended snapshots**
> (09:12–09:28 ET) and **3 clean regular snapshots** (09:31–09:43 ET) instead of
> one of each moves the extended median from 44.9 → **51.1 bp** and the ratio
> from 3.20× → **3.42×**. The regular-hours baseline is **unchanged at 14.0 bp**,
> which is a good stability check. **The number is therefore 51.5 bp, not 45 bp.**
> One snapshot file (`rth_0945.jsonl`) was found to contain rows from *both*
> sessions and has been quarantined as `.MIXED_DO_NOT_USE`; the original headline
> inputs (`premarket_0917`, `rth_0935`) were verified 100% single-session, so the
> first estimate was not contaminated — only under-sampled.

---

## 0. Which source produced which number (read this first)

| Source | Status | What it gave us |
|---|---|---|
| Our L1 depth archive (`s3://…/orderbook/`) | **USELESS for this question** | Only `MES`/`MNQ` futures, and `bot/orderbook_collector.py` is RTH-gated (`_in_rth()`); 23,016 objects, all 09:30–16:00 ET. **Zero equity extended-hours quotes.** |
| IBKR `reqHistoricalData` TRADES, `useRTH=False` | **WORKS** | 5-min bars, 20 days, 36/36 names. Coverage **04:00–20:00 ET only**. Used for the independent volume cross-check. |
| IBKR `whatToShow=BID_ASK` / `MIDPOINT` | **BLOCKED** | `Error 162: No market data permissions for NYSE STK`. No quote-based spread from IBKR on this account. |
| RH `get_equity_historicals bounds=24_7` | **WORKS, with a hard gap** | 5-min bars, 15 days, `session` label + `interpolated` flag + volume. Used for volume split and the evening-fill test. |
| RH `get_equity_quotes` + `get_equity_price_book` (live) | **WORKS — primary spread source** | Real L1 bid/ask + L2 level arrays with sizes, from the venue we actually trade. Basis of every spread number below. |
| Corwin-Schultz high-low estimator | **REJECTED — see §5** | Produced implausible output in *both* directions on this data. Not used for any headline number. |

---

## 1. Effective spread: extended session vs regular hours

Both legs measured identically — the RH L2 book walked to fill **$250 per side**,
effective half-spread vs the prevailing mid, summed into a round trip.
`premarket_0917` = 09:12–09:14 ET (pre session). `rth_0935` = 09:34–09:35 ET.

| Metric ($250/side round trip) | Regular hours | Extended session | Ratio |
|---|---|---|---|
| **Median** | **14.0 bp** | **44.9 bp** | **3.20×** |
| Mean | 14.4 bp | 71.7 bp | 6.05× |
| p75 | 19.4 bp | 77.6 bp | |
| Max | 44.8 bp | 884.6 bp (SIRI, stale quote) | |
| Median excl. worst outlier | — | 44.5 bp | |

Per-symbol detail: `research/overnight_cost_floor.json`. Depth was never the
binding constraint — **all 36 names filled the full $250 on both sides inside the
recorded book levels**, in every session.

**Critical caveat that makes 44.9 bp a FLOOR, not a central estimate:** the
extended sample was taken in the final ~18 minutes before the 09:30 open — the
single most liquid window of the entire extended session. The 16:05–20:00 and
20:00–04:00 windows are structurally thinner, so true evening/overnight cost is
**≥** this number. The `tickflr` column shows the hard penny-grid floor: for a
$2.23 stock (PLUG) one cent alone is 44.7 bp, so sub-$5 names can never be cheap.

## 2. How much actually trades outside regular hours

Two **independent** sources, closely agreeing. Median share of total volume:

| Session (ET) | RH 24_7 (15d) | IBKR (20d) |
|---|---|---|
| overnight 20:00–04:00 | **0.00%** (not reported — see §4) | **no bars exist** |
| pre 04:00–09:30 | 1.02% | 1.62% |
| regular 09:30–16:00 | 88.30% | 87.71% |
| **closing auction 16:00–16:05** | **9.33%** | 7.94% |
| **evening 16:05–20:00** | **0.73%** | 0.88% |

**The closing-auction trap:** the closing cross prints in the 16:00 bar and
accounts for **72–100%** of naive "post-market" volume (CMCSA 100%, SIRI 100%,
PLUG 94%, F 90%, KHC 72%). Bucketing 16:00–20:00 as one block overstates evening
liquidity by ~13×. Any future analysis **must** exclude the 16:00–16:05 bar.

True evening liquidity is thin in absolute terms: median **65.5k shares** and
~36 traded 5-min bars per evening across the sample. Some names are effectively
dead after 16:05 — CMCSA traded **2,047 shares** in the entire 4-hour evening on
2026-08-24; SIRI traded **zero**.

## 3. Would a LIMIT at the closing price fill in the evening?

Test: take the 16:00 regular close, rest a limit there from 16:05, walk the
16:05–20:00 session (RH 24_7 bars, real prints only), 36 names × ~11 sessions.

| Measure | Median across symbols |
|---|---|
| Buy limit at close touched during the evening | **90.9%** of sessions |
| Touched within 30 minutes | **81.8%** |
| Median time to touch | **0 min** (first evening bar) |
| Price concession needed at the 80th percentile | **0.0 bp** |
| Post-fill adverse drift (evening close vs fill) | **−1.1 bp** |

**Interpretation — and why this is weaker than it looks.** The evening range
routinely spans the close, so a limit at the close needs **no** price concession
to be *touched*. But "touched" is necessary, not sufficient: bar-low ≤ limit
ignores queue priority and the fact that RH routes to a single venue, so real
fill rates will be lower. More importantly this is the wrong cost question — a
passive limit resting at the close sits *inside* a ~45 bp spread, so it fills
preferentially when the market is moving against you. The measured −1.1 bp
post-fill drift is the visible tip of that adverse selection. **The binding cost
is the spread (§1), not the concession.**

## 4. The overnight session (20:00–04:00) is NOT measurable today

Across 36 symbols × 15 days, RH's `24_7` series contains **zero** bars with a
real print between 20:00 and 04:00 ET. Bars are emitted for those hours but all
carry `interpolated: true` and `volume: 0`.

**This is an API reporting gap, not an absence of trading.** Diagnostic: the same
query on TSLA, NVDA, AAPL, SPY, AMD, PLTR, INTC, QQQ returns
`overnight_real_prints=0, overnight_vol=0` for **all eight**. TSLA and SPY
unquestionably trade overnight, so the series simply does not report Blue Ocean /
overnight-ATS prints.

Therefore **no overnight spread and no overnight volume number exists** from:
our L1 archive (futures-only, RTH-gated), IBKR historicals (04:00–20:00, and
BID_ASK blocked outright), or RH historicals (gap above).

**What is required to close it — now running.** The only remaining source is the
live quote surface sampled *inside* the session. Deployed this session:
`research/rh_session_spread_cron.py`, cron `rh-session-spread-collector-24x5`
(job `c9ced4daf5de`), **every 15 min, 24/5**, sampling L1 for all **524** universe
names plus a rotating 60-name L2 book slice, session-labelled. Verified live:
`universe=524 quoted=520 two_sided=520 books=60`.
First true evening (16:05–20:00) sample lands **today**; first full overnight
(20:00–04:00) sample **tomorrow ~04:00 ET**. That is what converts the floor
below into a measured central estimate.

## 5. Corwin-Schultz was tried and REJECTED

Implemented per Corwin & Schultz (2012), negative estimates floored at zero,
applied two ways. Both failed sanity checks in opposite directions:

- **Session-level H/L (consecutive days):** median **78.1 bp** for regular hours,
  where the directly measured quoted spread is **12.3 bp**. Over 6.5 hours the
  high-low range is dominated by volatility, not spread — 6× overstated.
- **Consecutive 5-min bars within session:** median **1.4 bp** for the evening,
  where the measured extended quoted spread is **30+ bp**. Thin evening bars have
  high = low = close, so `log(H/L) → 0` and the estimator **collapses to zero** —
  badly understated exactly where we need it most.

CS is unusable on this universe at this horizon. Reported here so it is not
retried. Roll's serial-covariance estimator is also computed in
`overnight_cost_analyze.py` but is undefined (positive autocovariance) for a large
share of thin evening series. **No headline number in this document depends on an
estimator — all spreads are measured quotes.**

## 6. Robinhood 24-hour practical constraints

Verified against `hardening/rh_client.py`, `docs/ROBINHOOD_EXECUTION.md` and RH's
documented behaviour:

| Constraint | Reality |
|---|---|
| Session window | 24-Hour Market **Sun 20:00 → Fri 20:00 ET** |
| Order types (API) | `market`, `limit`, `stop_market`, `stop_limit` |
| `market_hours` arg | `regular_hours` / `extended_hours` / `all_day_hours` |
| **Outside RTH: order type** | **LIMIT ONLY.** Market orders are not accepted in the 24-hour/extended session. |
| **Stop orders outside RTH** | **NOT AVAILABLE.** `place_stop()` hard-codes `market_hours="regular_hours"` — a resting stop is inert until 09:30. |
| Stop granularity | **Whole-share only.** A fractional position cannot carry a broker stop at all. |
| Brackets | **None.** No atomic entry+stop; never-naked is a *code* guarantee, so a crash between entry fill and stop rest leaves a naked window. |
| Fractional | `dollar_amount` on **market orders in regular hours only** → unusable overnight (limit-only). |
| Commission | $0. Statutory sell-side fees: SEC §31 0.28 bp + FINRA TAF 0.09 bp = **0.37 bp** round trip. |

**Protection therefore possible overnight:** a resting **stop-limit is not
available**; the only protection is (a) a passive **take-profit limit** on the
other side, and (b) **position sizing to absorb the full overnight gap
unprotected**. An overnight position on RH is, structurally, an unstopped
position until 09:30. Combined with the whole-share stop rule and the $150
effective order floor, the practical consequence is that overnight risk must be
controlled by size alone.

---

## 7. THE NUMBER

> **A 24-hour/overnight strategy on this universe must overcome a minimum
> round-trip cost of 51.5 bp** (51.1 bp pooled measured effective spread at
> $250/side + 0.37 bp statutory fees), from 4 clean extended snapshots × 36 names.
>
> Regular-hours equivalent: **14.4 bp**. The extended session costs **3.42×** more.
> Excluding the one stale quote (SIRI) the extended median is 50.8 bp — the
> headline does not depend on the outlier.

**Status of this number — stated precisely:**
- It is **measured**, not estimated: real RH L2 books, real sizes, our order size.
- It is a **LOWER BOUND** for the evening/overnight session, because it was
  sampled in the pre-open window — peak extended-hours liquidity.
- It covers **04:00–09:30 and, by extension, 16:05–20:00**. The
  **20:00–04:00 overnight block is still unmeasured** and no number is offered
  for it; the collector now running produces it tomorrow.

**Implication for strategy design:** an overnight edge must clear ~45 bp
round-trip *and* be held unstopped through the gap. At 0.73% of daily volume in
the evening and 3.2× the spread, the burden of proof sits with the signal: it
needs a median edge well north of 45 bp per round trip to survive, which is a far
higher bar than the same signal traded at 14 bp in regular hours.

---

### Reproduce

```bash
./venv/bin/python research/overnight_cost_fetch.py      # IBKR 5-min useRTH=False
./venv/bin/python research/rh_247_fetch.py              # RH bounds=24_7 bars
LABEL=x POLLS=3 SLEEP=40 ./venv/bin/python research/rh_spread_snap.py
./venv/bin/python research/overnight_cost_analyze.py    # volume split + fill test
./venv/bin/python research/rh_book_cost.py <label>      # $250 book walk
./venv/bin/python research/overnight_cost_floor.py      # paired table + the number
```

Artifacts: `overnight_cost_results.json`, `overnight_cost_floor.json`,
`rh_book_cost.json`, `rh_snap_summary_*.json`.
