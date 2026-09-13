# Close-to-next-open overnight hold on Robinhood's 24-hour market — GO/NO-GO

**Verdict: NO-GO.**

The overnight gap is real, stable, and statistically strong (+7.2bp OOS mean, t=21.5,
459,882 trades on the tradeable sub-$50 universe). It is also far too small to pay for
itself. Across 45 variants the **highest round-trip cost at which any variant keeps
PF ≥ 1.3 out-of-sample is 6.09 bp** (and every broad, unconditional variant fails the
PF ≥ 1.3 bar at *zero* cost). The physical floor — crossing a one-cent spread on a
$21.56-median-price stock — is already **4.64 bp**, and a level-2 book walk of a real
$250 Robinhood clip in off-hours costs a **median 44.9 bp round trip**. The cost wall is
breached by roughly 7–10x.

Scripts: `research/overnight_24h_fetch.py` → `overnight_24h_features.py` →
`overnight_24h_edge.py` → `overnight_24h_edge_checks.py` → `overnight_24h_edge_walls.py`
→ `overnight_24h_edge_verdict.py`. All numbers: `research/overnight_24h_edge_results.json`.
No orders placed; read-only research.

---

## What was tested

The trade: **buy at close[t]** in the evening session (Robinhood 24-hour market, limit
orders — no MOC needed), **sell at open[t+1]**. Gross = `1e4 * (open[t+1]/close[t] - 1)`.

* Data: `s3://trading-datalake-920641308584/ibkr/equities/daily/` — 697 of 714 requested
  symbols (522/524 of `research/smallcap_universe_full.json`, 189/190 of the
  `bot/live_equities.py` STOCKS list; `PFSA`, `CLBK`, `BRK-B` have no object).
  2,325,473 symbol-days, 2006-08-21 .. 2026-08-13.
* IS ≤ 2019-12-31, OOS ≥ 2020-01-01.
* **Tradeability gate applied at trade time** (not just today): close in $2–$50 and
  20-day ADV ≥ $20M, so the $700 whole-share account could actually have taken the
  trade. This matters: the *ungated* small-cap panel returns a nonsense IS mean of
  +1810bp, driven by sub-penny pre-history rows (`DBRG` 2017-01-10 at $0.0004 →
  +1.5e9 bp). The gate removes all of it.

### Cost models

| model | what | median on gated small-caps |
|---|---|---|
| `tick1` | cross a 1-cent quoted spread, round trip = 100/price bp — **physical floor** | **4.64 bp** |
| `tick2`/`tick3` | 2/3-cent spread (realistic off-hours) | 9.3 / 13.9 bp |
| `flat` | required stress | 10 / 20 / 30 / 40 (+60/100) bp |
| `cs` | Corwin-Schultz (2012) high-low, per symbol-year, neg 2-day estimates floored at 0 | 62.7 bp |
| `ar` | Abdi-Ranaldo (2017) close-high-low, per symbol-year | 26.9 bp |

**Honest warning on Corwin-Schultz.** It was computed as instructed, per symbol per year,
with the CS overnight-gap adjustment. At 250-observation windows on modern low-spread US
equities it is **not a spread estimate, it is a volatility proxy**: it returns 51.2 bp for
AAPL in 2025, when a one-cent spread on a $232 stock is 0.4 bp and the true effective
spread is ~1 bp (`research/overnight_24h_cs_diag.py`). Abdi-Ranaldo (averaging before the
square root, so no flooring bias) is better behaved but still noisy — it prints 0.0 for
half the symbol-years and 87 bp for AAPL 2025. **Under CS every single variant loses
money, but that result is not decisive** because the estimator is inflated. The decisive
costs are the tick floor and the measured Robinhood book.

---

## Results — gross, and net of every cost model (mean bp per trade)

n = trades; win/PF/mean at trade level; IS | OOS.

