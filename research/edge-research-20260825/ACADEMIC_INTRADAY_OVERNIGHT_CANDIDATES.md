# Academic Intraday & Close-to-Open Equity Strategy Candidates
**Deep-mine beyond SSRN/Quantpedia first page — 15 candidates with exact rules**
Compiled 2026-08-25. Every number below was extracted from a full text I actually downloaded and read
(open-access PDFs from author pages, university repositories, RePEc-verified journal records).
Unreadable/paywalled figures are marked **NOT-EXTRACTED** — nothing is estimated.

Sources fetched to `/home/ubuntu/research_out/*.txt` (raw extracted text, re-greppable).

## Ranking (testability × edge size × fit to A/B)

| # | Candidate | Fit | Gross edge | Survives 6bp RT? |
|---|-----------|-----|-----------|------------------|
| 1 | MIM on **r_ROD** (Baltussen-Da-Lammers-Terhorst) | A | SR 1.73, 6.86%/yr | **Futures YES / SPY NO** |
| 2 | Turn-of-month T-8→T-4 / T-3→T-1 (Etula et al.) | B-adj | whole equity premium in 7 days | **YES (easily)** |
| 3 | End-of-day cross-sectional reversal (Baltussen-Soebhag-Da) | A | 3.78–6.86 bps/day | **NO** |
| 4 | Overnight-return persistence, weekly (Aboody et al.) | B | 1.76 pp/wk decile spread | Marginal |
| 5 | VOL+-conditioned long-night/short-day (Fortuin thesis) | B | 7–10 bps/day | **NO** as stated |
| 6 | Intraday periodicity at 13-lag multiples (Heston-Korajczyk-Sadka) | A | 3.03–5.16 bps | **NO (proven)** |
| 7 | Daily tug-of-war intensity (Akbas et al.) | B | NOT-EXTRACTED | Unknown |
| 8 | Gap-fade at the open / attention (Berkman et al.) | A+B | NOT-EXTRACTED | Unknown |
| 9 | Gamma-hedging + LETF end-of-day flow (Barbon et al.) | A | −113% / +430% of avg LH return | Unknown |
| 10 | Day-of-week overnight, Mon→Tue (Lin 2025) | B | points only, NOT-EXTRACTED | Unknown, low turnover |
| 11 | Retail trading proportion → return gap (Ahn et al.) | B | 0.8 bps/day per 1pp RTP | Unknown |
| 12 | ORB with normal-tail threshold (Holmberg et al.) | A | success rate > fair game | Sub-period failure |
| 13 | Size/illiquidity premium in last 30 min (Bogousslavsky) | A | NOT-EXTRACTED | Unknown |
| 14 | Closing-auction imbalance → next day (Majorin thesis) | B | NOT-EXTRACTED | Unknown |
| 15 | Naive SPY buy-close/sell-open | B | +717% gross | **NO: −32% net** |

---

# A) INTRADAY (same day, enter morning / exit before close)

## 1. Market intraday momentum on the *rest-of-day* return (r_ROD) — the upgrade to Gao et al.
**Thesis:** the return from the previous close all the way to 30 minutes before the close predicts the
last-30-minute return *better and more robustly* than the first-half-hour signal, because it proxies the
accumulated short-gamma hedging imbalance that must be unwound into the close.

**EXACT RULES**
- Universe: equity index futures (17 developed markets, incl. ES/YM); also works on bonds/commodities/FX.
- Signal: `r_ROD` = return from **previous market close → 30 minutes before today's close** (15:30 ET for a 16:00 close).
- Entry: at **15:30 ET**, long if `r_ROD > 0`, short if `r_ROD < 0`.
- Exit: **market close (16:00 ET)**. Holding period 30 minutes. Sizing: constant unit exposure.
- Combined variant `η(r_ONFH, r_ROD)`: also require the first-half-hour signal (`r_ONFH` = prev close → 10:00) to agree.
- Regime filter (their key contribution): only trade when dealers' **net gamma exposure (NGE) < 0**.

**MAGNITUDES** — Baltussen, Da, Lammers & Terhorst (2021), *Journal of Financial Economics* 142(1):377–403,
DOI 10.1016/j.jfineco.2021.04.029. OA full text: https://academicweb.nd.edu/~zda/intramom.pdf
Sample: 60 futures, **Dec 1974 – May 2020**.
- Equity-index futures panel, timing strategy `η(r_ROD)`: avg return **6.86%/yr**, SD 3.96%, **Sharpe 1.73**, success rate 0.55.
  `η(r_ONFH)`: 4.21%, SD 3.95%, SR 1.07. `η(r_ONFH, r_ROD)`: 5.47%, SD 3.42%, **SR 1.60, success 0.61**.
  Benchmarks: Always-Long 0.44% / SR 0.11; Buy&Hold 8.76% / SD 17.29% / SR 0.51.
- Predictive regressions, equity index futures full sample: β_ROD = **4.18 (t = 7.29), R² = 2.45%**;
  β_ONFH = 4.86 (t = 6.52), R² = 1.49%.
- **2000–2020 subsample** (i.e. post-Gao-sample robustness): β_ROD = **3.97 (t = 6.66), R² = 2.34%** — effect persists.
- Gamma conditioning (S&P 500 futures, Jan 1996 – May 2020): when NGE < 0, β_ROD = **6.63 (t = 4.78), R² = 3.58%**;
  when NGE ≥ 0, β_ROD = **0.82 (t = 1.03), R² = 0.05% — insignificant**.
