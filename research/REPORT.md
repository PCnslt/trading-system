# Option Order Flow → Directional Single Long Call/Put? (Six-Layer Verification)

Date: 2026-08-31. Method: primary-source retrieval (Crossref, OpenAlex, Semantic
Scholar, arXiv, RePEc, NBER full text, Unpaywall). All paywalled magnitudes flagged
NOT-EXTRACTED.

## DOIs (all verified against Crossref)

| Paper | Venue | DOI | Full text status |
|---|---|---|---|
| Pan & Poteshman (2006), "The Information in Option Volume for Future Stock Prices" | RFS 19(3):871–908 | `10.1093/rfs/hhj024` | paywalled; READ the NBER working-paper full text `10.3386/w10925` (2004) |
| Ge, Lin & Pearson (2016), "Why does the option to stock volume ratio predict stock returns?" | JFE 120(3):601–622 | `10.1016/j.jfineco.2015.08.019` | paywalled; verbatim abstract via SSRN `10.2139/ssrn.2329714` + RePEc |
| Dubach (Jan 2026), "Option Order Flow and Short-Horizon Return Predictability: Evidence from U.S. Equity ETF Options" | — | **NOT FOUND** | see §4 |

## 1. Pan & Poteshman (2006) — what the primary source actually says

Signal = **open-buy put/call ratio** = (buyer-initiated-to-OPEN put volume) /
(put + call volume), from CBOE proprietary 16-category data (4 trade types × 4
investor classes), 1990–2001.

Verified headline numbers (NBER WP full text):
- "stocks with low put-call ratios outperform stocks with high put-call ratios by
  more than 40 basis points on the next day and more than 1% over the next week"
  (risk-adjusted).
- Regression slope −53 bp (t = −32.92).
- Quintile long-short: low-quintile +15.7 bp vs high-quintile −26.6 bp = **42 bp/day**
  spread, t = 28.55, Sharpe 0.52.
- First five days sum to >1%; decays exponentially, ≈0 after 3 weeks; **no reversal**
  (→ information, not price pressure).
- Leverage gradient (Table 7, slope on P/C ratio, bp [t]): >10% OTM −44.67 [−29.57];
  3–10% OTM −21.15 [−16.71]; NTM −11.74 [−8.43]; 3–10% ITM −2.71 [−1.85];
  **>10% ITM +7.95 [3.52] (wrong sign)**. Short-dated <30d −34.83 vs >179d −6.91.
- **Signal is NON-PUBLIC.** "…we use the Lee and Ready (1991) algorithm to back out
  buyer-initiated … volume from publicly observable … records. We find that the
  resulting publicly observable option signals are able to predict stock returns for
  only the next 1 or 2 trade days. Moreover, the stock prices subsequently reverse…
  In a bivariate analysis … there is no predictability at all from the public signal."
  "…the economic source of our main result is valuable private information in the
  option volume…"
- Full-service-broker (hedge-fund) flow is the strongest predictor; firm proprietary
  traders "contain no information at all."
- **The strategy tested is a STOCK long-short portfolio, not an option position.**

## 2. Ge, Lin & Pearson (2016) — primary-source abstract (verbatim)

"We find no evidence that trades related to synthetic short positions in the
underlying stocks contain more information than trades related to synthetic long
positions. **Purchases of calls that open new positions are the strongest predictor
of returns**, followed by call sales that close out existing purchased call positions.
Overall, our results indicate that the role of options in providing **embedded
leverage** is the most important channel why option trading predicts stock returns."

- Again a STOCK-return predictability study; option volume is the signal.
- Magnitudes (bp of open-buy-call predictability, decile spreads, cost numbers):
  **NOT-EXTRACTED (paywalled; no OA copy).**

## 3. Six-layer test (the directional single-long-call/put claim)

1. **Phenomenon** — CONFIRMED in-sample (option open-buy flow → stock direction,
   t ≈ 30). But it is a *stock-return* phenomenon, not an *option-return* one.
2. **Long-short portfolio** — CONFIRMED (42 bp/day stock L/S, t = 28.55). Requires
   shorting the bearish leg (violates the Level-2 long-only constraint). Long leg
   alone = +15.7 bp/day.