| variant | n (IS/OOS) | IS gross mean/med/win/PF | OOS gross mean/med/win/PF | OOS net CS | OOS net AR | OOS net tick1 | OOS net 10/20/30/40 bp | **PF≥1.3 OOS cost wall** |
|---|---|---|---|---|---|---|---|---|
| **1a uncond, sub-$50 gated** | 435,952 / 459,882 | +3.60 / +2.92 / 50.5% / 1.092 | +7.20 / +4.45 / 50.9% / 1.131 (t=21.5) | −77.1, PF 0.29 | −42.7, PF 0.51 | +0.23, PF 1.004 | −2.8 / −12.8 / −22.8 / −32.8 | **0 bp** (fails at zero cost) |
| 1b uncond, sub-$50 ungated | — | corrupt (+1810bp, sub-penny rows) | +10.18 / +3.44 / 50.5% / 1.179 | −85.7 | — | −0.15 | −3.2 / −13.2 / −23.2 / −33.2 | **0 bp** |
| **1c uncond, 189 large-caps** | 473,229 / 302,775 | +3.89 / +3.12 / 51.4% / 1.126 | +5.45 / +5.13 / 52.7% / 1.130 (t=18.6) | −57.1, PF 0.29 | −41.8, PF 0.43 | +3.94, PF 1.092 | −4.6 / −14.6 / −24.6 / −34.6 | **0 bp** |
| **2a RSI(2)<5 & >SMA200, small-cap, overnight leg** | 8,819 / 10,383 | +11.00 / +7.91 / 53.6% / 1.306 | +4.90 / +11.79 / 53.7% / 1.083 (t=2.4) | −79.8, PF 0.28 | −40.0, PF 0.54 | −1.97, PF 0.968 | −5.1 / −15.1 / −25.1 / −35.1 | **0 bp** |
| **2b same, large-cap** | 11,695 / 7,980 | +9.39 / +8.67 / 54.9% / 1.309 | +12.42 / +12.87 / 56.4% / 1.308 (t=6.9) | −47.6, PF 0.36 | −30.5, PF 0.54 | +11.06, PF 1.27 | +2.4 / −7.6 / −17.6 / −27.6 | **0.27 bp** (3.72 excl-COVID) |
| 3a prior-day down, small-cap | 209,304 / 226,576 | +4.80 / +5.40 / 51.7% / 1.120 | +5.47 / +5.54 / 51.3% / 1.096 | −80.0 | −44.8 | −1.56 | −4.5 / −14.5 / −24.5 / −34.5 | **0 bp** |
| 3b prior-day down, large-cap | — / 367,962 | +5.80 / +5.97 / 53.1% / 1.186 | +5.34 / +6.20 / 53.2% / 1.123 | −57.6 | — | +3.80 | −4.7 / −14.7 / −24.7 / −34.7 | **0 bp** |
| 3c small-cap prior day −10% or worse | 1,748 / 4,099 | +76.92 / +52.09 / 58.3% / 1.610 | +55.65 / +58.88 / 57.9% / 1.357 | −87.0, PF 0.62 | −21.3, PF 0.89 | +45.27, PF 1.282 | +45.7 / +35.7 / +25.7 / +15.7 | 7.85 bp → **0 bp excl COVID** |
| 3d large-cap prior day −10% or worse | 905 / 1,101 | +80.95 / +66.29 / 62.6% / 1.849 | +89.68 / +86.50 / 61.9% / 1.843 | −13.1, PF 0.92 | — | +85.17, PF 1.787 | +79.7 / +69.7 / +59.7 / +49.7 | 51.36 bp → **0 bp excl COVID** |
| 4a DOW Mon, small-cap | 82,093 / 86,111 | +4.73 / +3.34 / 50.7% / 1.126 | +14.69 / +4.00 / 50.8% / 1.296 | −69.7 | −35.7 | +7.71, PF 1.145 | +4.7 / −5.3 / −15.3 / −25.3 | **0 bp** |
| 4b DOW Mon, large-cap | — / 56,484 | +4.84 / +3.96 / 52.0% / 1.163 | +14.50 / +5.00 / 52.8% / 1.409 | −48.1 | — | +13.00, PF 1.36 | +4.5 / −5.5 / −15.5 / −25.5 | 3.38 bp → **0 bp excl COVID** |
| 4a DOW Wed, small-cap | — / 184,065 | +3.82 / 0.00 / 49.8% / 1.097 | **−3.98** / 0.00 / 49.6% / 0.936 | −88.3 | — | −10.93 | −14.0 / −24.0 / −34.0 / −44.0 | **0 bp** |
| **4c month-end (last trading day), small-cap** | 20,848 / 21,907 | +13.14 / +13.48 / 56.3% / 1.340 | +14.59 / +10.90 / 53.5% / 1.273 (t=9.8) | −69.9, PF 0.33 | −35.4, PF 0.59 | +7.61, PF 1.134 | +4.6 / −5.4 / −15.4 / −25.4 | 0 bp → **6.09 bp excl COVID (best of all variants)** |
| 4c month-end last 2 days, small-cap | — / 85,996 | +11.06 / +8.95 / 54.0% / 1.302 | +1.52 / 0.00 / 48.6% / 1.027 | −83.1 | — | −5.45 | −8.5 / −18.5 / −28.5 / −38.5 | **0 bp** |
| 4d month-end (last day), large-cap | — / 14,400 | +12.50 / +15.07 / 58.5% / 1.405 | +10.39 / +11.67 / 55.4% / 1.260 | — | — | +8.88, PF 1.218 | +0.4 / −9.6 / −19.6 / −29.6 | 0 bp → **5.95 bp excl COVID** |
| 5b (data-mined) small-cap prior day <−3% AND Mon/Tue | 12,796 / 20,538 | +24.44 / +24.81 / 56.8% / 1.404 | +31.09 / +20.87 / 55.1% / 1.459 (t=15.6) | −84.7, PF 0.38 | −30.7, PF 0.71 | +22.25, PF 1.31 | +21.1 / +11.1 / +1.1 / −8.9 | 9.47 bp → **1.56 bp excl COVID** |
| 5c (data-mined) large-cap Monday + prior-day down | — / 25,885 | +6.34 / +6.53 / 53.6% / 1.205 | +17.12 / +7.97 / 54.4% / 1.498 | — | — | +15.58, PF 1.444 | +7.1 / −2.9 / −12.9 / −22.9 | 5.97 bp → **0.40 bp excl COVID** |