- Mean-reversion after the fact: `r_LH,t` predicts negative equity-futures close-to-close returns over the
  next 1–3 days: −14.51 (t = −1.70), −29.05 (t = −3.16), −27.98 (t = −2.61).
- Authors state main results **exclude transaction costs**, but that exploiting it in S&P 500 futures
  "yields a positive net Sharpe ratio when we assume transaction cost equal to a tick."

**REPLICATION / OOS**
- Li, Sakkas & Urquhart (2022), *Journal of Financial Markets* 57:100619, DOI 10.1016/j.finmar.2021.100619
  (RePEc:eee:finmar:v:57:y:2022:i:c:s138641812100001x). OA: https://centaur.reading.ac.uk/95566/1/Accepted-Version.pdf
  16 developed markets, **4 Oct 2005 – 29 Dec 2017**. Rule: long last half-hour if first half-hour > 0, else short,
  flat at the close. Significant alphas in **10 of 16 countries**, ranging **+2.66%/yr (UK) to +7.45%/yr (Norway)**
  vs Always-Long; annualized appraisal ratios **0.52 (UK) to 0.99 (Norway)**. US first-half-hour return has
  exploitable cross-country predictive power. Global EW portfolio 3.06%/yr, VW 4.75%/yr; best variant
  (mean-variance-weighted, Type 3) 6.75%/yr with spanning alphas 5.63–7.19%.
- Limkriangkrai, Chai & Zheng (2023), *Pacific-Basin Finance Journal* 80:102086 (open access,
  researchmgt.monash.edu/ws/files/519509174/494419119_oa.pdf). **PARTIAL FAILURE**: intraday momentum
  present in China and Japan only; weak in South Korea; **absent in Hong Kong and Singapore**; weaker during
  COVID (14 Feb – 31 Mar 2020) where China's r1 and r_{n-1} "completely lose their predictive power".
  Their US SPY benchmark replication (Jan 1996 – Dec 2013): coefficient **7.15, R² = 1.7%**, significant at 1%.
- Rosa (2022), *Journal of Futures Markets* 42(12):2218–2234 — always-on rule loses OOS predictability (already in bank).

**DATA NEEDED:** 30-min (or finer) RTH bars for ES/MES/NQ/MNQ + daily close for the overnight leg. Already have.
For the gamma filter: index option open interest + gamma (OptionMetrics or CBOE) — **do not have**.

**HONEST PRIOR:** The only candidate here whose stated gross edge clearly clears our cost bar — **but only in
futures**. 6.86%/yr ÷ 252 ≈ **2.7 bps/day gross**; one round trip on SPY at 6 bps **kills it outright**.
On ES/MES a 1-tick round trip is ≈ 0.4–0.8 bp, so it survives with room. Test on MES first, futures only.
The NGE filter is likely where the real edge lives — worth acquiring option data for.

## 2. End-of-day cross-sectional reversal (intraday losers bounce into the close)
**Thesis:** individual stocks that fell during the day get bought back in the last 30 minutes
(attention-induced retail buying + short-seller risk management at the close).

**EXACT RULES**
- Universe: US common stocks, TAQ, price filter applied (results shown for two filters).
- Signal: `ROD3_{i,t}` = return from **close of day t−1 → 15:00 ET on day t**.
- Sort into quintiles on ROD3 at 15:00. **Long quintile L (intraday losers), short quintile H (intraday winners).**
- Entry: **15:30 ET** (deliberate 30-minute gap after the signal window, to kill bid-ask bounce).
- Exit: **16:00 ET**. Holding period 30 minutes, daily rebalance.
- Weighting: value-weighted or equal-weighted (both reported).

**MAGNITUDES** — Baltussen, Soebhag & Da, "End-of-Day Reversal", working paper (EFMA 2024;
Erasmus School of Economics + Notre Dame). OA: https://academicweb.nd.edu/~zda/EOD.pdf
Sample: **from 1993** (TAQ, 9:30–16:00 EST, seconds→VWAP, split/dividend adjusted, winsorized 1%/99%).
- Value-weighted L−H spread: **3.78 bps/day, t = 10.69** (≈ **9.5%/yr**). Quintile L = 3.55 bps/day, quintile H = −0.22 bps/day.
- FF6 alpha of the spread: **3.71 bps/day, t = 10.61**.
- Equal-weighted L−H spread: **6.38 bps/day, t = 17.30**; headline EW figure **6.86 bps/day ≈ 17.3%/yr**.
- t-statistics "typically exceeding 10 in simple portfolio sorts"; strategies 3.78–6.86 bps/day (9.5–17.3%/yr)
  depending on weighting and price filter.
- Stronger in small firms; the effect comes **primarily from positive price pressure on intraday losers**.
- Explicitly **distinct from market intraday momentum**; not explained by liquidity or gamma-hedging.
- Authors' own caveat: "the strategy as presented might not be exploitable by many investors after accounting
  for transaction costs" — viable for market makers / prop desks / as an execution overlay.
- Related note in the same paper: the 9:30–16:00 return on day t−1 **positively** predicts the first-half-hour
  return on day t but **negatively** predicts overnight returns (consistent with Akbas 2022 and Berkman 2012).

**REPLICATION:** none found yet (2024 WP). It cites and is distinct from Heston et al. (2010) and Bogousslavsky (2016).

**DATA NEEDED:** 30-min intraday bars for a broad US cross-section (≥ 1,000 names) + market cap + price filter.
Also requires **short selling** of the winner leg. We do not have a broad intraday cross-section.

