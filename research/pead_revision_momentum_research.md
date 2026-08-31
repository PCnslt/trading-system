# PEAD + Estimate-Revision Momentum — "Predict Future Gainers" Edge Research

Research date: 2026-08-30. Subagent deliverable for the US-equities long-only system.
All numbers below were read from fetched text (jina / OpenAlex / EconPapers / Wikipedia
API / API probes); nothing is reconstructed from memory. Where a magnitude could NOT be
re-extracted, it is explicitly marked.

## TL;DR

- PEAD (earnings-surprise drift) and estimate-revision momentum are the two established
  families that predict cross-sectional winners **before** price momentum catches up —
  exactly the "predict future gainers before they hit a gainers list" edge requested.
- Both are **low-turnover** (event-driven / quarterly / monthly rebalance), so the ~6–12 bp
  round-trip cost is a non-issue relative to the gross spreads (4.2%/60d, ~7.5%/6mo).
  The real risks are (1) post-publication decay (esp. large caps), (2) long-only beta
  contamination, and (3) the short leg — already shown weak in `research/pead_backtest.py`.
- **Data availability is asymmetric**: the surprise-side (PEAD) is fully backtestable TODAY
  on free keys. The revision-side (analyst estimate revisions) is NOT available free
  point-in-time — it must be DIY-polled from FMP over weeks, or proxied by the surprise.

---

## Data availability — verified endpoint-by-endpoint (free keys)

### AlphaVantage (free tier)
| Need | Endpoint | Status | Verified |
|---|---|---|---|
| Quarterly surprise history (actual vs consensus, `surprise`, `surprisePercentage`, `reportTime`) | `function=EARNINGS` | ✅ WORKS | 122 quarters for AAPL (back to 2013) |
| Upcoming earnings dates + consensus est | `function=EARNINGS_CALENDAR` | ✅ WORKS | returned CSV (symbol, reportDate, fiscalDateEnding, estimate, timeOfTheDay) |
| Analyst estimate revisions | — | ❌ none | AV has no analyst-estimate/revision endpoint |
| Upgrade/downgrade events | — | ❌ none | — |

`EARNINGS` is the key one: `estimatedEPS` is the **analyst consensus**, and
`surprisePercentage` = (reported−estimated)/estimated. That is exactly the
**analyst-forecast surprise** (Livnat–Mendenhall 2006), which produces a *stronger* drift
than time-series SUE. Full surprise history is free.

### FMP /financialmodelingprep.com (free tier)
| Need | Endpoint | Status | Verified |
|---|---|---|---|
| Forward consensus EPS (epsAvg/epsHigh/epsLow, numAnalystsEps) | `stable/analyst-estimates?period=annual` | ✅ WORKS | AAPL returned FY2028–2030 estimates |
| Same, quarterly | `stable/analyst-estimates?period=quarter` | ❌ PREMIUM | "Premium Query Parameter" |
| Upcoming earnings + `epsEstimated` | `stable/earnings-calendar` | ✅ WORKS | ADBE/DOCU/NIO with dates + estimates |
| Historical surprise table | `stable/earnings-surprises` | ❌ empty `[]` (paid) | — |
| Rating changes | `stable/upgrades-downgrades` | ❌ empty `[]` (paid) | — |
| Price targets | `stable/price-target` | ❌ empty `[]` (paid) | — |
| Recommendation history | `stable/analyst-stock-recommendations` | ❌ empty `[]` (paid) | — |

**Conclusion for estimate revisions:** the free tier exposes the **current** consensus
snapshot (FMP `analyst-estimates`, annual) but NOT the point-in-time revision history, and
NOT discrete upgrade/downgrade events. To build a revision-momentum signal you must
**poll `analyst-estimates` daily/weekly and diff `epsAvg` yourself** — usable forward, not
backtestable on historical revisions. The surprise-side (AV EARNINGS) IS backtestable now.

Note: the repo already pulls surprise data via Robinhood MCP (`pead_backtest.py`) and has an
earnings calendar; FMP `earnings-calendar` + AV `EARNINGS_CALENDAR` add upcoming-date +
consensus-est coverage.

---

## Signals (8, ranked by testability-now + evidence)

