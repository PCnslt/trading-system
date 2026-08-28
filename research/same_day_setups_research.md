# Same-Day (flat-by-close) Practitioner Setups — Evidence Audit

Researched for a **$700 long-only fractional-share** account (Robinhood-class venue, whole-share
buys, sub-$50 names, ~$105/position, **~6 bp round trip regular hours**, 1-min + daily bars).
Cost yardstick throughout: **6 bp = 0.06% round trip on notional**. Task: same-day setups with a
*documented positive expectancy* from practitioner books/papers, each with exact rule + source +
net expectancy + implementability, weak claims flagged.

**The single most important cross-cutting finding:** almost every *documented* same-day edge is a
**single-digit-basis-points-per-day** phenomenon (2.7–8 bp/day gross). At this venue's ~6 bp round
trip, a flat-by-close trade that costs 6 bp needs ~6 bp of gross edge **just to break even**, and
most of the famous same-day edges gross between 2.7 and 8 bp/day. The setups that survive are the
ones with (a) *conditional* triggers (not "always on"), (b) *one* round trip/day max, and (c)
long-only legs on sub-$50 names. Index-level and futures-level edges (MIM, VWAP, noise-area ORB)
are real but do **not** reach a $700 long-only fractional account.

---

## TIER 1 — real net-of-cost evidence, long-only extractable, flat by close

### 1. Bollinger-band intraday mean reversion — Ernie Chan, *Quantitative Trading* Ex. 3.8
- **Rule:** SP1500 universe. At the open auction, **buy** stocks at/below their lower Bollinger band
  (sell/short at/above upper). **Exit all at the close** (flat by close).
- **Source:** Chan, E. *Quantitative Trading* (2009) Ex. 3.8; restated at
  http://epchan.blogspot.com/2008/12/enduring-profitability-of-mean.html
- **Net expectancy:** Sharpe **4.8 gross → 3.5 net at 10 bp round trip**, out-of-sample on 2008 data.
- **Turnover:** 1 round trip/day/name. Long-only extraction: buy the below-lower-band names only.
- **$700 fit:** YES on the long leg (sub-$50 names, flat by close). **Caveats Chan himself flags:**
  survivorship bias (delistings) and 2008 being unusually favorable — treat Sharpe 3.5 as an upper bound.