**HONEST PRIOR:** **Fails at 6 bp.** A daily L/S rebalance is two round trips (long leg + short leg) ≈ 12 bps
against 3.78 bps VW gross. Even the EW 6.86 bps is under cost. Do NOT trade as a standalone.
Its real value to us is as an **execution rule**: if we must buy, buy intraday losers at 15:30, not at 15:00.

## 3. Intraday periodicity — same half-hour-of-day, k = 13, 26, 39… lags
**Thesis:** institutional flow and execution algos are autocorrelated day-to-day, so a stock's return in a
given half hour predicts its return in that *same* half hour on subsequent days, for up to 40 trading days.

**EXACT RULES**
- Universe: NYSE common stocks (CRSP share code 10/11), 1,715 firms.
- Split the day into **13 half-hour intervals, 9:30–16:00** (excludes overnight).
- For interval t, cross-sectionally regress `r_{i,t}` on `r_{i,t−k}` for **k = 13, 26, 39, 52, 65** (exact multiples
  of one trading day). Long/short the top/bottom decile on the lagged same-interval return.
- Entry at the start of the target half hour, exit at its end. Holding period 30 minutes.
- Effect is **strongest in the first and last half hour** and survives in mid-day.
- Companion negative signal: for **non-daily** lags (k = 1…12) returns *reverse*; that reversal fully resolves in **< 60 minutes**.

**MAGNITUDES** — Heston, Korajczyk & Sadka (2010), *Journal of Finance* (forthcoming version on arXiv);
free full text **arXiv:1005.3535**. Sample **Jan 2001 – Dec 2005** (post-decimalization), NYSE + TAQ.
- Smallest Fama-MacBeth t-statistic at daily lags (13, 26, 39, 52, 65) over the first week: **9.62**.
- Risk-adjusted lag-13 winner-minus-loser decile spread: **3.03 bps**; the k = 1…12 (nondaily) spread is **−4.65 bps**.
- Day-1 Daily strategy: **5.16 bps** (small stocks), **3.28 bps** (non-S&P 500), **2.19 bps** (S&P 500 stocks).
- Day-5 (k = 65) spread: **4.84 bps** in the first half hour, **3.42 bps** in the last half hour; < 1 bp mid-day.
- Persistence: statistically significant for **at least 40 trading days**; volume periodicity significant to 520 half-hour lags.
- Not a weekday, month, turn-of-month or turn-of-quarter effect (Day-1 daily strategy positive in *every*
  calendar month, 1.70 bps in March to 7.80 bps in November; every weekday, 2.62 bps Tue to 3.44 bps Wed).
- **COST FAILURE (measured, not assumed):** buying at the offer and selling at the bid makes the decile
  spread **negative for all size categories at all times of day**: Day-1 Daily = **−23.78 bps** (small),
  **≈ −20 bps** (medium), **≈ −14 bps** (large); implied one-way spread cost **4–7 bps**. Authors' conclusion:
  "does not present a profit opportunity in the absence of other motives to trade."

**DATA NEEDED:** 30-min bars for a wide cross-section + short selling. **Sub-minute not required.**

**HONEST PRIOR:** **Fails at 6 bp — and this is measured in the paper, not my guess.** Include as a
**negative control** and as an execution-timing rule (shifting a trade by 30 minutes recovers roughly one
effective spread). Do not queue as a standalone alpha.

## 4. Opening-range breakout with a normal-tail threshold (testable from daily OHLC only)
**Thesis:** if price travels a statistically abnormal distance from the open, the martingale property breaks
and the move continues to the close.

**EXACT RULES**
- Thresholds set at the open: `ψ^u_t = P^o_t + z_α·σ` and `ψ^l_t = P^o_t − z_α·σ`, where `z_α` = inverse
  standard-normal CDF at tail probability α (they sweep α from 0.0 to 0.5).
- Entry: **long the moment intraday price ≥ ψ^u_t; short the moment price ≤ ψ^l_t** (same day, any time after the open).
- Exit: **the day's close `P^c_t`**. Holding period: intraday, one day max.
- Clever testability trick: with only daily O/H/L/C you know *with certainty* whether the signal fired
  (if `P^h_t > ψ^u_t` a long triggered), which makes the strategy testable on long daily histories.
- Significance via the Brock-Lakonishok-LeBaron (1992) bootstrap, extended to the joint O/H/L/C distribution.

**MAGNITUDES** — Holmberg, Lönnbark & Lundström (2013), *Finance Research Letters* 10(1):27–33;
free WP: Umeå Economic Studies 845 (RePEc:hhs:umnees:0845),
http://www.econ.umu.se/DownloadAsset.action?contentId=196616&languageId=3&assetKey=ues845
Sample: **U.S. crude oil futures, 30 Mar 1983 – 26 Jan 2011, 6,976 daily obs**.
- Full sample: returns "significantly higher than zero" and success rate above a fair game; both the success
  rate and the average return **increase monotonically as α moves further into the tail** (their Fig. 3 shows
  average return rising from ≈0.000 toward ≈0.100 across the α range).
- **SUB-PERIOD FAILURE (their own words):** "splitting up the full sample into three sub-periods reveals that
  this finding is **not robust to time** and to a large extent explained by the most recent (and most volatile) period."
- Exact per-α return / success-rate table values: **NOT-EXTRACTED** (Table 2 numbers did not survive extraction cleanly).

**DATA NEEDED:** daily O/H/L/C (have) for the go/no-go test; intraday bars for realistic fills.
**Not an equity study** — crude oil futures. Flag.

**HONEST PRIOR:** The *method* is more valuable than the result: it lets us pre-screen ORB on 20 years of
daily equity/index OHLC before spending any intraday-data effort. Expect the same volatility-regime
dependence they found; any ORB backtest must be volatility-stratified or it will be a regime artifact.