3. **Long leg alone** — PARTIAL / one-sided. CALL side: open-buy call volume is the
   single strongest predictor (Ge-Lin-Pearson), and low P/C (call-heavy) long leg
   earns +15.7 bp (Pan-Poteshman). PUT side: explicitly NOT informative ("no evidence
   … synthetic shorts … more information"). So a *long-call* rule has support; a
   *long-put* rule does NOT.
4. **Single contract** — NOT TESTED. Both papers are diversified stock-portfolio
   studies. The "deep-OTM is strongest" result is a portfolio-average leverage
   gradient, not evidence that any single name's call can be selected profitably.
5. **Retail $700** — NOT ADDRESSED. Headline magnitude is stock bp, not option
   premium P&L. A +15.7 bp single-day stock move is a small fraction of a deep-OTM
   option's relative bid-ask spread and roughly one day's theta. No paper computes
   option-level return net of premium.
6. **Net execution after bid-ask** — NOT ADDRESSED. Neither paper models option
   bid-ask, theta, or commissions. Pan-Poteshman do not discuss transaction costs
   at all (the 42 bp/day spread is an institutional cross-sectional trade).

**Direction vs volatility:** DIRECTIONAL, not volatility/straddle. The signal is
call-vs-put buyer-initiated direction → stock direction, via Black (1975)'s leverage
channel. It is NOT a vol-mispricing result. BUT the directional signal is (i)
concentrated in NON-PUBLIC data and (ii) ASYMMETRIC (bullish call-buy works, bearish
put-buy does not).

## 4. Dubach (Jan 2026) — NOT LOCATABLE (critical flag)

"Option Order Flow and Short-Horizon Return Predictability: Evidence from U.S. Equity
ETF Options" (Dubach, Jan 2026) was NOT found in any indexed source:
- OpenAlex exact `title.search` → **0 results**; OpenAlex/Crosref/Semantic-Scholar
  author "Dubach" → no such paper.
- arXiv, Bing, Brave, DuckDuckGo, Google Scholar, SSRN (via Crossref SSRN indexing) →
  nothing.
- The only quantitative-finance "Dubach" is **Philipp D. Dubach**, whose complete
  Crossref/SSRN list (Polymarket microstructure, MPT, consumer panels, gambling
  fairness, Hacker News, glycemic modeling — 10 works) contains **no** option-order-flow
  or ETF-return-predictability paper.

→ The cited paper and its attributed findings are UNVERIFIABLE / appear fabricated or
mis-attributed. All its numbers — 56 predictors; OTM call/put volume ratio, IV skew,
IV-skew change surviving Harvey-Liu-Zhu multiple testing; SPY OOS 2024–25 directional
accuracy ≈59.7%; 56% / 22% / 0.3% informed / put-call-parity / VRP decomposition —
are **NOT-EXTRACTED (no primary source exists)**.

## 5. Decay / cost-fragility verdict

- **Post-publication decay:** the *publicly-observable* signal reverses after 1–2 days
  (Pan-Poteshman, primary source) — i.e., anything a retail trader can see is already
  decayed/absent. The strong (40 bp) signal requires proprietary CBOE open-buy +
  investor-class data, so there is no public implementation to have decayed; it was
  never public. Citation counts: Pan-Poteshman 909, Ge-Lin-Pearson 222 (OpenAlex) —
  heavily studied, but **no located replication demonstrating a cost-surviving
  single-long-call/put edge**.
- **Magnitude vs single-contract frictions:** the long-leg effect is ~15.7 bp/day on
  the *stock*. Mapped to a deep-OTM long call, that is far below the option's
  bid-ask + one day of theta on a single contract. 40 bp next-day is the *hedged
  spread*, not the long-leg, and it is stock-denominated.

**Bottom line:** Option order flow IS directional (call/put selectable, leverage
channel — not volatility). But it fails the ladder as a tradeable single long
call/put: the directional content lives in non-public data; it is one-sided (calls
only); it is demonstrated only at the stock-portfolio level; and the long-leg
magnitude (~15.7 bp stock) is too small to survive option bid-ask + theta at retail
size. **NOT verified as a cost-surviving Level-2 long-call/put edge.**
