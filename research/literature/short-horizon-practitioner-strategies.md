# Short-Horizon (1–5 Day) Practitioner/Industry Quant Strategies — Investigative Report

**Prepared:** 2026-08-24 (subagent task)
**Scope:** Practitioner/industry sources only — Alpha Architect, Quantpedia, Quantocracy, Ernie Chan, Rob Carver, Newfound/Hoffstein, QuantStart, QuantRocket, Option Alpha.
**Verification rule applied:** every quantitative claim below carries its source URL. Numbers were transcribed from fetched full-text; nothing is invented. Where a figure lives only in an image/chart and could not be text-extracted, it is explicitly flagged as "not extracted."

---

## Ranking (testability × short-horizon edge × implementation completeness)

| # | Strategy | Holding | Edge strength | Testability (our data) | Verdict |
|---|----------|---------|---------------|------------------------|---------|
| 1 | Short-term reversal, large-cap (weekly) | 1 week | Strong (Sharpe ~1.09) | Excellent — 20y daily equities | **GENUINE** |
| 2 | Overnight-gap mean reversion (Chan Ex 4.1) | intraday | Strong | Good — daily OHLC (intraday caveat) | **GENUINE, execution-sensitive** |
| 3 | Market intraday momentum (Gao–Han–Zhou) | intraday (last ½hr) | Strong, replicated | Good — intraday futures | **GENUINE** |
| 4 | Intraday momentum "noise-area" breakout (Zarattini) | intraday | Moderate–strong (replicated) | Good — minute futures | **GENUINE** |
| 5 | Bollinger intraday mean reversion (Chan Ex 3.8) | intraday | Strong but regime-dependent | Good — daily OHLC | **GENUINE w/ caveats** |
| 6 | Correlated stress reversal (multi-asset) | 1 day | Moderate (single source) | Good — daily ETFs | **PROMISING, under-sourced** |
| 7 | Earnings-announcement reversal | 2–3 days | Moderate, OOS-deteriorating | Needs earnings dates | **GENUINE, decaying** |
| 8 | Short-term reversal in futures (vol/OI) | 1 week | Strong (old sample) | Gap: open interest + futures history | **GENUINE, data-gap** |
| 9 | ETF pairs trading (Johansen + Bollinger) | days–weeks | Moderate, decays ~2y | Good — daily ETFs | **GENUINE, needs pipeline** |
| — | Rob Carver vol targeting | overlay | improves Sharpe ~1/3 | Sizing technique | **OVERLAY, not standalone** |
| — | Option Alpha iron condor / short strangle | 30–45 DTE (or 0DTE) | vol-selling, neg skew | Options chains (have) | **STRUCTURE, not directional edge** |

---

## 1. Short-Term Reversal — Large-Cap Stocks (Weekly)

**Source:** Quantpedia, "Short Term Reversal Effect in Stocks" — https://quantpedia.com/strategies/short-term-reversal-in-stocks
**Academic root:** de Groot, Huij, Zhou, *"Another Look at Trading Costs and Short-Term Reversal Profits"* (SSRN 1605049).

- **Universe:** 100 largest stocks by market capitalization (global).
- **Entry:** Go **long the 10 stocks with the lowest prior-WEEK return**; go **short the 10 stocks with the highest prior-MONTH return** (note asymmetry: 1-week lookback for the long leg, 1-month for the short leg).
- **Exit / holding:** Hold 1 week; **rebalance weekly**.
- **Position sizing:** Equal weight across 20 names (10 long + 10 short); dollar-neutral long/short.
- **Reported stats:** Net geometric weekly return **0.29% → ~16.25% p.a.**; est. vol 14.94%; **Sharpe 1.09**; max DD −52.94%; backtest 1990–2009. Source paper: **30–50 bp/week net of transaction costs** on large caps.
- **Edge rationale:** Overreaction correction + liquidity provision (Nagel, "Evaporating Liquidity"). Key implementation insight: reversal only survives costs when **restricted to large caps**; small-cap reversal is eaten by costs.
- **Veracity:** GENUINE short-horizon edge. Quantpedia marks "confidence in anomaly: Strong." Caveat: a later Quantpedia paper ("Reversing the Trend of Short-Term Reversal," Blitz et al.) notes the *classic* version has weakened over time and suggests netting out short-term *industry/factor momentum* to revive it.
- **Data check:** We hold 20y+ daily US equities. ✅ Fully testable today.