## 5. End-of-day flow: option gamma hedging + leveraged-ETF rebalancing
**Thesis:** delta-hedgers and LETF swap counterparties *must* trade into the close in a mechanically
predictable direction, moving the last 30 minutes.

**EXACT RULES** (predictive regression, not yet a packaged strategy)
- Predict `r_end` = stock return **15:30 → 16:00** from:
  - `ΓHP_{j,t}` = delta-hedgers' gamma imbalance in stock j, scaled by the average dollar volume in the
    **last half hour** over the previous month (`ADV_end_{t−1}`);
  - `Ω_LETF_{j,t} = Σ_i L_i(L_i−1)·A_{i,t−1}·w_{i,j,t−1}·r^{pre}_{i,t;bench} / ADV_end_{j,t−1}`
    (LETF rebalancing demand: leverage × AUM × index weight × pre-close benchmark return);
  - control: `r_pre` = return from the previous close to 15:30.
- Direction: LETF flow → **momentum** into the close; short-gamma hedging pressure → amplification; the two
  have opposite signs in their specification.

**MAGNITUDES** — Barbon, Beckmeyer, Buraschi & Moerke, "Liquidity Provision to Rebalancing Flows from
Leveraged ETFs and Equity Options" (WP; the same team's related paper is cited as
"The Role of Leveraged ETFs and Option Market Imbalances on End-of-Day Price Dynamics", Univ. of St. Gallen 2021).
OA: https://abarbon.com/assets/Liquidity_Provision_to_Rebalancing_Flows_from_Leveraged_ETFs_and_Equity_Options.pdf
Sample: options + LETF data spanning **2013–2020**.
- A one-standard-deviation increase in Γ **depresses** end-of-day returns by **−113% of the average
  last-30-minute return**; a one-SD increase in **LETF rebalancing flow raises** end-of-day returns by
  **+430% of the average last-half-hour return**.
- In the return regression: `ΓHP` coefficient **−9.46 (t = −4.71)**, time- and entity-clustered SEs.
- Corroborating evidence in Baltussen et al. (2021) Table: `Indexing_LETF × r_ROD` = **1.79 (t = 2.20)**
  for equity futures (LETF presence amplifies intraday momentum), sample Jun 2006 – May 2020.

**DATA NEEDED:** OptionMetrics (or exchange) open interest + gammas by strike, and LETF AUM/holdings.
**We have neither.** The LETF-only half is cheaper: LETF AUM is public (SSO/SDS/TQQQ/SQQQ 13F+prospectus)
and only needs the index return to 15:30.

**HONEST PRIOR:** Coefficients are expressed as multiples of the *average* last-half-hour return, which is
tiny — so a "430%" effect is not automatically 6 bp. Do NOT queue for backtest until we can compute a bps
figure. Best use: build `Ω_LETF` as a **conditioning filter on candidate #1** rather than a standalone signal.

## 6. Size and illiquidity premia are earned in the last half hour
**Thesis:** anomaly/characteristic returns are not uniform through the day — arbitrageurs de-risk before the
close and the small/illiquid premium spikes into the closing auction.

**EXACT RULES**
- Split each day into 14 intervals: overnight (16:00→9:30) plus thirteen 30-minute intervals.
- Sort stocks on **size** (large/small/micro by NYSE 20th and 50th percentiles, Fama-French 2008 breakpoints)
  and on **illiquidity**; hold the long-short characteristic portfolio **only during 15:30–16:00**.
- Complementary finding: size/illiquidity earn **negative** returns in the **first hour**, but that is
  "only marked on Mondays."

**MAGNITUDES** — Bogousslavsky (2021), *Journal of Financial Economics* 141(1):172–194,
DOI 10.1016/j.jfineco.2020.07.020, "The cross-section of intraday and overnight returns."
OA WP: https://finance.unibocconi.eu/.../The%2520Cross-Section%2520of%2520Intraday%2520and%2520Overnight%2520Returns...pdf
Sample split into pre-1993, 1993–2004, 2005–2015.
- "The bulk of size and illiquidity average returns (alpha) is earned in the last half hour of trading",
  statistically significant across all subsamples and days of the week, robust to excluding January,
  robust to excluding NASDAQ, not limited to extreme deciles.
- Last-half-hour returns increase **monotonically with size**; first-half-hour returns decrease monotonically with size.
- Turnover of small relative to large stocks spikes in the last half hour (the proposed mechanism).
- Accruals and book-to-market are **not** significant over the sample; several anomalies earn large negative
  returns in the last half hour and overnight.
- **Per-interval bps and t-stats: NOT-EXTRACTED** (they live in Table 1 / Figures 1–2, which did not extract as text).

**DATA NEEDED:** 30-min cross-sectional bars + size/illiquidity characteristics + shorting.

**HONEST PRIOR:** Interesting but unquantified for us. Treat as a **timing overlay** on any small-cap
long we already hold (execute buys at the close, not at the open) rather than a new lane.

---

# B) CLOSE-TO-OPEN / OVERNIGHT (buy near close, sell at/near next open)

## 7. **COST REALITY CHECK: the naive SPY overnight trade is net-negative**
Read this before queueing any overnight candidate.