Full 45-variant table (incl. every prior-day-move bucket, all five weekdays on both
universes, and month-end last-1/2/3) is in the JSON under `variants`.

### Cost walls, the decisive table

`wall` = max flat round-trip bp at which PF(gross − cost) ≥ 1.3 on OOS trades.

| | wall incl COVID | **wall excl COVID (2020-02-20..04-30)** |
|---|---|---|
| best variant of all 45 | 51.36 bp (large-cap prior-day ≤ −10%, n_oos=1,101) | **6.09 bp** (small-cap month-end last day, n_oos=21,270) |
| every unconditional variant | 0 bp | 0 bp |
| the deployed dip signal | 0 bp small-cap / 0.27 bp large-cap | 0 bp / 3.72 bp |

The two big-looking walls are **COVID artifacts**. 33.9% of the large-cap "prior day
≤ −10%" OOS trades sit in Feb–Apr 2020; strip that window and the variant collapses from
+89.68 bp / PF 1.843 to **+8.30 bp / PF 1.069** — a 51 bp wall becomes 0 bp. Same story
small-cap: +55.65 → +24.65 bp, PF 1.357 → 1.167.

---

## Answers to the four specific questions

**(1) Unconditional, 524-name sub-$50 universe vs the 189 large-caps.** The sub-$50
universe has the *bigger* gross gap (+7.20 vs +5.45 bp OOS) but a 3x higher cost floor
(4.64 vs 1.58 bp per tick), so net of the tick floor the large-caps win (+3.94 vs
+0.23 bp) — and neither is remotely near PF 1.3. Both fail the PF ≥ 1.3 bar at zero cost.
This is the core problem: the universe the $700 account can trade is exactly the universe
where the gap does not survive the spread.