- **Evidence quality:** STRONG (published book + author's own caveats), but survivorship-unadjusted.

### 2. Overnight-gap mean reversion (Buy-on-Gap) — Ernie Chan, *Algorithmic Trading* Ex. 4.1
- **Rule:** SPX universe. At the **open**, buy the 10 biggest **down-gaps** vs prior close; **exit at
  the close** (flat by close). QuantConnect coding = buy the 09:31 bar when open < yesterday's low.
- **Source:** Chan, E. *Algorithmic Trading* (2013) Ex. 4.1; coded version
  https://www.quantconnect.com/forum/discussion/598/buy-on-gap-strategy-logic/
- **Net expectancy:** NOT cleanly stated in the free text. Chan's own "Beware of Low Frequency Data"
  post shows 1-min-bar backtests **overstate** live fills for exactly this open-auction reversal
  (order-book "flip-flops" / mini flash crashes): http://epchan.blogspot.com/2015/04/beware-of-low-frequency-data.html
- **$700 fit:** YES mechanically (buy 09:31, sell ~15:50, long-only, sub-$50). **But** edge is
  unquantified net → use as a cheap baseline, not a conviction lane.
- **Evidence quality:** MODERATE — exact rule documented, net expectancy not; execution caveat first-party.

### 3. Connors RSI(2) — the **0-day-hold (same-day) variant** — Connors & Alvarez family
- **Rule:** Long when price > 200-day SMA **and RSI(2) < 5**; the canonical entry is the signal close,
  but the re-tester moved it to the **next open** (you need the close to confirm indicators), and the
  **best time-based variant was a 0-day hold: buy at the open, exit the same day's close** — roughly on
  par with the original.
- **Source:** independent re-test of Connors RSI(2), S&P 500, 1990–2024:
  https://www.reddit.com/r/algotrading/comments/1fm5lfj/backtest_results_for_connors_rsi2_strategy/
  (original code link 404 — verified). Vendor cross-number for the family: avg **+0.9%/trade**, ~9%/yr,
  maxDD 34%: https://www.quantifiedstrategies.com/rsi-2-strategy/
- **Net expectancy:** family ≈ **+0.5–0.9%/trade gross**, win 70–80%; the 0-day variant "roughly on par"
  — **no fees modeled, index-tested** → net expectancy NOT-EXTRACTED for the same-day leg.
- **$700 fit:** YES (daily-bar computable, long-only, no stops). Re-run on sub-$50 names — the index
  figure does **not** transfer.
- **Evidence quality:** MODERATE — exact rule + direction documented, but same-day net expectancy unquantified.

### 4. VWAP 2σ reversion with high-volume filter — in-house validated sleeve (practitioner staple)
- **Rule:** Session-cumulative VWAP on RTH 5-min bars; `z = (close − VWAP)/σ(close−VWAP)`. Enter LONG
  when `z < −2.0` **only when volume ≥ 1.0× the 20-bar mean** (fade genuine high-participation
  extensions, not thin drift); exit on VWAP reversion or **2×ATR hard stop**; **flatten at EOD**.
- **Source:** in-house validation, `research/LANE10_VWAP_SLEEVE.md` + `research/LANE10_VWAP_SWEEP.md`
  (trading-system repo). Practitioner lineage: VWAP reversion is a standard prop-desk mean-reversion
  entry (no single citable book; this is the *only* version here with our own measured OOS numbers).
- **Net expectancy:** OOS profit factor **1.11–1.38 @ 1 tick** on equity-index futures (MES/MNQ),
  stable across VWAP_K ∈ {1.5–2.5}. Cross-asset (metals 0.94 / energy 0.97) = NO-GO — index-only.
- **$700 fit:** **NO on this venue** — needs futures (MES/MNQ) or an index ETF; sub-$50 single-name
  VWAP reversion is **not** what was validated. Flag as futures-only.
- **Evidence quality:** STRONG for the futures sleeve (own OOS, honest-fill); not portable to $700 equities.

### 5. Market intraday momentum (first half-hour → last half-hour) — Gao–Han–Li–Zhou / Baltussen
- **Rule:** Signal = return **prev close → 10:00 ET** (Gao et al.) or **prev close → 15:30** (Baltussen
  "r_ROD" upgrade). If positive, **long the last half-hour (15:30–16:00), flat at the close**.
- **Source:** Gao, Han, Li & Zhou 2018, *JFE* 129(2):394–414, DOI 10.1016/j.jfineco.2018.05.009;
  Baltussen, Da, Lammers & Terhorst 2021, *JFE* 142(1):377–403, DOI 10.1016/j.jfineco.2021.04.029
  (OA: academicweb.nd.edu/~zda/intramom.pdf). Practitioner coverage:
  https://alphaarchitect.com/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/
- **Net expectancy:** r_ROD **6.86%/yr, SR 1.73** (equity-index futures, 1974–2020, gross). **Gamma gate**
  (the real edge): when dealer net gamma < 0, β_ROD 6.63 (t=4.78, R² 3.58%); when ≥ 0, β 0.82 (t=1.03,
  R² 0.05%, insignificant). **Cost math: 6.86%/yr ≈ 2.7 bp/day gross → survives on MES/ES at ~1 tick,
  DIES on SPY at 6 bp.**
- **$700 fit:** **NO** — index-level; 2.7 bp/day gross is below the 6 bp round trip; no sub-$50 proxy.
- **Evidence quality:** STRONG (two JFE papers + regime gate), but a futures-only edge; unusable here.

### 6. Noise-area intraday breakout — Zarattini–Aziz–Barbon 2024, independently replicated
- **Rule:** ES/NQ futures. "Noise Area" = prior intraday range. **Long** on a break above the upper
  boundary, **short** on a break below; **exit at the close** or on re-entry into the Noise Area;
  trailing stop at Noise-Area/VWAP. Vol-target 2–3%/day.
- **Source:** Zarattini, Aziz & Barbon 2024, SSRN 4824172; **independent replication with realistic
  fees**: https://www.quantitativo.com/p/intraday-momentum-for-es-and-nq
- **Net expectancy (replicated, net of realistic fees):** ES **8.1%/yr SR 0.91** (paper rules) →
  **16.8% SR 1.25** (90-day/3%/8×); NQ **24.3% SR 1.67**; portfolio **22.4% SR 1.57, maxDD 15%**.
- **$700 fit:** **NO** — futures + short leg + vol-targeting. Signal-library value only.
- **Evidence quality:** STRONG (paper + independent net-of-fee replication) — the best *documented*
  same-day momentum edge, but futures-only.

---

## TIER 2 — positive expectancy *claimed*, but weak / venue-blocked — flag before testing

### 7. Opening-range breakout on "Stocks in Play" — Zarattini–Barbon–Aziz 2024
- **Rule:** 5-min ORB (buy stop above / sell stop below the 09:30–09:35 range) applied only to the
  **top-20 "Stocks in Play"** (high relative-volume names, mostly news/earnings-driven). Exit at close.
- **Source:** Swiss Finance Institute Research Paper 24-98; abstract https://ideas.repec.org/p/chf/rpseri/rp2498.html ;
  summary https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/
- **Claimed expectancy:** **Sharpe 2.81**, total net >1,600% (2016–2023), "even after considering
  transaction costs." **The "Stocks in Play" filter — the entire claimed contribution — is NOT
  quantitatively defined in any reachable free text (NOT-EXTRACTED).**
- **$700 fit:** **NO** — 20 simultaneous intraday stop-markets, shorts, sub-$105 sizing that can't
  express 1%-risk. Also: after-hours-fill contamination and **divergent community replications**
  (C# Sharpe 2.396 vs Python port **−0.148** — ATR warmed on the wrong timeframe).
- **Evidence quality:** WEAK — headline spectacular, core filter undefined, replication divergence.

### 8. Crabel Opening Range Breakout (Stretch / NR7) — the canonical ORB text
- **Rule:** Stretch = 2 × 10-day avg Noise, Noise[i] = min(H−O, O−L). Buy-stop at Open + Stretch,
  sell-stop at Open − Stretch, placed at 09:30; first stop touched = position, other = protective stop.
  Qualifying setups: NR7 (narrowest range in 7 days) / NR4 (narrowest 2-day range in 20).
- **Source:** Crabel, T. (1990) *Day Trading With Short Term Price Patterns and Opening Range
  Breakout* (Wyckoff rationale p.167). Specs: https://oxfordstrat.com/trading-strategies/nr7/
- **Net expectancy:** **NOT-EXTRACTED** (chart-only contour images). Crabel's **own 2026 admission**:
  "the primary session open no longer carries the same significance… that effect has been diluted," a
  "gradual decline in both dollars per contract and Sharpe ratio over time":
  https://tobycrabel.substack.com/p/the-evolution-of-the-opening-range
- **$700 fit:** NO — stop-and-reverse needs intraday path + futures. **Evidence quality:** WEAK/decayed.

### 9. End-of-day cross-sectional reversal — Baltussen–Soebhag–Da (unpublished WP)
- **Rule:** Rank by intraday return (prev close → **15:00**); **long intraday losers / short winners**;
  **enter 15:30, exit 16:00** (the deliberate 30-min gap kills the bid-ask bounce).
- **Source:** Baltussen, Soebhag & Da, WP (EFMA 2024), academicweb.nd.edu/~zda/EOD.pdf
- **Net expectancy:** VW spread **3.78 bp/day (t=10.69) ≈ 9.5%/yr**; EW 6.38 bp/day (t=17.30). **Fails
  at 6 bp**: daily long/short = 2 round trips ≈ 12 bp vs 3.78 bp gross. Authors concede costs likely
  kill it. **Adopt as an EXECUTION rule (buy intraday losers at 15:30, not 15:00), not a lane.**
- **$700 fit:** NO as a lane (cross-sectional L/S). Long-only leg is marginal. **Evidence quality:**
  STRONG magnitude, NEGATIVE net — the honest verdict.

### 10. Gap-fade — the "gaps fill" trade — mostly folklore, one conditional survivor
- **Claim:** buy a gap-down at the open, sell when the gap "fills." **Refuted base rates:** on E-mini S&P
  futures 25y, fill rate **inversely scales with gap size** — 81% for tiny gaps (unexploitable after
  cost), **33% for >0.5σ, 0% for >1.5σ**; "the big gaps continue, they don't revert."
  https://www.reddit.com/r/algotrading/comments/1spd5nf/... and
  https://www.quantifiedstrategies.com/gap-trading-strategies/ (vendor's own "what worked nicely before
  doesn't work nearly as well anymore").
- **The one *documented* profitable gap setup** is **not** same-day: Quantitativo "Mind the Gap" — gap-down
  on a name above its 200-day SMA, buy the open, **exit the NEXT open** (22.9%/yr net of 10 bp, 2010–2024,
  Sharpe 1.66, 55.6% win): https://www.quantitativo.com/p/mind-the-gap
- **Same-day academic variant:** Berkman, Koch, Tuttle & Zhang 2012 (*JFQA* 47(4):715–741) — retail
  attention pushes prices up at the open, which then **reverse intraday** — but all magnitudes
  NOT-EXTRACTED, and the finding is primarily "**don't buy at the open**," not a standalone profitable
  long/short. DOI 10.1017/S0022109012000270.
- **$700 fit:** the same-day versions are NOT tradeable (folklore / cost-negative / index-only). The
  overnight Mind-the-Gap is the honest gap candidate. **Evidence quality:** the *folklore* is disproven;
  the *survivor* is overnight, not flat-by-close.

---

## Named-but-no-documented-expectancy (honest flags)

### 11. Al Brooks — price action (5-min bars, discretionary)
- **What it is:** a discretionary reading system (bars, patterns, always-in direction, measured moves),
  not a ruleset with a published backtest. **No documented win-rate / PF / net expectancy exists** — and
  the author's own material is explicit that results are trader-dependent:
  https://www.brookstradingcourse.com/futures-market/should-i-take-this-trade/ ("a 60% win rate would
  increase profit per trade to 1.6 points" — a discretionary worked example, not a documented edge).
- **Verdict:** NOT implementable as a systematic same-day lane on a $700 account; there is no net
  expectancy to test. Use only as a discretionary "don't buy the open" / context overlay.

### 12. Kevin Davey — *Building Winning Algorithmic Trading Systems*
- **What it is:** a **methodology** book (walk-forward / out-of-sample / Monte Carlo discipline), not a
  catalogue of same-day setups. Davey's published strategies are **futures multi-day swing systems**, and
  his live strategies are proprietary (unpublished). https://kjtradingsystems.com/
- **Verdict:** no extractable same-day equity setup with a documented expectancy. Its value here is
  **process** (honest OOS testing), which is exactly the discipline the rest of this list requires.

---

## Bottom line for the operator (ranked by "testable same-day on $700 long-only fractional")

| Rank | Setup | Flat by close | Net evidence | $700 long-only fit | Action |
|---|---|---|---|---|---|
| 1 | Chan Bollinger intraday MR (#1) | yes | Sharpe 3.5 @10bp (survivorship-biased) | YES | backtest long-leg on sub-$50 |
| 2 | Chan Buy-on-Gap (#2) | yes | unquantified net, flip-flop caveat | YES | cheap baseline only |
| 3 | Connors RSI(2) 0-day hold (#3) | yes | unquantified net (no fees) | YES | re-test on sub-$50 names |
| 4 | EOD reversal long-leg @15:30 (#9) | yes | NEGATIVE net (cost-killed) | execution rule | use as entry-timing rule |
| 5 | VWAP 2σ sleeve (#4) | yes | OOS PF 1.11–1.38 @1t | NO (futures) | keep futures-only |
| 6 | MIM r_ROD (#5) | yes | 2.7bp/day gross → dies @6bp | NO (index) | futures-only, gamma-gated |
| 7 | Noise-area ORB (#6) | yes | 8–24%/yr net (replicated) | NO (futures+short) | signal library |
| 8 | "Stocks in Play" ORB (#7) | yes | claimed SR 2.81, filter undefined | NO | skip until filter defined |
| 9 | Crabel ORB (#8) | yes | NOT-EXTRACTED, decayed | NO | skip |
| 10 | Gap-fade (#10) | yes | disproven as folklore | NO | skip; Mind-the-Gap is overnight |

**Net message:** the *only* same-day setups with a documented positive expectancy that are even
*mechanically* reachable on a $700 long-only fractional account are the three Chan/Connors mean-reversion
entries (#1–#3), and **none of them has a clean, cost-adjusted net number on sub-$50 names** — that is
precisely the gap the operator's due-diligence backtest must fill. Everything with a *strong* net number
(MIM, noise-area ORB, VWAP, EOD reversal) is futures- or index-level and dies at 6 bp or requires
shorts. Assume decay is the base case (every living author above — Chan, Crabel, Alvarez, Quantitativo —
says the same thing).

*All citations are URLs fetched/verified in the trading-system research bank (2026-08). Book page numbers
for Connors/Alvarez and Crabel are NOT-EXTRACTED (archive.org full-text returns numFound:0 for these
titles; no pirated copies used). Chart-only stats are marked NOT-EXTRACTED.*