---

## 2. Overnight-Gap Mean Reversion (Ernie Chan, *Algorithmic Trading* Ex 4.1)

**Source:** Ernie Chan, "Beware of Low Frequency Data" — http://epchan.blogspot.com/2015/04/beware-of-low-frequency-data.html (strategy described as Example 4.1 of *Algorithmic Trading*).

- **Universe:** SPX (S&P 500) constituents.
- **Entry (at the open):** **Buy the 10 stocks that gapped DOWN the most** at the open; **short the 10 stocks that gapped UP the most** (gap = return from prior close → today's open).
- **Exit:** **Liquidate everything at the close** (same day).
- **Holding:** Intraday (open→close); **~1 round-trip/day**.
- **Position sizing:** Equal weight, 10 long + 10 short.
- **Reported stats:** Chan does not publish P&L in this post (the post is about backtest data quality); he states the "essential driver of the returns is mean-reversion of the overnight gap."
- **Veracity:** GENUINE short-horizon edge, but with a **critical execution caveat** documented by Chan himself: backtesting on **1-minute bars overstates returns** vs. **1-millisecond BBO quotes**, because the strategy hits high-frequency "flip-flops" (sudden order-book moves that immediately revert, aka "mini flash crashes"). Live fills are materially worse than minute-bar backtests. This is a *short-vol / liquidity-providing* profile.
- **Data check:** Daily OHLC gives open/close → a first-cut backtest is trivially possible. A *faithful* backtest needs intraday/tick data to avoid the flip-flop overstatement. We have ~1y of futures intraday bars but **this is an equities strategy** — flag: limited intraday equities history.

---

## 3. Market Intraday Momentum — First Half-Hour Predicts Last Half-Hour (Gao, Han, Zhou)

**Source:** Alpha Architect, "Attention Prop Traders: The first half hour of trading predicts the last half hour" — https://alphaarchitect.com/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/ ; paper: Gao, Han, Zhou, *"Market Intraday Momentum"* (SSRN 2440866).

- **Universe:** SPY (SPDR S&P 500 ETF).
- **Entry:** **If the first half-hour return (r₁) > 0 → go LONG the last half-hour; if r₁ < 0 → go SHORT the last half-hour.** (Variants: use the 12th half-hour return r₁₂, or require r₁ and r₁₂ to agree, else flat.)
- **Exit:** At the close.
- **Holding:** Last half-hour only (intraday).
- **Position sizing:** 1× (single instrument).
- **Reported stats:** Simple first-half-hour rule earned **6.34% annualized** (SPY, 1999–2012), beating both "always long the last half-hour" and buy-and-hold. Predictive regression R² ≈ **2%** full sample, **4.3% during the financial crisis**. Effect is stronger on high-volatility days and in recessions (per the underlying paper).
- **Veracity:** GENUINE, well-replicated academic intraday momentum. Note the raw annual return is modest (single half-hour/day) and the edge concentrates in high-vol/recession regimes.
- **Data check:** Needs intraday bars partitioned into 13 half-hour buckets. We hold ~1y of futures intraday bars — ES can proxy SPY. ✅ Testable (but 1y of intraday is short for statistical comfort).

---

## 4. Intraday Momentum — "Noise-Area" Breakout (Zarattini, Aziz, Barbon)

**Source:** Quantitativo, "Intraday Momentum for ES and NQ" — https://www.quantitativo.com/p/intraday-momentum-for-es-and-nq ; paper: *"Beat the Market: An Effective Intraday Momentum Strategy for S&P 500 ETF"* (SSRN 4824172). Independent replication with minute data 2010–today.

- **Universe:** ES and NQ futures (S&P 500 / Nasdaq-100).
- **Entry:** Define a **"Noise Area"** from prior intraday price range over a lookback (**14 days** per paper; **90 days** improved results). **Long when price breaks above the Noise Area; short when price breaks below.**
- **Exit:** At market close, or when price reverses back into the Noise Area. **Trailing stops:** at Noise-Area boundary or VWAP.
- **Holding:** Intraday.
- **Position sizing:** Scale positions to a **daily vol target (2% paper / 3% improved)**, leverage capped at **4× (paper) / 8× (improved)**.
- **Reported stats (independent replication, after $0.85/contract commission + $1.40/contract fees + 0.25-tick slippage):**
  - ES, paper rules: +8.1%/yr, Sharpe 0.91, max DD 24%.
  - ES, improved (90-day lookback, 3% vol, 8× cap): +16.8%/yr, Sharpe 1.25, DD 21%.
  - NQ: +24.3%/yr, Sharpe 1.67, DD 24%.
  - Portfolio (50% NQ-strategy / 25% ES-strategy / 25% NQ long-only): +22.4%/yr, **Sharpe 1.57**, max DD 15%; 2 negative years in 16; per-trade +6 bps, win rate ~38%, payoff ~2.25.
- **Veracity:** GENUINE. The replicator notes the paper's headline (+12.4%/yr) is flattered by a 2007 start (2008 helps) and low slippage assumptions; realistic replication is ~8–17% with Sharpe ~0.9–1.25. Effect mostly flat 2010–2017, works from ~2018.
- **Data check:** Needs minute intraday data (have ~1y futures intraday). ✅ Testable; short history is the limiting factor.

---

## 5. Bollinger-Band Intraday Mean Reversion (Ernie Chan, *Quantitative Trading* Ex 3.8)

**Source:** Ernie Chan, "The enduring profitability of mean-reversion strategies" — http://epchan.blogspot.com/2008/12/enduring-profitability-of-mean.html (Example 3.8 of *Quantitative Trading*).

- **Universe:** S&P 1500 (SP1500) constituents.
- **Entry (at the open, opening auction):** **Buy when price is at/below the lower Bollinger band; sell (short) at the upper band** (Bollinger = rolling MA ± k·σ).
- **Exit:** At the close (or on reversion to the moving-average mid-band).
- **Holding:** Intraday (1 day).
- **Position sizing:** ~**1/300 of gross capital per symbol** (broad, diversified book).
- **Reported stats:** **Sharpe 4.8 gross, 3.5 net** after 10 bps round-trip cost — measured on *unseen* 2008 SP1500 data (constructed ~1y prior while writing the book, i.e., out-of-sample). Chan also confirms "no down years" for his mean-reversion book strategies across bull/bear regimes through that period.
- **Veracity:** GENUINE but with two self-acknowledged caveats: (1) **survivorship bias** (SP1500 membership excludes delisted busts like AIG/LEH/FNM; Chan mitigates by ~1/300 sizing); (2) 2008 was an unusually favorable reversal year. Execution nuance: trades at the opening auction (not a guaranteed fill price).
- **Data check:** Daily OHLC suffices for a first pass. ✅ Testable.

---

## 6. Correlated Stress Reversal — 1-Day Cross-Asset Reversal

**Source:** Quantpedia, "Short-Term Correlated Stress Reversal Trading" (Cyril Dujava, Apr 2025) — https://quantpedia.com/short-term-correlated-stress-reversal-trading/

- **Universe / inputs:** Daily ETF prices — SPY (equities), USO (oil), GLD (gold), IEF (7–10y Treasuries), UUP (USD). Sample 2004–2025.
- **Entry signal (a "stress day"):** (a) **two risk-on assets decline together** (pairs: GLD+SPY, USO+SPY, USO+GLD), OR (b) **one risk-on asset declines while the risk-off asset (IEF) rises**. Threshold parameterized; optimal ~**0% to −0.5%** daily move.
- **Entry:** At the **close of the stress day**, go **LONG SPY** (equities showed the strongest next-day bounce).
- **Exit:** At the close of the **next trading day** (1-day hold).
- **Position sizing:** Composite = **equal weight of 3 signals** (IEF↑+GLD↓, IEF↑+USO↓, IEF↑+SPY↓).
- **Reported stats:** Performance tables are **images — exact Sharpe/return NOT text-extractable in this pass** (flag). Qualitative finding: SPY is the best reversal asset after cross-asset stress; the 3-signal equal-weight composite showed "enhanced risk-adjusted returns."
- **Veracity:** PROMISING but thin — single 2025 blog post, thresholds are optimized, short history. Conceptually consistent with the liquidity-provision/reversal literature (Nagel). Treat as a candidate, not a confirmed edge.
- **Data check:** Only daily ETF prices needed — we hold 20y+ daily US equities/ETFs. ✅ Fully testable.

---

## 7. Reversal Around Earnings Announcements (2–3 Day)

**Source:** Quantpedia, "Reversal During Earnings-Announcements" — https://quantpedia.com/strategies/reversal-during-earnings-announcements ; paper: So & Wang, *"News-Driven Return Reversals"* (SSRN 2275982); plus Jansen & Nikiforov, *"Fear and Greed"*.

- **Universe:** NYSE/AMEX/NASDAQ common stocks; restrict to the **top size quintile (largest)**.
- **Entry:** Within the top size quintile, sort into quintiles by **average return over t−4 to t−2** (where t = earnings day). **Long the bottom quintile (losers); short the top quintile (winners).**
- **Exit / holding:** Hold across **t−1, t, t+1 (a 3-day window)**.
- **Position sizing:** Equal weight.
- **Reported stats:** LOW−HIGH 3-day return **1.45%** (1996–2011) vs **0.22%** in random pseudo-announcement periods (6× gap); ~6.5% p.a. (arith), Sharpe 1.73, max DD −65.88%. **Jansen & Nikiforov variant:** stocks with extreme abnormal returns the week before earnings reverse **+1.3% over a 2-day window**, profitable **40 of 42 years**.
- **Veracity:** GENUINE historically, but Quantpedia flags **out-of-sample deterioration** ("alpha deteriorating in the out-of-sample period"). The "Fear and Greed" 2-day variant is the more robust formulation. This is an event-driven reversal, distinct from unconditional reversal.
- **Data check:** ⚠️ **Gap — requires exact earnings-announcement dates** (Compustat source in the paper). We hold fundamentals + news headlines; confirm whether announcement dates (not just news text) are in S3. Daily prices ✅.

---

## 8. Short-Term Reversal in Futures — Volume/OI Conditioned (Weekly)

**Source:** Quantpedia, "Short Term Reversal with Futures" — https://quantpedia.com/strategies/short-term-reversal-with-futures ; paper: Wang & Yu, *"Trading activity and price reversals in futures markets"*.

- **Universe:** **24 US futures** — 4 FX, 5 financials, 8 agricultural, 7 commodities.
- **Signal conditioning:** Classify each contract by **lagged change in volume** (high = above median, detrended by sample mean) and **lagged change in open interest** (high = top 50%, low = bottom 50%). Target the **high-volume, low-open-interest** group.
- **Entry (weekly, Wednesday→Wednesday):** Long the **lowest prior-week return** contract in that group; short the **highest prior-week return**.
- **Exit / holding:** 1 week.
- **Position sizing:** Weight ∝ (contract return − equal-weighted average return of the group's N contracts).
- **Reported stats:** **0.57%/week → 29.64% p.a.** (arithmetic), vol 31.4%, **Sharpe 0.82**, max DD −58.65%, sample 1983–2000; ~6 contracts held.
- **Veracity:** GENUINE weekly reversal effect (mirrors equity reversal), "Strong" confidence per Quantpedia — but the sample is old (1983–2000) and the strategy is cash-futures-reversal, i.e., short-vol/liquidity-providing.
- **Data check:** ⚠️ **Two gaps:** (1) **futures open interest and volume** — we hold "futures intraday bars" but OI is not explicitly listed in our data inventory; (2) the strategy needs **multi-year daily futures history**, whereas we have only ~1y intraday. Not currently testable at full fidelity.

---

## 9. ETF Pairs Trading — Johansen Hedge Ratio + 1σ Bollinger Band

**Source:** QuantRocket, "Is Pairs Trading Still Viable?" — https://www.quantrocket.com/blog/pairs-trading-still-viable/ ; rooted in Ernie Chan, *Algorithmic Trading*, ch. 4.

- **Universe:** Liquid US ETFs (avg daily dollar volume > $10M → ~110 ETFs), or a chosen pair (e.g., GLD/GDX).
- **Entry:** Compute the daily **hedge ratio via the Johansen cointegration test** (rolling window); spread = hedge-weighted sum of the pair. **Long the spread when it crosses below the lower band; short when above the upper band.** Bands = **20-day rolling mean ± 1 standard deviation** of the spread.
- **Exit:** When the spread **crosses back through the mean**.
- **Holding:** Mean-reversion driven — typically a few days to ~2 weeks (1σ/20-day Bollinger).
- **Position sizing:** Hedge-ratio weighted (dollar-neutral long/short).
- **Reported stats:** GLD/GDX pair profitable ~2 years out-of-sample (post-2013 book publication), then decayed. A 5-pair ETF pipeline (in-sample 2012–2015 Sharps: USO/DUG 1.03, LQD/QID 0.96, ICF/FAZ 0.71, VNQ/FAZ 0.70, XLI/IWR 0.69) also decayed ~2 years out-of-sample.
- **Veracity:** GENUINE but **decaying** — pairs break cointegration within ~1–2 years. Requires a **continuous re-selection pipeline** (re-run Johansen + in-sample selection annually). Flag: top pairs included leveraged/inverse ETFs that are expensive to short.
- **Data check:** Daily ETF/equity prices ✅; Johansen via `statsmodels.tsa.vector_ar.vecm.coint_johansen`. Fully testable.

---

## Overlay / technique (not a standalone 1–5 day edge)

### Rob Carver — Volatility Targeting
**Source:** "Vol Targeting and Trend Following" — https://qoppac.blogspot.com/2018/07/vol-targeting-and-trend-following.html
- **What it is:** Scale position = target vol ÷ recent realized vol (dynamic, ~last month). A **position-sizing overlay**, not an entry/exit edge. Carver's underlying system is *trend-following* (weeks–months horizon) — not short-horizon.
- **Evidence:** Across 37 futures (Systematic Trading ch. 15, trend-only), vol targeting raises **Sharpe from 0.569 → 0.92** (significant, t≈3.59), cuts min monthly return from −55.6% to −32.6% and kurtosis from 33 → 5.28, at a cost of some positive skew (+2.46 → +1.08).
- **Use:** Apply as the sizing layer on *any* of the short-horizon strategies above (most naturally #4, which already uses a vol target). Not itself a short-horizon edge.

---

## Options structure (not a directional 1–5 day edge)

### Option Alpha — Iron Condor / Short Strangle (short volatility)
**Sources:** https://optionalpha.com/strategies/iron-condor and https://optionalpha.com/strategies/short-strangle
- **Mechanics (iron condor):** Sell OTM put spread + OTM call spread, same expiry; credit = max profit; max loss = spread width − credit. **Short strangle:** sell OTM put + OTM call (undefined risk). Profit from theta + vol crush + range-bound underlying.
- **Holding:** Option Alpha's standard framework is **~30–45 DTE** (longer than 1–5 days) — manage at ~50% max profit or ~21 DTE. The genuinely *short-horizon* variant is **0DTE / 1–5 DTE** short-duration selling (see Option Alpha's 0DTE backtester — https://optionalpha.com/backtester).
- **Veracity:** This is a **short-volatility / theta-harvesting** strategy with **negative skew**, not a mispricing edge; performance is regime-dependent (VIX level) and dominated by the few tail days. Do not confuse with the directional short-horizon edges above. Exact Option Alpha default parameters (strike ≈ 16-delta/1σ, 45 DTE) are their published methodology but were **not independently re-verified in this pass**.
- **Data check:** We hold options chains ✅ — iron condor / strangle and 0DTE backtests are runnable, but require careful vol/theta modeling and borrow/assignment handling.

---

## Flagged as LONG-HORIZON / FOLKLORE (do NOT treat as 1–5 day edges)

1. **Alpha Architect "Combining Reversals with TSMOM"** (Liu & Papailias) — https://alphaarchitect.com/combining-reversals/ — the "trend-following reversal" here is a **12–24 month** effect. Long-horizon; not actionable at 1–5 days.
2. **Quantpedia "FSCORE + Short-Term Reversal"** — https://quantpedia.com/strategies/combining-fundamental-fscore-and-equity-short-term-reversals — **monthly** rebalance on past 1-month returns. Outside the 1–5 day window (and OOS-deteriorating).
3. **Rob Carver trend-following proper** — multi-week/multi-month horizon; the short-horizon relevance is limited to his vol-targeting overlay (#overlay).
4. **Newfound / Hoffstein "Rebalance Timing Luck"** — https://www.thinknewfound.com/rebalance-timing-luck — a *methodology* finding (performance dispersion from rebalance-date choice: >100 bp annualized for factor indices; >400 bp tracking error for a 3-month put-spread collar). Not a trading strategy; treat as a **backtest-robustness caveat** — any short-horizon strategy's measured edge is sensitive to the exact rebalance timestamp.
5. **Newfound / Hoffstein on reversal generally:** his public commentary (Flirting with Models / podcasts) frames **1-day reversal as largely bid-ask-bounce (microstructure)**, with the real signal at **1-week/1-month** — consistent with #1 and #6. (Not pinned to a single URL this pass; treat as orientation, not a cited stat.)

---

## Data-collection gaps to close before full testing

| Need | Strategy affected | Status |
|------|-------------------|--------|
| Exact earnings-announcement dates | #7 Earnings reversal | ⚠️ confirm in S3 (fundamentals/news may lack precise dates) |
| Futures **open interest** + volume history | #8 Futures reversal | ⚠️ OI not in stated inventory |
| Multi-year **daily futures** history | #8 | ⚠️ only ~1y intraday held |
| Intraday bars ≥1-min for **equities/SPY** | #2, #3, #5 | ⚠️ intraday futures held, equities intraday unclear |
| Options IV surface / Greeks (not just chains) | Options section | ⚠️ need IV + term structure for faithful vol-strategy backtest |
| Survivorship-bias-free equity universe (delistings) | #2, #5 | ⚠️ Chan explicitly flags this; point-in-time constituents needed |

---

## Bottom line

Highest-conviction, immediately testable short-horizon edges given the data we already hold: **#1 large-cap weekly reversal** (daily equities, exact rules, Sharpe ~1.09), **#2 overnight-gap mean reversion** (daily OHLC, exact rules), and **#3 market intraday momentum** (intraday futures, replicated). **#4 noise-area intraday momentum** is the strongest *risk-adjusted* candidate (Sharpe up to 1.67 single-instrument) but is execution- and data-hungry. The options (iron condor/strangle/0DTE) and vol-targeting overlay are useful *building blocks* but are not directional 1–5 day edges. Everything longer than ~1 month (TSMOM reversal, FSCORE reversal, trend-following) is correctly classified as long-horizon and should not be bundled into a short-horizon alpha stack.