**(2) Conditional on the deployed RSI(2)<5 & close>SMA200 signal — does evening entry
beat the next open?** No, not on the names we trade. The paired close-entry-minus-open-entry
advantage is **+4.12 bp OOS on the gated small-caps (t=1.97, median +11.83, 54% positive)**
and **+11.98 bp on large-caps (t=6.55, 56% positive)**, essentially identical at H=1,2,3,5
(as it must be — it is the same overnight gap). Switching the entry does *not* add a round
trip; it moves the buy from the RTH open auction into an off-hours session. It therefore
only pays if the **extra buy-side** cost is under +4.1 bp (small-cap) / +12.0 bp
(large-cap). Measured off-hours half-spread on a $250 clip is ~22 bp (44.9 bp round trip
median). **The switch is value-destroying on the small-caps and marginal-at-best on
large-caps the account can't size properly.** Keep the deployed next-open entry.
Note also the signal's own overnight leg decayed IS→OOS on small-caps (+11.00 → +4.90 bp)
while holding on large-caps (+9.39 → +12.42 bp).

**(3) Conditional on prior-day down move / size.** No usable monotonicity. Small-cap
buckets: −0..1% +4.96, −1..2% +6.05, −2..3% +7.48, −3..5% **+2.59**, −5..10% **−3.62**,
≤−10% +55.65 bp OOS. Large-cap: +5.04, +6.22, +6.46, **−2.87**, +3.63, +89.68 bp. The
signal is *not* "bigger drop = bigger bounce"; it is flat-to-negative through the
−3% to −10% region and everything sits in the ≤−10% tail, which is COVID-driven and
carries the widest spreads (CS median 131 bp, tick floor 7.4 bp) precisely because those
are catastrophic-news names.

**(4) Day-of-week and month-end.** Real but small and IS/OOS-unstable. Monday and Tuesday
are the good entry days (small-cap OOS +14.69 / +13.95 bp), **Wednesday is negative**
(−3.98 bp OOS, PF 0.936; large-cap −0.90 bp). But the Monday effect is mostly an OOS
phenomenon (small-cap IS +4.73 → OOS +14.69) and 2020-heavy — excl COVID the Monday
large-cap wall drops 3.38 → 0 bp. Month-end is the most IS/OOS-consistent effect found:
**last trading day of the month, small-cap, IS +13.14 bp PF 1.340 / OOS +14.59 bp
PF 1.273**, and it is the single best variant on the excl-COVID cost wall (6.09 bp). But
the last *two* days is much worse than the last *one* (OOS +1.52 bp, PF 1.027), the
year-by-year OOS path is erratic (−7, +112, +30, +2, +29, −25, −13 bp), it fires on only
79 distinct OOS days, and 6.09 bp is still below any realistic off-hours cost.

### Portfolio realism (≤3 whole-share positions per night, biggest prior-day losers)

| | nights | OOS gross/night | OOS net tick1 | OOS net flat 20 bp | wall |
|---|---|---|---|---|---|
| sub-$50 gated, top-3 losers | 5,005 | +21.37 bp, PF 1.25 (~+54%/yr gross) | +10.99 bp, PF 1.122 | +1.37 bp, PF 1.015 | 0 bp |
| large-caps, top-3 losers | 5,006 | +4.84 bp, PF 1.084 (~+12%/yr) | +1.49 bp, PF 1.025 | −15.16 bp, PF 0.775 | 0 bp |

Concentrating into 3 names per night lifts the gross to a headline-grabbing ~54%/yr and
still never reaches PF 1.3 — and at the measured ~45 bp real cost it is deeply negative.

---

## The cost wall that kills it