### 1. SUE decile drift — the canonical PEAD  [DATA: AVAILABLE]
- **Rule (Bernard–Thomas 1989):** expected EPS = seasonal random walk (same quarter last
  year + trend). SUE = (actual − expected) / σ(prior quarterly surprises, ≥10 quarters).
  Rank universe by SUE at announcement; buy the top decile **at the close of the
  announcement day**; hold ~60 trading days (re-entry works at ~20d for the 1–20d fit,
  since ~half the drift is after day 10). Use **lagged** (prior-quarter) decile cutoffs to
  avoid lookahead.
- **Magnitude (text-verified):** top − bottom SUE decile ≈ **4.2% over 60 trading days**
  (top +2.0–3.0%, bottom −1.5–2.5%); ~half of the drift accrues **after day 10**; spread
  positive in **41 of 48 quarters** 1974–85, incl. 11/16 down quarters.
- **Net of cost:** ~4.2%/quarter gross ≈ trivial vs 6–12 bp round trip; Sadka (2006)
  replication cites **~8.76% annualised post-cost** as the modern lower bound (via Katz
  replication). Long-only top-decile ≈ +2–3% per quarter, but this **inherits beta** —
  benchmark against the unconditional post-earnings drift (the repo's own backtest already
  flags that beaters ≈ unconditional drift, so alpha is small on liquid large caps).
