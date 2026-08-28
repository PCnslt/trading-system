# NEW short-horizon edges — LONG-only, cost-survivable, ≠ RSI/Stoch/Broken-Arrow family

Researched 2026-08-27. Primary sources verified against OpenAlex + author-hosted PDFs +
NBER. Every number below was read as TEXT (full PDF or abstract), not estimated. Prior work
already banked intraday momentum (Gao/Baltussen), overnight drift, turn-of-month, FOMC drift,
macro-announcement premium, dealer-gamma gate, ORB, weekly reversal, RVOL, VPIN/CVD — see the
"ALREADY DONE" section at the end so nothing is re-researched.

Cost model reminder (from prior measured work): ~5.9 bp round trip regular hours, ~6 bp assumed
here. Ranking puts TURNOVER STRUCTURE (round trips per unit time) before gross bps, because cost
scales with round trips. "Acceleration" as a named short-horizon factor has no clean primary
academic source — closest items are #12 (practitioner, monthly) and the banked ROD upgrade.

---

## 1. Pre-holiday drift  — SESSION ANOMALY  (best cost-survivability in this list)
- **Rule:** long the broad market (SPY/QQQ — or the long side of the strategy universe) on the
  **last trading day before each market-closed holiday**; sell the next session. ~8 event-days/yr.
  No oscillator, no short, both legs RTH.
- **Source:** Robert A. Ariel 1990, "High Stock Returns before Holidays", *Journal of Finance*
  45(5):1611–1626. https://doi.org/10.1111/j.1540-6261.1990.tb03731.x
- **Magnitude (text-verified from abstract):** pre-holiday days average **9–14×** the mean return
  of all other days; **>1/3 of the entire 1963–1982 market return accrued on the 8 pre-holiday
  trading days/yr**; high returns spread throughout the day (not just the close).
- **Corroboration:** Lakonishok & Smidt 1988, "Are Seasonal Anomalies Real? A Ninety-Year
  Perspective", *RFS* 1(4):403–425 (90y DJIA) — persistent holiday effect alongside
  turn-of-week/month/year. https://doi.org/10.1093/rfs/1.4.403