1. **PF ≥ 1.3 OOS is unreachable above 6.09 bp round trip for any of the 45 variants**
   (excl COVID), and unreachable at *any* cost — including zero — for every unconditional
   variant and for the deployed dip signal on small-caps. At the trade level the per-trade
   noise (std 193 bp on the gated small-cap gap) simply dwarfs a +5 to +30 bp edge.
2. On the softer "positive mean net" criterion, break-even round-trip cost is
   **+7.20 bp** (unconditional small-cap), **+5.45 bp** (large-cap), **+4.90 bp**
   (dip signal small-cap), **+14.59 bp** (month-end), **+31.09 bp** (the data-mined
   prior-day-<−3%-Mon/Tue combo).
3. Real costs beat all of those:
   * **4.64 bp** — physical floor, one-cent spread at the $21.56 median price. Unavoidable.
   * **44.9 / 47.2 bp** — median round trip for a **$250 Robinhood clip** walked through
     the actual level-2 book in off-hours (36 names, `research/rh_book_cost.json`,
     produced independently in this repo). Range 4.6–884.6 bp; only 13.9% of names come in
     under 10 bp. Median quoted spread 30–41 bp.
   * **Liquidity is worse than the spread suggests**: over 2026-08-10..08-25 the true
     24-hour window (20:00–04:00 ET) printed **zero volume in all 36 sampled names**, and
     the 16:00–20:00 evening session carried a median **0.73%** of the day's volume with a
     median 5-minute bar range of 7.5 bp (`research/overnight_cost_results.json`).
     So "buy at the close price in the evening session" is not a thing you can do at scale
     even for $233 — you are a price-taker in a 0.7%-of-volume book.

Gross edge +5 to +15 bp vs a 4.6 bp floor and a ~45 bp realistic cost. **NO-GO.**

---

## What would change the answer

* A cost regime under ~5 bp round trip: i.e. RTH-hours execution on names priced ≥ $40
  with 1-cent spreads, not off-hours limit orders on $5–20 names. That is a different
  broker/venue problem, not a signal problem.
* Selling the overnight gap as *overlay* on positions you already hold (no extra round
  trip): the deployed dip signal already holds through the overnight, so it already
  collects this. Nothing to add.
* If a real off-hours fill at ≤ 5 bp is ever demonstrated on the actual account, the
  month-end-last-day small-cap variant (6.09 bp wall, IS PF 1.340 / OOS PF 1.273) is the
  one to revisit — 12 trades a year, not a strategy.

## Caveats (all of these make the numbers above optimistic, not pessimistic)

1. **Universe look-ahead.** Both universes are screened on *today's* price/ADV and applied
   back 20y. Names that died are absent. The $2–50 / ADV ≥ $20M trade-time gate removes the
   worst of it but not survivorship.
2. **Close-entry is optimistic.** It assumes a fill at the 16:00 print after observing that
   print. In reality the evening session opens after the close and the gap starts pricing
   in immediately. Sensitivity is in the JSON (`gap_capture_haircut_oos_mean_bp`): at 50%
   capture the unconditional small-cap edge is +3.60 bp, below its own 4.64 bp tick floor.
3. **Split-adjusted, not dividend-adjusted** → ex-div drops sit inside the measured gap,
   so the raw gap is a slight *under*-estimate. Immaterial at this magnitude.
4. **Overlapping per-signal pooling**, not a position-capped portfolio (except section 6).
5. **Fat tails are real events, not bugs**: the largest surviving gated gaps are
   AMC 2021-01-26 (+30,968 bp), ZG 2015-08-14 (+22,725), GME 2021-01-26 (+13,982).
   Winsorising 1/99% moves the unconditional small-cap mean only +5.45 → +5.02 bp, so the
   conclusion is not tail-driven.
6. **CS/AR spread estimators are unreliable here** (see above). They are reported because
   they were requested; the tick floor and the measured book are what the verdict rests on.
7. The Robinhood 24-hour market supports **limit orders only** and covers a subset of
   names; whether all 522 sub-$50 names are even eligible was not verified.
8. Data ends 2026-08-13 (backfill lag) → OOS ≈ 6.6 years.