- **Source:** Bernard & Thomas (1989), *J. Accounting Research* 27(Suppl):1–36,
  DOI 10.2307/2491062. https://doi.org/10.2307/2491062 ; https://www.jstor.org/stable/2491062
  (method + rules also in Gow's open textbook: https://iangow.github.io/far_book/pead.html)
- **Data:** AV `EARNINGS` quarterly history → compute SUE; prices from S3 daily bars.

### 2. Analyst-surprise drift (continuous SUE, not binary beat)  [DATA: AVAILABLE]
- **Rule (Livnat–Mendenhall 2006):** use **analyst-consensus forecast error** instead of a
  time-series model: surprise = actual − consensus (AV `surprise` / `surprisePercentage`),
  standardised cross-sectionally. Rank; buy top surprise names at announcement close; hold
  20–60d.
- **Magnitude:** the analyst-based surprise produces a **stronger** drift than time-series
  SUE ("the market's failure to fully incorporate analyst consensus is a key driver").
- **Net of cost:** same low-turnover profile; the upgrade over signal #1 is in *strength*,
  not cost.
- **This is the untested upgrade to the repo's existing `pead_backtest.py`**, which used a
  binary beat/miss split. Test the **continuous** `surprisePercentage` rank, top-K long-only.
- **Source:** Livnat & Mendenhall (2006), *J. Accounting Research* 44(1):177–205,
  DOI 10.1111/j.1475-679X.2006.00196.x. https://doi.org/10.1111/j.1475-679X.2006.00196.x
- **Data:** AV `EARNINGS` (`estimatedEPS`, `surprise`, `surprisePercentage`) — free, 122 qtrs.

### 3. Seasonal drift — hold through the NEXT announcement  [DATA: AVAILABLE]
- **Rule (Bernard–Thomas 1990):** don't exit on a flat 20–60d timer; the drift is
  concentrated around the **subsequent quarterly announcements**. Hold the beater position
  into the next scheduled report (exit in the 3-day window after it).
- **Magnitude (text-verified):** **~25–30% of PEAD occurs in the 3-day windows around the
  subsequent earnings announcements**, which are only ~5% of trading days.
- **Net of cost:** fewer round trips than a fixed timer → strictly cheaper; concentrates the
  edge into a known calendar event.
- **Source:** Bernard & Thomas (1990), *J. Accounting & Economics* 13(2–3):305–340
  (via Wikipedia PEAD summary). https://en.wikipedia.org/wiki/Post%E2%80%93earnings-announcement_drift
- **Data:** upcoming earnings dates via FMP `earnings-calendar` / AV `EARNINGS_CALENDAR`.

### 4. Attention-conditioned PEAD (Friday / crowded-day drift is LARGER)  [DATA: AVAILABLE]
- **Rule (Hirshleifer–Lim–Teoh 2009; DellaVigna–Pollet 2009):** take PEAD entries only when
  the announcement day is attention-poor — **Friday announcements**, or days with many
  simultaneous announcements / high announcement-day volume. Underreaction (and thus the
  drift) is larger there.
- **Magnitude:** drift is larger and more prolonged on high-volume announcement days and on
  Fridays (investor inattention). (Direction verified; exact bp NOT-EXTRACTED — paywalled.)
- **Net of cost:** a *filter* on signals #1–2; improves per-trade edge, no extra cost.
- **Source:** Hirshleifer, Lim & Teoh (2009), *J. Finance* 64(5):2289–2325,
  DOI 10.1111/j.1540-6261.2009.01501.x ; DellaVigna & Pollet (2009),
  *J. Finance* 64(2):709–749. https://doi.org/10.1111/j.1540-6261.2009.01501.x
- **Data:** AV `reportTime` + `reportedDate` (Friday detection), daily bars (volume).

### 5. Earnings momentum = SUE + past-return combo  [DATA: AVAILABLE]
- **Rule (Chan–Jegadeesh–Lakonishok 1996):** rank on **both** past 6-month price return AND
  SUE (each predicts drift after controlling for the other); buy the joint high/high names.
  This is the "predict winners in advance" edge — it overlaps but is distinct from the
  system's already-validated 20-day price STM.
- **Magnitude (verified mechanism; decile bp NOT-EXTRACTED — paywalled):** "Past return and
  past earnings surprise each predict large drifts … after controlling for the other."
  Widely-reported CJL figures: SUE decile ≈ **7.5% / 6 months**, combined price+earnings
  momentum ≈ **8.8% / 6 months** (mark as secondary, not re-extracted).
- **Net of cost:** ~7.5%/6mo gross ≫ 6–12 bp; long-only top-decile ≈ half the long-short
  spread; beta must be stripped (compare to the 20-day STM already validated, OOS PF 1.55 —
  the earnings component may be the *incremental* alpha over pure price momentum).
- **Source:** Chan, Jegadeesh & Lakonishok (1996), *J. Finance* 51(5):1681–1713,
  DOI 10.1111/j.1540-6261.1996.tb05222.x. https://doi.org/10.1111/j.1540-6261.1996.tb05222.x
  (NBER WP: https://www.nber.org/papers/w5375)
- **Data:** AV `EARNINGS` (SUE) + S3 daily bars (past return).

### 6. Consensus-revision momentum (the pure "estimate revision" factor)  [DATA: PARTIAL/DIY]
- **Rule (Chan–Jegadeesh–Lakonishok 1996 revisions leg; Gleason–Lee 2003):** rank by the
  **change in consensus forward EPS over the last 1–3 months** (and/or number of analysts
  raising vs lowering); buy upward-revision names, hold ~1–3 months. "High-innovation"
  revisions (deviating from consensus) drift more than consensus-hugging ones.
- **Magnitude:** post-revision drift confirmed; "a substantial portion of the delayed price
  adjustment occurs around subsequent earnings-announcement and forecast-revision dates"
  (Gleason–Lee 2003 abstract, verified). Exact long-short bp: NOT-EXTRACTED (paywalled).
- **Net of cost:** monthly/quarterly turnover → costs trivial.
- **Data:** ❌ NOT free point-in-time. Free tier gives current consensus only
  (FMP `analyst-estimates`, annual). Build a revision series by **polling daily and diffing
  `epsAvg`** — forward-usable in weeks, NOT historically backtestable. AV has nothing.
- **Source:** Gleason & Lee (2003), *The Accounting Review* 78(1):193–228,
  DOI 10.2308/accr.2003.78.1.193. https://doi.org/10.2308/accr.2003.78.1.193
- **Data:** FMP `analyst-estimates` (poll-and-diff). Proxy-now: use AV `EARNINGS`
  estimatedEPS revisions quarter-over-quarter as a coarse revision signal.

### 7. Earnings-announcement premium / expected-announcer  [DATA: AVAILABLE — already banked]
- **Rule (Frazzini–Lamont 2007):** long a stock **into** its scheduled announcement (~2 weeks
  before → 2 weeks after), long-only.
- **Magnitude:** announcing stocks earn **+60 bp in announcement month**, expected-announcer
  strategy **+72 bp/month** (1973–2004); long-short 61 bp/month (t>5), Sharpe 0.94.
- **Net of cost:** 1 round trip/name/quarter → survives 6 bp easily.
- **Status:** ALREADY RESEARCHED in `research/NEW_SHORT_HORIZON_EDGES.md` #2 — listed for
  completeness, do not re-queue. Needs exact earnings dates (now covered by FMP
  `earnings-calendar` / AV `EARNINGS_CALENDAR`).
- **Source:** Lamont & Frazzini (2007), NBER WP 13090. https://www.nber.org/papers/w13090

### 8. Recommendation-change drift (upgrades/downgrades)  [DATA: NOT AVAILABLE free]
- **Rule (Jegadeesh–Kim–Krische–Lee 2004):** buy analyst upgrades, sell downgrades; drift
  persists for months after the change.
- **Data:** FMP `upgrades-downgrades` returns `[]` on the free key (paid). ✗ Cannot backtest
  or run live without an upgrade. Skip unless the FMP key is upgraded.
- **Source:** Jegadeesh, Kim, Krische & Lee (2004), *J. Finance* 59(3):1083–1124.
  https://doi.org/10.1111/j.1540-6261.2004.00657.x

---

## Cost / turnover verdict (the number that decides survival)

Every surviving candidate here is event- or monthly-driven, i.e. **≤ a few round trips per
name per quarter**. At ~6–12 bp round trip that is ~0.1–0.2% of notional per name per
quarter against gross spreads of 2–7% — **cost is not the binding constraint** (unlike the
rejected same-day/intraday family). The binding constraints are instead:

1. **Post-publication decay** — PEAD has shrunk since 1989, mostly in large caps
   (Chordia–Subrahmanyam–Tong 2014); it persists in **small, less-followed names**. Bias
   the universe toward small caps / low analyst coverage, which is also where the small
   whole-share account trades.
2. **Long-only beta contamination** — "buy beaters" ≈ unconditional post-earnings drift on
   liquid names (already shown in `pead_backtest.py`). Every long-only PEAD/revision
   candidate must be reported as **alpha vs an equal-weight benchmark / vs the 20-day STM**,
   not raw bucket PF.
3. **Short-leg weakness** — the repo's own PEAD test found the miss-short leg does not drift
   (missers bounce). So the market-neutral PEAD spread is weaker than the paper headline;
   the LONG beaters leg + the attention/seasonal conditioners are the extractable part.
4. **Point-in-time data gap** — the revision factor (#6/#8) cannot be honestly backtested on
   free data; only the surprise family (#1–5, #7) can.

## Recommended backtest order (feeds `trading-edge-validation`)

1. #2 analyst-surprise continuous rank (top-K long-only, 20d + 60d, IS/OOS, alpha vs
   benchmark) — direct upgrade of the existing `pead_backtest.py`.
2. #4 attention filter (Friday / crowded-day) as a conditioner on #2.
3. #3 seasonal exit (hold-through-next-announcement) vs flat timer.
4. #5 earnings+price momentum combo vs the already-validated 20-day STM (is the earnings
   leg incremental alpha?).
5. #6 DIY revision series — start polling FMP `analyst-estimates` daily NOW (build history),
   paper-test, do not backtest-claim it.

## Sources (URLs)
- Bernard & Thomas (1989): https://doi.org/10.2307/2491062 · https://www.jstor.org/stable/2491062
- Gow PEAD chapter (method/rules): https://iangow.github.io/far_book/pead.html
- Wikipedia PEAD (seasonal-drift, OR-surprise): https://en.wikipedia.org/wiki/Post%E2%80%93earnings-announcement_drift
- Livnat & Mendenhall (2006): https://doi.org/10.1111/j.1475-679X.2006.00196.x
- Hirshleifer, Lim & Teoh (2009): https://doi.org/10.1111/j.1540-6261.2009.01501.x
- Ng, Rusticus & Verdi (2008, cost caveat): https://doi.org/10.1111/j.1475-679X.2008.00290.x
- Chan, Jegadeesh & Lakonishok (1996): https://doi.org/10.1111/j.1540-6261.1996.tb05222.x · https://www.nber.org/papers/w5375
- Gleason & Lee (2003): https://doi.org/10.2308/accr.2003.78.1.193
- Jegadeesh, Kim, Krische & Lee (2004): https://doi.org/10.1111/j.1540-6261.2004.00657.x
- Lamont & Frazzini (2007): https://www.nber.org/papers/w13090
- Ball & Brown (1968): https://doi.org/10.2307/2490232
- Secondary summaries used for cross-check: https://tryvantage.co/insights/paper-trail-bernard-thomas-pead · https://quantdecoded.com/en/post-earnings-announcement-drift