- **Cost:** ~8 round trips/yr ⇒ trivially survives 6 bp. **SURVIVES.**
- **Flags:** none — long-only, index/ETF, no L2/options. Only caveat: effect has weakened vs the
  1963–1982 sample (Ariel's own 1983–86 post-test still positive but smaller) — re-measure on
  1990–2026 before sizing.

## 2. Earnings-announcement premium  — EVENT + VOLUME  (momentum family, NOT reversion)
- **Rule:** long a stock **into its scheduled earnings announcement** (Frazzini–Lamont hold
  ~2 weeks before → 2 weeks after the expected date; a 3-day window around the date misses most of
  the premium — there is pre-event run-up AND post-event drift). Long-only; no short needed.
- **Source:** Lamont & Frazzini 2007, "The Earnings Announcement Premium and Trading Volume",
  NBER WP 13090. https://www.nber.org/papers/w13090 (PDF: https://www.nber.org/system/files/working_papers/w13090/w13090.pdf)
- **Magnitude (text-verified from PDF):** announcing stocks earn **+60 bp in announcement month
  (month 0)**; expected-announcer strategy **+72 bp** (1973–2004); long-short **61 bp/month
  (~7%/yr, t>5)**; annual **Sharpe 0.94** (beats momentum's 0.70 over same window). Premium is
  strongly tied to the **announcement-period volume surge** — high past-announcement-volume stocks
  earn the highest premium (small-investor attention buying).
- **Cost:** 1 round trip per name per quarter ⇒ **SURVIVES** easily (60–72 bp gross vs ~6 bp).
- **Flags:** needs **exact earnings dates** (prior research already flagged this as a data gap);
  the long-short 61 bp is gross — but the LONG leg alone carries the premium, so long-only is the
  right extraction. Not an oscillator; distinct mechanism (attention + volume).

## 3. High-volume return premium  — VOLUME / CONTINUATION  (NOTE: already queued as "RVOL")
- **Rule:** buy stocks with **unusually high recent volume** (top decile of volume vs trailing
  ~50-day norm, or a large 1-day volume shock); hold **~1–20 days** (effect front-loaded).
- **Source:** Gervais, Kaniel & Mingelgrin 2001, "The High-Volume Return Premium", *Journal of
  Finance* 56(3):877–919. https://doi.org/10.1111/0022-1082.00349
- **Magnitude (previously text-verified in prior pass, DOI re-confirmed now):** high-minus-low
  volume portfolio ~**+0.45% (small) / +0.29% (large) over 20 days**.
- **Cross-country replication (NEW citation):** Kaniel, Ozoguz & Starks 2011, "The high volume
  return premium: Cross-country evidence", *JFE* 103(2). https://doi.org/10.1016/j.jfineco.2011.08.012
- **Cost:** 1 round trip per ~10 days ⇒ **SURVIVES**.
- **Flags:** ALREADY-QUEUED (this is the #1 RVOL backtest in `short_horizon_signals_report.md`) —
  list for completeness, don't re-queue. Momentum family (continuation), NOT reversion.

## 4. Volume × return interaction → continuation vs reversal  — VOLUME (momentum family)
- **Rule (paper's exact model):** regress R_t on R_{t−1} and on V_{t−1}·R_{t−1}. When the
  volume-interaction coefficient **C2 > 0** the stock's returns are **speculative/informed ⇒ a move
  on high volume CONTINUES**; when **C2 < 0** they are **hedging-driven ⇒ the move REVERSES**.
  Testable translation (flagged as a translation, not the paper's words): in high-C2 (high
  informed-trading) names, a high-volume directional day is a **momentum entry**; in low-C2 names
  it is a fade.
- **Source:** Llorente, Michaely, Saar & Wang 2002, "Dynamic Volume-Return Relation of Individual
  Stocks", *Review of Financial Studies* 15(4):1005–1047. https://doi.org/10.1093/rfs/15.4.1005
- **Magnitude:** cross-sectional variation in the volume–autocorrelation relation is monotone with
  the extent of informed trading (sign verified from abstract; per-stock C2 magnitudes are
  paywalled → **NOT-EXTRACTED** beyond the sign/mechanism).
- **Cost:** daily/weekly rebalance ⇒ **MARGINAL** — treat as a stock-selection filter on #3/#7,
  not a standalone lane.
- **Flags:** momentum/continuation family (opposite of RSI); needs per-stock C2 estimation from
  history. No short, no L2, no options.

## 5. Order imbalance → market returns  — ORDER-FLOW (approximable on 1-min bars)
- **Rule:** daily **dollar order imbalance** (buy-initiated − sell-initiated, value-weighted,
  market-wide) is **positively related to contemporaneous AND next-day market returns**; after a
  **large down day (R_{t−1} < −1%) combined with high negative imbalance**, the market
  **reverses up** with magnitude predictable from imbalance + return level. Long-only use: market
  timing overlay (buy after high-negative-imbalance / big-down days; the reversal corr is −0.304).
- **Source:** Chordia, Roll & Subrahmanyam 2002, "Order imbalance, liquidity, and market returns",
  *Journal of Financial Economics* 65(1):111–130. https://doi.org/10.1016/S0304-405X(02)00136-8
  (author PDF: https://www.anderson.ucla.edu/documents/areas/fac/finance/28-00.pdf)
- **Magnitude (text-verified from author PDF):** corr(R_t, R_{t−1} | R_{t−1}<−1%) = **−0.304
  (p<0.0001)**; corr(R_t, R_{t−1} | R_{t−1}<−0.1%) = −0.126 (p<0.0001); up-market continuation
  corr = +0.067 (p=0.02). Daily OIB autocorrelation at lag 1 = **0.465** (persistent).
- **Cost:** daily signal on SPY ⇒ ~1 round trip per event ⇒ **SURVIVES** as an index overlay.
- **Flags:** paper needs TAQ signed dollar flow; on the new 1-min bars approximate imbalance via
  bar-direction ("up-bar volume − down-bar volume", close-vs-open sign). Reversal leg overlaps
  dip-buying → **partially DUPLICATE-adjacent**, but the *order-imbalance predictive channel* is
  genuinely new.

## 6. Volume lead-lag (high-volume stocks lead)  — VOLUME
- **Rule:** daily/weekly returns of **high-volume portfolios lead low-volume portfolios**, holding
  size fixed (low-volume names respond to market info more slowly). Long-only extraction: the
  **high-volume leg is the fast leg** — buy high-volume names on a market move (they move first);
  the full high-minus-low spread needs the short leg.
- **Source:** Chordia & Swaminathan 2000, "Trading Volume and Cross-Autocorrelations in Stock
  Returns", *Journal of Finance* 55(2):913–935. https://doi.org/10.1111/0022-1082.00231
- **Magnitude:** lead-lag significant daily and weekly, controlling for size (sign verified from
  abstract; portfolio-spread bps **NOT-EXTRACTED** — paywalled).
- **Cost:** weekly ⇒ **SURVIVES** if used as a universe/timing tilt; full strategy is L/S.
- **Flags:** full spread **needs shorting**; long-only leg is a momentum/timing tilt, not a
  standalone number. Distinct mechanism (speed-of-adjustment), not reversion.

## 7. Volume-enhanced intraday momentum (1-min bars)  — VOLUME × INTRADAY MOMENTUM
- **Rule:** Gao-style intraday momentum (morning/open return predicts the **final half-hour**
  direction) is **sharply stronger conditioned on HIGH opening volume + HIGH information
  uncertainty** — directional accuracy **63.04%** under that joint condition (XGBoost OOS
  **71.43%**).
- **Source:** (open access) 2026, "Enhancing Intraday Momentum Prediction: The Role of
  Volume-Based Information Uncertainty in the Chinese Stock Market", *Int. J. Financial Studies*
  14(2):47. https://www.mdpi.com/2227-7072/14/2/47
- **Magnitude:** accuracy figures above (text-verified). Volume-based uncertainty (IVU) ranks among
  the top predictors.
- **Cost:** 1 round trip/day on the last half-hour ⇒ **MARGINAL at 6 bp** unless the 63–71%
  directional edge is confirmed on US names.
- **Flags:** **China data + ML** — needs US replication on the new 1-min bars; direction-only
  accuracy is not a P&L number. Same intraday-momentum *base* as banked Gao/Baltussen, but the
  **volume-conditioning is the new, unbanked part**.

## 8. VPIN flow toxicity (1-min volume clock)  — ORDER-FLOW
- **Rule:** build VPIN in **volume time** (fixed-volume buckets) from 1-min bars using **bulk
  volume classification** (buy/sell); when VPIN CDF > ~0.8, order flow is **toxic** (informed,
  adverse-selecting market makers) ⇒ predicts **short-term toxicity-induced volatility** / market
  stress (the 2010 flash-crash detector).
- **Source:** Easley, López de Prado & O'Hara 2012, "Flow Toxicity and Liquidity in a
  High-frequency World", *Review of Financial Studies* 25(5):1457–1493. https://doi.org/10.1093/rfs/hhs053
- **Magnitude:** VPIN is a useful indicator of short-term toxicity-induced volatility (sign from
  abstract; threshold levels are in paywalled exhibits → **NOT-EXTRACTED**).
- **Cost:** intraday/frequent ⇒ **dies as a directional signal at 6 bp**; use as a **risk-on/off
  or regime filter**, not a trade.
- **Flags:** needs buy/sell classification (approximable from 1-min OHLCV); contested (Andersen &
  Bondarenko 2014 critique — VPIN recovers only under specific assumptions). Directional use weak.

## 9. Net individual-investor buying predicts returns  — ORDER-FLOW (retail)
- **Rule:** individuals buy after monthly declines and sell after rises; **stocks with intense net
  individual-investor BUYING earn positive excess returns over the next month** (and negative after
  intense selling). Long-only: buy the net-bought names.
- **Source:** Kaniel, Saar & Titman 2008, "Individual Investor Trading and Stock Returns",
  *Journal of Finance* 63(1):273–309. https://doi.org/10.1111/j.1540-6261.2008.01316.x
- **Magnitude:** positive (negative) next-month excess returns after intense buying (selling),
  distinct from past-return and volume effects (sign verified from abstract; bps paywalled →
  **NOT-EXTRACTED**).
- **Cost:** monthly ⇒ **SURVIVES**; but the signal is measured in months, so horizon is 3+ weeks,
  at the long end of "short".
- **Flags:** needs **signed retail flow** (TAQ Boehmer–Jones–Zhang–Zhang classification — prior
  research confirms we don't have it). Not an oscillator.

## 10. Volume-conditioned reversal  — VOLUME × MEAN-REVERSION  (DUPLICATE-ADJACENT)
- **Rule:** first-order daily autocorrelation declines with volume: **a down day on HIGH volume
  bounces harder than a down day on LOW volume** (high-volume down-move ⇒ expected-return
  increase).
- **Source:** Campbell, Grossman & Wang 1993, "Trading Volume and Serial Correlation in Stock
  Returns", *Quarterly Journal of Economics* 108(4):905–939. https://doi.org/10.2307/2118454
- **Cost:** 1–2 day hold ⇒ **SURVIVES** if the volume condition adds >6 bp over unconditional
  dip-buy.
- **Flags:** **DUPLICATE-ADJACENT** — this is the same mean-reversion family as Broken
  Arrow/dip-buy (price-drop reversion), but the **volume gate is the new, untested bit**. Use as a
  *filter on* the existing dip-buy lane (only fade high-volume drops), not a new lane.

## 11. High-frequency return predictability  — VOLUME/ORDER-FLOW (NOT tradeable here)
- **Source:** Aït-Sahalia, Fan, Xue & Zhu 2025, "How and When Are High-Frequency Stock Returns
  Predictable?", *Management Science*. https://doi.org/10.1287/mnsc.2022.02435
- **Finding:** HF return/duration predictability is large and pervasive at short horizons via
  trade+quote predictors, but decays in **milliseconds** and requires a look-ahead at order flow
  (fast-trader domain).
- **Flags:** **NOT-EXTRACTED / NOT-APPLICABLE** — needs tick data + ML + sub-second execution; the
  exact opposite of a $700 Robinhood fractional account. Listed only to mark the boundary of what
  the new 1-min bars can vs cannot reach.

## 12. Return acceleration (practitioner, monthly)  — MOMENTUM ("acceleration" angle)
- **Rule:** rank by **rate of change of momentum** (acceleration = second-difference of returns)
  instead of level; decile long/short, monthly rebalance.
- **Source (practitioner, evidence-based):** CXO Advisory 2015, "Return Acceleration More
  Effective than Momentum?". https://www.cxoadvisory.com/momentum-investing/return-acceleration-more-effective-than-momentum/
- **Magnitude:** acceleration factor **12% vs 7% annualized gross** excess return for momentum
  (May 1963–Dec 2013).
- **Flags:** **monthly, long/SHORT decile, GROSS (no costs)** — not intraday/3-day, needs shorting,
  practitioner source not academic. Included only because "acceleration" was asked for; the honest
  verdict is that no primary short-horizon "acceleration" paper exists.

---

## ALREADY DONE — do NOT re-research (verified banked)
- **Market intraday momentum** (Gao–Han–Li–Zhou 2018 JFE; Baltussen–Da–Lammers–Terhorst 2021 JFE
  `r_ROD` upgrade; Li–Sakkas–Urquhart 2022) — first/open→last-half-hour momentum, incl. the
  dealer-gamma (NGE<0) gate.
- **Overnight drift** (Boyarchenko–Larsen–Whelan 2023 RFS) — needs globex, post-2021 fade.
- **Turn-of-month** (Etula–Rinne–Suominen–Vaittinen 2020 RFS "Dash for Cash" T-day map).
- **Pre-FOMC drift** (Lucca–Moench 2015 NY Fed SR512) + **macro-announcement premium**
  (Savor–Wilson 2013 JFQA).
- **Dealer-gamma regime gate** (Barbon–Beckmeyer–Buraschi–Moerke WP) — as MIM conditioner.
- **ORB** (Zarattini–Barbon–Aziz 2024; community) — rejected: shorts, 17% win, AH-fill
  contamination, divergent replications.
- **Weekly short-term reversal** (Lehmann 1990 / Jegadeesh 1990) — L/S, cost-killed at daily
  rebalance.
- **Gap-fade / VWAP 2σ / KAMA** — prior NO-GO verdicts on file (see `research/`).

## Recommended next backtests (ranked)
1. **Pre-holiday drift** on SPY/QQQ 1990–2026 (trivial, ~8 trades/yr — cheapest test, highest
   certainty).
2. **Volume-gate on the existing dip-buy lane** (#10 filter: only fade HIGH-volume drops).
3. **Volume-conditioned intraday momentum** (#7) on US 1-min bars — the direct use of the new data.
4. **Earnings-announcement premium** (#2) once exact earnings dates are in hand.
5. **High-volume return premium** (#3) — already queued, just run it.