**EXACT RULES TESTED:** buy SPY at the close, sell at the next open, every day.
**MAGNITUDES** — Alpha Architect, "Trading Costs Wipe Out the Overnight Return Anomaly", 16 Jun 2020
(https://alphaarchitect.com/trading-costs-wipe-out-the-overnight-return-anomaly/).
Sample: **SPY, Jan 1993 – Jan 2020, 6,800 days**.
- Gross cumulative return **+717%**. Net of the day's historical bid-ask spread **plus $0.01/share commission:
  −32% cumulative**. Difference **749 percentage points**.
- The overnight return exceeded the intraday return on only **53% of the 6,800 days**.
- They note the academic paper they are testing — "The Overnight Return Temporal Anomaly",
  *International Journal of Economics and Finance* (2017) — **did not include the bid-ask spread** in its cost analysis.
**CAVEAT:** this is a practitioner replication (rigorous, with real spread data), not a peer-reviewed paper,
and I did **not** read the underlying IJEF 2017 article — its own figures are NOT-EXTRACTED.
**HONEST PRIOR:** any overnight candidate must clear ~6 bps *per night* of round-trip cost against a gross
edge measured in single-digit bps per night. Unconditional overnight is dead. Only **conditional/sparse**
versions (candidates 8, 10, 13) have a chance.

## 8. Turn-of-month day-map: short T-8→T-4, long T-3→T-1
**Thesis:** the monthly institutional payment cycle forces selling before month end (price pressure down)
and 401(k)/pension reinvestment after (pressure up).

**EXACT RULES**
- Define **T = the last business day of the month**.
- **Negative** expected market return over **T−8 to T−4** (institutions distribute month-end sales over these days).
- **Positive** expected market return over **T−3 to T−1**; predictability concentrates around the
  **third business day before month end**.
- Long-only implementation: hold the US value-weighted index only during the positive window
  (~**7 days a month**), cash otherwise.
- Conditioners that strengthen it: high **TED spread** (weak funding → bigger reversals); stocks with
  **high mutual-fund ownership**; **larger / more liquid** stocks.

**MAGNITUDES** — Etula, Rinne, Suominen & Vaittinen (2020), *Review of Financial Studies* 33(1):75–111
(RePEc:oup:rfinst:v:33:y:2020:i:1:p:75-111). WP read: "Dash for Cash: Month-End Liquidity Needs and the
Predictability of Stock Returns", 27 Aug 2015, AEA 2016 conference PDF (aeaweb.org/conference/2016/retrieve.php?pdfid=21226).
- "Since July 1926, one could have held the US value-weighted stock index (CRSP) for **only seven days a
  month** and pocketed **the entire market excess return** with **nearly fifty percent lower volatility**
  compared to a buy and hold strategy."
- Return reversals are statistically significant in **22 of 25 international markets**.
- Stocks with greater mutual-fund ownership show more negative T−8→T−4 and more positive T−3→T−1 returns.
- ANcerno trade-level data confirms institutional selling concentrated in the window.
- Exact per-day average return table values: **NOT-EXTRACTED**.

**DATA NEEDED:** daily index closes + a business-day calendar. **We already have everything.** Optional: TED
spread (FRED) and mutual-fund ownership for the conditioners.

**HONEST PRIOR:** **Best cost-survivability of the entire list.** ~2–4 round trips/month against a gross
edge of roughly the whole equity premium: 4 × 6 bps = 24 bps/yr of cost vs ~800 bps of gross.
It is close-to-close, not overnight, so it is a **calendar overlay**, not lane B proper — and the bank
records turn-of-month as retired. The **new** content worth re-testing is (a) the *asymmetric* T−8→T−4 short
window and (b) the TED-spread conditioner, neither of which a plain turn-of-month test would have covered.

## 9. Weekly overnight-return persistence (firm-specific sentiment)
**Thesis:** overnight returns are a clean proxy for retail sentiment, and sentiment persists — so this
week's overnight winners keep winning *overnight* next week.

**EXACT RULES**
- Universe: US stocks; sort each **week w** by that week's **overnight (close-to-open) return**, form **deciles**.
- Hold **overnight-only** positions in **week w+1**: long the top decile, short the bottom decile.
- Persistence decays but remains monotone for **four weeks**.
- Amplifier: effect is significantly larger in the **most-difficult-to-value quartile**
  (proxies: return volatility, firm size, firm age, profitability) and where institutional presence is low.

**MAGNITUDES** — Aboody, Even-Tov, Lehavy & Trueman (2018), *Journal of Financial and Quantitative Analysis*
53(2):485–505, "Overnight Returns and Firm-Specific Investor Sentiment."
Full WP text read (SSRN-id2554010 mirror: https://qiniu-images.datayes.com/SSRN-id2554010.pdf).
- Week w+1 average **overnight** return, top-minus-bottom decile of week-w overnight return: **1.76 percentage points**.
- Robust within characteristic partitions: beta partitions **1.29–1.9 pp**; size partitions **0.98–2.5 pp**;
  book-to-market partitions **1.34–1.8 pp**; monotone increasing across deciles in all cases.
- Difference-in-difference between hardest- and easiest-to-value quartiles: from **0.69 pp** (firm-age sort) upward.
- Sample period: **NOT-EXTRACTED**.

**DATA NEEDED:** daily open and close per stock (i.e. plain daily OHLC). **We have this.** Requires shorting
for the full spread; a long-only top-decile version is testable without shorting but its standalone
magnitude is not reported.

**HONEST PRIOR:** **Marginal.** 176 bps/week gross sounds huge, but holding *overnight only* means 5 entries
and 5 exits per week per leg = up to 10 round trips = **~60 bps/week** of cost for the L/S version — plus this
is a small-cap/hard-to-value effect where 6 bps is optimistic. Worth testing precisely because the data is
free, but test the **long-only, top-decile, weekly-hold** variant (2 round trips/week) rather than the paper's version.

## 10. Long-night / short-day conditioned on upside close-to-close volatility (VOL+)
**Thesis:** the overnight premium is concentrated in stocks with high *upside* realized volatility, so
conditioning on VOL+ sharpens Lou-Polk-Skouras into a tradeable sort.

**EXACT RULES**
- Universe tested: S&P 500 constituents; DJIA; the **123 largest Nasdaq stocks**; five ETFs.
- Signal: **realized upside close-to-close volatility `VOL+`** measured through the close of day t−1.
  Because VOL+ is only known at close t−1, live trading requires a forecast — the thesis uses a
  **HAR-UV-SC** model (HAR with upside-volatility and semi-covariance terms).
- Sort into terciles (and sextiles). In the **high** bucket: **buy at the close of t−1, sell at the open of t**
  (long the night) and **short at the open of t, cover at the close of t** (short the day).
- Rebalance twice per day.

**MAGNITUDES** — Fortuin, D.T. (2023), MSc thesis, Erasmus School of Economics,
"The structure of overnight versus intraday prices", https://thesis.eur.nl/pub/65764/...pdf
Sample **1993–2022** (extends Linton & Wu 2020's 1993–2017).
- High tercile: night-minus-day difference ≈ **0.07%/day** gross ≈ **19%/yr**.
- Top **sextile** (17 stocks): ≈ **0.10%/day** ≈ **29%/yr** gross over the last five years
  (vs S&P 500 8.9%/yr over 5y, 12.5%/yr over 10y). All other sextiles insignificant.
- Author's cost treatment: 0.01% per trade × 2 legs = 0.02%/day → claims **0.08%/day net**, but explicitly
  concedes the bid-ask spread was *not* separately added ("since I use trade data, the bid-ask spread is
  already part of the price") and that "the trading strategy is thus profitable when trading small volumes,
  but will soon become unprofitable when increasing the volumes."
- Using **forecast** VOL+ (HAR-UV-SC) rather than realized VOL+, only the high tercile stays significantly
  positive and "the result is by far not as pronounced" — i.e. the live-tradeable version is much weaker.

**DATA NEEDED:** daily OHLC per stock (have). No intraday data required. Needs **shorting** for the day leg.

**HONEST PRIOR:** **Fails at 6 bp as specified** — 10 bps/day gross against two round trips (~12 bps).
The realized-vs-forecast degradation is the bigger red flag: the author's own OOS-ish test weakens it
substantially. Test only the **overnight leg alone** on the high-VOL+ bucket (1 round trip/day, ~6 bps
against ~5 bps of gross) — likely still negative, so rank it low.

## 11. Daily "tug-of-war" intensity → next-period cross-section
**Thesis:** counting how often a month's days show "positive overnight, negative intraday reversal" measures
the intensity of the fight between overnight noise traders and daytime arbitrageurs; more intense = daytime
arbitrageurs overcorrect = higher future returns.

**EXACT RULES**
- Universe: US common stocks, monthly rebalance.
- Signal: within each month, the **frequency of days on which a positive overnight (close-to-open) return is
  followed by a negative intraday (open-to-close) reversal**. Higher frequency = more intense tug of war.
- Long high-intensity, short low-intensity; hold into the next period (close-to-close).

**MAGNITUDES** — Akbas, Boehmer, Jiang & Koch (2022), *Journal of Financial Economics* 145(3):850–875,
DOI 10.1016/j.jfineco.2021.09.019 (RePEc:eee:jfinec:v:145:y:2022:i:3:p:850-875). Abstract verified on RePEc.
- Portfolio spreads / alphas / t-stats: **NOT-EXTRACTED** — ScienceDirect paywalled and both open-access
  mirrors (SMU `ink.library.smu.edu.sg`, KU ScholarWorks) block automated retrieval (403 / bot wall).

**REPLICATION — the valuable part**
- Hajiyev, Keiber & Luczak (2024), *Quarterly Review of Economics and Finance* 95:234–243
  (RePEc:eee:quaeco:v:95:y:2024:i:c:p:234-243), "Tug of war with noise traders? Evidence from the G7 stock markets":
  **confirms the US result and verifies it in Canada, but the tug of war is NOT predictive of future returns
  in France, Germany, Italy, the UK, or Japan.** Holds in raw returns and after Carhart-4 and Fama-French-6
  risk adjustment. Attributed to institutional/regulatory limits on daytime arbitrage outside North America.
- Kallinterakis et al. (2023), *International Review of Financial Analysis* 85:102450
  (RePEc:eee:finana:v:85:y:2023:i:c:s1057521922003933): SPY **1993–2021** — overnight/daytime reversals are
  driven by **feedback trading**; daytime feedback trading appears when the immediately preceding overnight
  return was positive, and **overnight feedback trading shows a strong Monday effect**. Holds across other large US ETFs.

**DATA NEEDED:** daily open/close per stock (have). Monthly holding period, so cost-light — but it is a
**monthly cross-sectional** strategy, not a same-day/overnight trade. Fit to lane B is indirect.

**HONEST PRIOR:** Cost-survivable (monthly turnover) but I cannot rank it properly without the magnitude.
The G7 failure outside North America is a genuine warning that it is a US-microstructure artifact.
Queue behind #8 and #9; if pursued, get the JFE PDF through a library first.

## 12. Retail trading proportion (RTP) → overnight-minus-intraday return gap
**Thesis:** retail investors want *daytime* exposure and exit before the close ("retail ebb and flow"),
mechanically producing high overnight and low intraday returns in retail-heavy stocks.

**EXACT RULES**
- Signal: `RTP` = retail trading volume / total trading volume, measured over prior days.
- Sort into deciles on past RTP; **long the overnight (close-to-open) leg and short the intraday
  (open-to-close) leg** in high-RTP stocks.
- Persistence: monotone across RTP deciles for horizons **[d+2, d+5]** and **[d+6, d+20]** — so the sort is not
  a one-day flash.

**MAGNITUDES** — Ahn, Fan, Noh & Park, "The Overnight-Intraday Return Gap and the Retail Ebb and Flow",
working paper, **April 2025** (PDF: https://www.kdajdqs.org/bbs/reference/1166/download/2188).
- A **1 pp increase in RTP → ≈ 0.8 bps higher daily return gap the next day**.
- A **1 standard-deviation increase in RTP → ≈ 40% annualized return gap**.
- Retail net buys are persistently **negative in the afternoon** and **positive in the morning** on days
  following high-attention days.
- Data: **Korea** (exchange tags every trade by investor type — retail/foreign/institutional/pension).

**DATA NEEDED:** a US retail-flow proxy. The Boehmer-Jones-Zhang-Zhang TAQ-based retail order-imbalance
algorithm (sub-penny trade classification) — needs **TAQ**, which we do not have. Korea result may not port.

**HONEST PRIOR:** Mechanically the most *believable* explanation for the overnight premium, and the
"40% annualized gap" is a large number — but it is a **gap** (long night + short day = 2 round trips/day),
so cost eats it just like #10, and the data requirement is heavy. Park it until we have TAQ or a
vendor retail-flow feed.

## 13. Day-of-week overnight seasonality: Mon→Tue long, avoid Fri→Mon
**Thesis:** the overnight premium is not uniform across weekdays — it is concentrated Monday-to-Tuesday and
negative Friday-to-Monday (weekend risk premium).

**EXACT RULES**
- Universe: US large-cap stocks and index ETFs (SPY, QQQ, DIA); also Japan/Hong Kong/Singapore/Switzerland index ETFs.
- Rule as stated: **buy in the afternoon of Monday when the instrument's historical Monday overnight return
  profile is positive; sell at the open of Tuesday.** Skip instruments/nights whose profile is negative.
- **Skip Friday→Monday entirely** (negative).
- "3-night model": trade **Monday, Tuesday and Thursday nights only**.
- Reported asset-class caveats: effect is **weak in small caps**; **crypto ETFs invert** (negative Monday
  overnight, positive weekend).

**MAGNITUDES** — Lin, W.J. (2025), *Applied Economics and Finance* 12(3), DOI 10.11114/aef.v12i3.7705
(open access, Redfame). Sample per ticker, earliest **1968**, through **2024**.
- Pattern: statistically significant **positive Monday-to-Tuesday** and **negative Friday-to-next-Monday**
  close-to-next-open returns in US large caps and index ETFs (p < 0.05 for the Panel A1 names).
- 3-night (Mon/Tue/Thu) vs all-nights vs buy-and-hold, in **index points**: BA 483.19 vs 308.82 vs 176.24 (from 1968);
  EEM 70.59 vs 44.69 vs 32.65 (from 2003).
- Overnight share of total return, aggregate across their sample: **73.37%** (3,351.66 of 4,567.96 points).
- **Percentage returns, Sharpe ratios and any transaction-cost analysis: NOT-EXTRACTED — the paper reports
  index POINTS summed over decades, with no cost adjustment.**

**DATA NEEDED:** daily open/close for SPY/QQQ/DIA (have). One round trip per week.

**HONEST PRIOR:** Methodologically the weakest paper on this list (single author, non-elite journal,
points-not-returns, no costs) — but the **structure is exactly what survives cost**: one round trip per week
(~6 bps/wk ≈ 31 bps/yr on SPY) instead of one per night. Worth testing *ourselves* precisely because the
data is free and the turnover is low. Do not trust its numbers; treat it as a hypothesis.
Independent partial support: Kallinterakis et al. (2023) find overnight feedback trading has "a strong
Monday effect" on SPY 1993–2021.

## 14. Gap fade at the open — attention-driven high opens that reverse intraday
**Thesis:** retail attention pushes the *opening price* up relative to intraday prices; the gap then fades
during the day. So the overnight premium and the intraday discount are the same phenomenon.

**EXACT RULES** (as described in the abstract and in Fortuin's review of it — I could not open the paper itself)
- Universe: US stocks, 13 years of intraday data.
- Sort on **retail attention** proxies, **retail buying at the open** (three measures), **short-sale
  constraints** (two proxies), **transaction-cost** measures (three), **hard-to-value** status, sentiment,
  and **institutional ownership** (IO = institutionally held shares / shares outstanding).
- Trade: **short at the open / cover at the close** in high-attention, high-retail-buying, hard-to-value,
  short-sale-constrained names (equivalently: avoid *buying* at the open in those names).
- The one-day reversal is more pronounced for firms that are harder to value and costlier to arbitrage.

**MAGNITUDES** — Berkman, Koch, Tuttle & Zhang (2012), "Paying Attention: Overnight Returns and the Hidden
Cost of Buying at the Open", *Journal of Financial and Quantitative Analysis* 47(4):715–741
(RePEc:cup:jfinqa:v:47:y:2012:i:04:p:715-741_00), DOI 10.1017/S0022109012000270.
- **All numeric magnitudes NOT-EXTRACTED.** Cambridge Core, JSTOR and KU ScholarWorks all blocked automated
  retrieval (bot walls / HTML interstitials). The sorting-variable list above is sourced from
  Fortuin (2023) pp. 16 and the RePEc/publisher abstract, both of which I read directly.

**DATA NEEDED:** daily open/close per stock (have) for the basic gap-fade; attention proxies (Google Trends /
news counts / abnormal volume), institutional ownership (13F), short-interest — partially available.
Requires **shorting**.

**HONEST PRIOR:** This is the canonical academic basis for "fade the gap", and its own title says the effect
is a *cost*, not a profit — the whole point is that the opening price is bad for buyers. Shorting at the open
in hard-to-value, short-sale-constrained names is precisely where borrow costs and 6 bps become 30 bps.
Prior: **does not survive as a standalone short**; high value as a rule to **never execute buys at the open**.

## 15. Closing-auction order imbalance → next-day return
**Thesis:** imbalance in the closing auction creates price pressure at the close that has not fully reverted
by the next session, so the signed auction imbalance predicts the next day's return.

**EXACT RULES**
- Signal: the exchange's **published closing-auction imbalance report** — use the **last report of the day**.
- Sign it: the reported imbalance is always positive, so multiply by −1 when sell-initiated orders dominate.
- Filter: **drop observations where |closing-auction imbalance| > 100% of that day's trading volume** (outliers).
- Prediction target: the **next trading day's** return (positive relation).

**MAGNITUDES** — Majorin, J. (2022), BSc thesis, Aalto University School of Business,
"Order imbalance and stock returns: Evidence from the Finnish stock market" (aaltodoc, 27+5 pp).
Sample: **Finnish Nasdaq stocks, 2010–2013**, Nasdaq Nordic ITCH data, fixed-effects panel regressions with
lags to the 5th lag.
- Finding as stated: "order imbalance at the closing auction **causes a price pressure, which spills over into
  the next trading day, affecting the next day's return positively**."
- **Coefficients / t-stats / economic magnitude: NOT-EXTRACTED** (Table 4 values did not extract cleanly).
- Related, cited: Jegadeesh & Wu (2021) find auction imbalance significantly predicts the closing price;
  Bogousslavsky & Muravyev (2023), *Journal of Financial Markets* 66:100852
  (RePEc:eee:finmar:v:66:y:2023:i:c:s1386418123000502) document closing auctions at **7.5% of daily volume in
  2018 (up from 3.1% in 2010)**, that **closing-price deviations fully revert overnight**, and that
  put-call-parity violations at the close **predict next-day stock returns**.

**DATA NEEDED:** US closing-auction imbalance feed (Nasdaq Net Order Imbalance Indicator / NYSE closing
imbalance publications, disseminated from ~15:50). **We do not have this.** Small universe, non-US sample.

**HONEST PRIOR:** Weakest evidence base (bachelor thesis, 4 years, Finland) but the *mechanism* is
well-supported by Bogousslavsky-Muravyev in a top journal, and the "closing-price deviations fully revert
overnight" result is a **direct close-to-open signal** — arguably the cleanest theoretical basis for lane B
on this list. Rank low on evidence, high on interest; the blocker is data acquisition, not logic.

---

## Cross-cutting conclusions

1. **The 6 bp bar is brutal and most of this literature knows it.** Three separate papers measure or concede
   cost failure in their own text: Heston-Korajczyk-Sadka (−14 to −25 bps after spread), Baltussen-Soebhag-Da
   ("might not be exploitable"), Baltussen et al. 2021 ("we do not consider transaction costs").
   Alpha Architect quantifies it for the naive overnight trade: **+717% gross → −32% net**.
2. **Only two candidates have gross edge comfortably above 2 round trips of cost:** #1 (MIM on r_ROD, *in
   futures only* — 2.7 bps/day gross means the SPY version dies) and #8 (turn-of-month, ~4 round trips/year).
3. **Turnover structure beats effect size.** #13 (one round trip per week) is a far worse paper than #3 (t-stat
   17) but has a far better chance of surviving costs. Prioritize sparse-trading candidates.
4. **Conditioning is where the surviving alpha is.** The single most striking result found: intraday momentum
   is essentially **zero when dealer net gamma exposure is positive** (β 0.82, t 1.03, R² 0.05%) and strong
   when negative (β 6.63, t 4.78, R² 3.58%). An unconditional MIM backtest averages these two regimes and
   will look mediocre for the wrong reason.
5. **Documented replication failures to respect:** Gao et al. fails/weakens in Hong Kong, Singapore, and under
   COVID (Limkriangkrai 2023) and OOS for the always-on rule (Rosa 2022); Akbas et al. fails in France,
   Germany, Italy, UK and Japan (Hajiyev 2024); the ORB result is not robust across sub-periods (Holmberg 2013).
6. **Hard-for-us flags:** #3, #6, #14 need a broad intraday cross-section plus **short selling**; #5 needs
   OptionMetrics; #12 needs TAQ retail classification; #15 needs an auction-imbalance feed.
   **None of the 15 requires sub-minute data** — 30-minute bars are sufficient everywhere except #15.

## Recommended backtest order
1. **#8 turn-of-month T-day map** — daily data in hand, cost-survivable, quick.
2. **#1 MIM on r_ROD, MES/ES only** — 30-min bars in hand; compare r_ROD vs r_ONFH head-to-head; stratify by volatility.
3. **#13 Mon→Tue overnight on SPY/QQQ/DIA** — free data, one round trip/week, verify the paper's claim in percent terms ourselves.
4. **#9 Aboody weekly overnight persistence, long-only top decile** — daily OHLC, no shorting.
5. Everything else: blocked on data or already cost-failed. **#3 and #14 should be adopted as execution rules
   (never buy at the open; buy intraday losers at 15:30) rather than as lanes.**
