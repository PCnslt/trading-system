# Short-Horizon Return Predictors & Anomalies — Literature Review & Testable Strategy Specs

**Prepared:** 2026-08-24 · **Mode:** Yale/Harvard-rigor (SSRN, NBER, JFE, JF, RFS, RePEc)
**Data available for testing:** 20y+ daily US equities (S3 `ibkr/eq/`); ~1y MES/MNQ/ES/NQ intraday RTH bars (1h/15m/5m/1m, S3 `futures-bars/`); options chains; orderbook depth; news; fundamentals.

**Ranking legend:** candidates are ordered by (i) short-horizon fit, (ii) replication robustness, (iii) our testability. Each is flagged **SHORT** (intraday–5 days, actionable now) or **LONG** (multi-week/month formation — skip for short-horizon deployment).

---

## RANK 1 — Weekly short-term reversal (Lehmann 1990; Jegadeesh 1990)

**Full citation:**
- Lehmann, Bruce N. (1990). "Fads, Martingales, and Market Efficiency." *Quarterly Journal of Economics* 105(1), 1–28. NBER WP 2533 (1988). JSTOR 2937816.
- Jegadeesh, Narasimhan (1990). "Evidence of Predictable Behavior of Security Returns." *Journal of Finance* 45(3), 881–898. DOI 10.1111/j.1540-6261.1990.tb05110.x.

**What it is.** Stocks that are "winners" over the past week reverse and underperform over the next week; past "losers" outperform. This is the canonical short-term reversal effect (distinct from 3–12-month momentum).

**Exact rules (Lehmann 1990):**
- **Universe:** NYSE/AMEX common stocks (later replicated on NASDAQ/CRSP all-firms). Exclude micro/illiquid names in practice.
- **Signal/formation:** rank on prior **one-week** (5 trading days) return.
- **Portfolio construction:** costless (zero-net-investment) portfolio — **short prior-week winners, long prior-week losers**; weights proportional to (negative of) each stock's return deviation from the equal-weighted cross-sectional mean (Lehmann's weighting) or simple decile/decile spread.
- **Entry:** start of next week (Monday open or prior Friday close).
- **Exit / holding period:** **one week** (rebalance weekly).
- **Time-of-day:** none specified (close-to-close returns). Rebalance at close or next open.

**Reported magnitude:**
- Lehmann: prior-week winners earn ≈ **−0.55%/week** in the following week (NBER w2533 Table 1, "Winners −0.0055"), with losers earning positive returns of similar magnitude; the costless long-losers/short-winners spread is **≈1.5–2%/week gross** before transaction costs (profits persist after bid-ask/thin-trading corrections but are consumed by realistic costs at high turnover — the paper emphasizes this is evidence of inefficiency, not a free lunch).
- Jegadeesh: **~2%/month** abnormal return for the monthly reversal strategy, 1934–1987 (negative first-order monthly serial correlation).

**Sample + significance:** Lehmann 1962–1986, NYSE/AMEX, statistically significant (arbitrage profits survive return-mismeasurement corrections). Jegadeesh 1934–1987, significant negative serial correlation.

**Replication robustness:** *Very high.* Replicated for decades; still present out-of-sample (e.g., Nagel 2012 *RFS* — liquidity provision explains much of it; Da, Liu & Schaumburg 2014). This is the most robust short-horizon effect in the literature.

**Our testability:** *Excellent.* We hold 20y+ daily US equities — compute 5-day return, weekly-rebalanced long-losers/short-winners decile spread, with market-cap/price filters. **SHORT horizon (weekly), directly testable today.**

---

## RANK 2 — Market intraday momentum (Gao, Han, Li & Zhou 2018)

**Full citation:**
Gao, Lei, Yufeng Han, Sophia Zhengzi Li, and Guofu Zhou (2018). "Market intraday momentum." *Journal of Financial Economics* 129(2), 394–414. DOI 10.1016/j.jfineco.2018.05.009. (SSRN 2440866.)

**What it is.** Time-series predictability of the *market* (S&P 500): the **first half-hour return** (measured from the prior day's close) predicts the **last half-hour return** of the same day.

**Exact rules:**
- **Universe:** SPDR S&P 500 ETF (**SPY**) — also replicated on 10 other most-actively-traded US & international ETFs (QQQ, DIA, etc.). We can substitute **ES / MES / NQ / MNQ futures** (the underlying is the same S&P 500 / Nasdaq exposure, but see caveats).
- **Signal:** `r_first` = market return from **previous day's close → 10:00 ET** (i.e., overnight gap + first 30 min of RTH). Computed with 30-min bars.
- **Predicted variable:** `r_last` = return from **15:30 → 16:00 ET** (last half hour of RTH).
- **Entry:** at the start of the last half hour (**15:30 ET**) on days when the signal direction is set.
- **Direction:** long (buy) the last half hour if `r_first > 0`; short if `r_first < 0`.
- **Exit / holding period:** **30 minutes** (exit at 16:00 ET close). Fully intraday, same-day round trip.
- **Conditioning (stronger signal):** predictability is stronger on high-volatility days, high-volume days, recession days, and major macro-news-release days — a filtered version trading only on strong-signal days is more robust (see Rosa 2022 below).

**Reported magnitude:**
- Predictive **R² = 1.6%** of the first-half-hour return for the last-half-hour return — "matches or exceeds typical predictive R²s at the monthly frequency" (abstract, verified).
- Statistically and economically significant; last-half-hour return is reliably positive (negative) following positive (negative) first-half-hour returns.

**Sample + significance:** SPY intraday 30-min data, **1993–2013**; significant; holds across the 10 additional ETFs.

**Replication robustness:** *Mixed — flag prominently.*
- **Rosa (2022), "Understanding intraday momentum strategies," *Journal of Futures Markets* 42(12), 2218–2234 (DOI 10.1002/fut.22375):** finds the predictability **disappears out-of-sample** for the always-on rule; a Markov-switching model shows the effect is regime-dependent, and a **thresholded strategy (trade only on strong signals) beats the always-active strategy.**
- Limkriangkrai, Chai & Zheng (2023), "Market intraday momentum: APAC evidence," *Pacific-Basin Finance Journal* 80, 102086: effect mainly in **China & Japan**, weak/absent in Korea/HK/Singapore, and **weaker in COVID** period — i.e., not pervasive globally.
- Onishchenko (2021), *International Review of Financial Analysis*: early-morning-return timing strategies still show superior last-half-hour performance in that sample.

**Our testability:** *Good, with two caveats.* (1) We have **ES/MES/NQ/MNQ 1m/5m RTH bars** — the 9:30–10:00 and 15:30–16:00 windows are in RTH; the overnight gap (prior close→9:30 open) comes from daily data. Signal = (overnight gap) + (9:30–10:00 RTH return). (2) The original uses SPY cash; futures trade ~23h, so "last half hour" must be defined on RTH 15:30–16:00 ET. **SHORT horizon (30-min), actionable, but treat as regime/threshold-dependent (apply Rosa's filter).**

---

## RANK 3 — The Overnight Drift (Boyarchenko, Larsen & Whelan 2023, RFS)

**Full citation:**
Boyarchenko, Nina, Lars C. Larsen, and Paul Whelan (2023). "The Overnight Drift." *Review of Financial Studies* 36(1), 215–261. DOI 10.1093/rfs/hhad020. (SSRN 3560269, 2020.) Follow-up: Boyarchenko, Larsen & Whelan (2026), "The Disappearing Overnight Drift," *Liberty Street Economics*, NY Fed.

**What it is.** Essentially **all of the US equity risk premium is earned in a single 1-hour overnight window**, 2:00–3:00 a.m. ET, around the **European (Frankfurt/London) open**. Mechanism (inventory risk): liquidity providers absorb end-of-day order imbalance at a discount, carry inventory overnight, and are compensated when European demand arrives at ~2:00 ET.

**Exact rules:**
- **Universe:** S&P 500 **E-mini futures** (ES); effect also documented in other index futures.
- **Entry:** **2:00 a.m. ET**.
- **Exit / holding period:** **3:00 a.m. ET** — one hour.
- **Time-of-day:** strictly overnight/globex session (NOT RTH).
- **Model-implied conditional signal (for a smarter version):** expected overnight return = (closing **dollar order imbalance**) × (**return variance**) × (**liquidity-provider risk-bearing capacity**)^−1. Higher closing imbalance / variance → larger expected overnight drift.

**Reported magnitude:**
- The 2:00–3:00 a.m. window generated **≈3.7% per annum** (1998–2020), representing ~100% of the total US equity premium (the rest of the 24h day nets to ≈0).

**Sample + significance:** S&P 500 E-mini futures, **1998–2020** (5,691 trading days); highly significant.

**Replication robustness:** *Published in RFS (peer-reviewed), but POST-2021 FADE is documented by the authors themselves.* The NY Fed follow-up (2026) shows the 2:00–3:00 window has averaged **≈0 since 2021** — the drift "disappeared" as one of the three channels (closing order-imbalance dispersion, variance, or LP risk capacity) collapsed. **This is a genuine, replicated, but currently-dormant effect.**

**Our testability:** *Partial — data constraint.* We hold ES/MES/NQ 1m/5m bars but they are **RTH only** (9:30–16:00). The 2:00–3:00 a.m. window is in the **globex/overnight session**, which we do **not** appear to hold. **To test we need CME globex (23h) minute bars.** Otherwise we can only proxy via daily open gaps. **SHORT horizon (1 hour), but blocked by missing overnight-session data — flag for data acquisition.**

---

## RANK 4 — Overnight vs. intraday return continuation ("Tug of War") — Lou, Polk & Skouras 2019

**Full citation:**
Lou, Dong, Christopher Polk, and Spyros Skouras (2019). "A Tug of War: Overnight Versus Intraday Expected Returns." *Journal of Financial Economics* 134(1), 192–213. DOI 10.1016/j.jfineco.2019.03.011.

**What it is.** Decompose each firm's close-to-close return into an **overnight component** (close→open) and an **intraday component** (open→close). Each component **continues** in its own period and **reverses** in the other period, persistently (up to 5 years).

**Exact rules (firm-level continuation):**
- **Universe:** CRSP US common stocks (value-weighted deciles); replicated in 9 non-US markets (CA, FR, DE, IT, UK, AU, HK, JP, ZA).
- **Signal:** rank stocks on **past one-month overnight return** (close-to-open) — or, symmetrically, past one-month intraday return (open-to-close).
- **Long leg:** top decile of past overnight (intraday) return; **short leg:** bottom decile.
- **Entry:** next month; **exit/holding:** **1 month** (rebalance monthly). **LONG-horizon formation (1 month), even though the payoff accrues in specific intraday/overnight windows.**

**Reported magnitude (verified from FMG DP744 / JFE text):**
- Overnight WML (long past-overnight winners, short losers): **overnight 3-factor alpha +3.47%/mo (t=16.83)**, intraday 3-factor alpha **−3.02%/mo (t=−9.74)**.
- Intraday WML: **intraday alpha +2.41%/mo (t=7.70)**, overnight alpha **−1.77%/mo (t=−7.89)**.
- Persistence survives lags of up to **60 months** (joint t > 20).

**"Tug of War" strategy-timing overlay (the published JFE headline result):**
- Construct `TugOfWar_t` = **EWMA of (overnight component) minus EWMA of (intraday component)** of a strategy, half-life **60 months**.
- It **forecasts next-month close-to-close strategy returns**: a **+1 SD** increase in the smoothed overnight−intraday spread forecasts a **+1% higher** next-month close-to-close return (≈18% of monthly return volatility). Sign is positive for overnight-premium strategies (momentum, short-term reversal) and negative for intraday-premium strategies (size, value, profitability, beta, IVOL, etc.).

**Sample + significance:** US daily data ~1990s–2010s; t-stats in the 7–17 range; replicated internationally.

**Replication robustness:** *High* (JFE, large t-stats, international replication). But the *tradeable* firm-level signal is **monthly**, not short-horizon. The value for a short-horizon desk is the **overnight-vs-intraday decomposition insight** (e.g., "earn this premium overnight, not intraday").

**Our testability:** *Good for the decomposition; LONG-horizon for the signal.* With 20y+ daily OHLC US equities we can compute overnight = open/prior_close and intraday = close/open, and run the 1-month continuation and the TugOfWar timing overlay. **Flag: LONG (1-month formation/60-month EWMA) — treat as a portfolio-construction/timing insight, not an intraday trade.**

---

## RANK 5 — Overnight effect & overnight-return persistence at the individual-stock level ("Night Moves", Haghani et al. 2022)

**Full citation:**
Haghani, Victor, Vladimir Ragulin, and Richard Dewey (2022). "Night Moves: Is the Overnight Drift the Grandmother of All Market Anomalies?" *SSRN* 4139328 (Elm Wealth working paper). **Not peer-reviewed.**

**What it is.** The aggregate overnight effect (all equity returns earned while market closed) also appears as **persistence at the individual-stock level** — a long/short portfolio sorted on overnight-vs-intraday return patterns.

**Exact rules:**
- **Universe:** US individual stocks (meme/high-attention names show the effect most strongly).
- **Signal:** rank stocks on recent **overnight (close→open) vs. intraday (open→close) return** persistence (long stocks with persistent overnight outperformance, short the opposite).
- **Entry/exit:** daily rebalancing; hold overnight session (buy at close, sell at next open) to harvest overnight return only.

**Reported magnitude:**
- Long/short portfolio testing overnight-vs-intraday persistence: **≈38%/year gross** (before transaction costs, no leverage), "Sharpe high enough to make an efficient-markets economist blush." Authors stress this is **gross** and that capturing much of it requires leverage, diversification, signal refinement, and low costs.

**Sample + significance:** US equities ~1990s–present; descriptive/working-paper rigor (not peer-reviewed).

**Replication robustness:** *Low–moderate.* SSRN working paper; related academic support (Lou-Polk-Skouras; Berkman et al. 2012; Cliff et al. 2008) but the specific 38% number is pre-cost and unreviewed.

**Our testability:** *Good* — 20y+ daily OHLC US equities give overnight (open/prev close) and intraday (close/open) returns for a daily-rebalanced overnight-harvesting strategy. **SHORT horizon (overnight), but pre-cost and unreviewed — validate carefully.**

---

## RANK 6 — Overnight returns as firm-specific sentiment (Aboody, Even-Tov, Lehavy & Trueman 2018)

**Full citation:**
Aboody, David, Omri Even-Tov, Reuven Lehavy, and Brett Trueman (2018). "Overnight Returns and Firm-Specific Investor Sentiment." *Journal of Financial and Quantitative Analysis* 53(2), 485–505. DOI 10.1017/S0022109017000986.

**What it is.** Overnight (close→open) returns proxy for **firm-specific retail/investor sentiment**. High overnight returns → temporary sentiment-driven overpricing.

**Exact rules:**
- **Universe:** US common stocks; effect stronger for **harder-to-value** firms (small, young, high-volatility, low-analyst-coverage).
- **Signal:** recent **overnight return** (close→open), short-horizon window.
- **Short-horizon trade (persistence):** overnight returns exhibit **short-term persistence** → go long recent overnight winners over days.
- **Long-horizon trade (reversal):** stocks with **high** overnight returns **underperform** over the **longer term**; low-overnight-return stocks outperform → long low-overnight / short high-overnight.

**Reported magnitude:** Persistence and long-horizon reversal both statistically significant; magnitude reported in tables (paywalled); the effect is monotonic across sentiment-sensitivity sorts.

**Sample + significance:** US, ~2000s–2010s; significant.

**Replication robustness:** *Moderate.* JFQA (peer-reviewed); conceptually overlaps Lou-Polk-Skouras and Berkman et al. The short-term persistence leg is short-horizon; the reversal leg is long-horizon.

**Our testability:** *Good* — daily OHLC data suffices. **Mixed horizon: short-term persistence = SHORT; long-term reversal = LONG.**

---

## RANK 7 — Cross-sectional "tale of night and day" (Hendershott, Livdan & Rösch 2020) & end-of-day mispricing decay (Bogousslavsky 2021)

**Full citations:**
- Hendershott, Terrence, Dmitry Livdan, and Dominik Rösch (2020). "Asset pricing: A tale of night and day." *Journal of Financial Economics* 138(3), 635–662. DOI 10.1016/j.jfineco.2020.06.006. (SSRN 3117663.)
- Bogousslavsky, Vincent (2021). "The cross-section of intraday and overnight returns." *Journal of Financial Economics* 141(1), 172–194. DOI 10.1016/j.jfineco.2020.07.020.

> **Note on the task's citation:** the task attributed "The cross-section of intraday and overnight returns" to Hendershott, Livdan & Rösch. The correct titles are: Hendershott-Livdan-Rösch = *"Asset pricing: A tale of night and day"* (JFE 2020); Bogousslavsky = *"The cross-section of intraday and overnight returns"* (JFE 2021). Both are covered here.

**What they are (structural, cross-sectional — NOT simple tradeable signals):**
- **Hendershott et al.:** CAPM fails on 24h returns but works *within* sessions — stock returns are **positively** related to beta **overnight** and **negatively** related to beta **intraday**. The implied risk-free rate also differs night vs. day (confirmed in Treasury futures). Implication: high-beta stocks earn their premium overnight and give it back intraday.
- **Bogousslavsky:** a **mispricing/anomaly factor earns positive returns intraday but performs poorly at the END of the day**, because arbitrageurs de-risk before the close (overnight margin costs, lending fees). This "end-of-day decay" strengthens in the second half of the sample and is shared by many anomalies.

**Exact rules (if operationalized):**
- **Hendershott:** sort stocks on **market beta**; **long high-beta / short low-beta overnight** (close→open), reverse intraday (open→close). Daily rebalance.
- **Bogousslavsky:** for any anomaly long-short factor, harvest returns **intraday but exit before the last ~30–60 min** (the "end-of-day decay" window).

**Reported magnitude:** Beta premium sign-flip and end-of-day anomaly decay both statistically significant; magnitudes in tables (paywalled).

**Sample + significance:** Hendershott: US + international, ~1990s–2010s, significant. Bogousslavsky: US, significant, strengthens over time.

**Replication robustness:** *Moderate–high* (both JFE); these are structural decompositions more than standalone anomalies.

**Our testability:** *Moderate.* Needs factor/beta construction (daily data OK) and, for Bogousslavsky, intraday timing of anomaly portfolios. **Flag: cross-sectional/structural; medium effort. Not a plug-and-play short-horizon signal.**

---

## RANK 8 — (Framework, not an anomaly) Berk & van Binsbergen 2016

**Full citation:**
Berk, Jonathan B., and Jules H. van Binsbergen (2016). "Assessing Asset Pricing Models Using Revealed Preference." *Journal of Financial Economics* 119(1), 1–23. DOI 10.1016/j.jfineco.2015.08.010. (NBER WP 20435.)

**What it is.** A **methodology** (measuring mutual-fund flows as "revealed preference" to test which asset-pricing model investors actually use), **not a return predictor**. It is cited in the overnight-anomaly literature as a valuation/flow-measurement tool, not as a tradeable effect. **FLAG: not a short-horizon (or any-horizon) anomaly — skip.**

---

## POST-2020 SSRN working papers proposing NEW short-horizon anomalies

1. **Boyarchenko, Larsen & Whelan — "The Overnight Drift"** (SSRN 3560269, 2020 → published *RFS* 2023). *Covered above (Rank 3).* The single best post-2020 short-horizon finding.
2. **Haghani, Ragulin & Dewey — "Night Moves"** (SSRN 4139328, 2022). *Covered above (Rank 5).*
3. **"Cross-Market Intraday Time-Series Momentum"** (SSRN 4651331): the US market's **last half-hour return predicts the next day's first half-hour returns in international markets** — a cross-market intraday spillover signal. Post-2020, unreviewed.
4. **"Intraday Market Return Predictability Culled from the Factor Zoo"** (SSRN 4465545): time-series predictability of intraday aggregate-market return from a broad set of anomaly factors. Post-2020, unreviewed.
5. **Barbon et al.** (Andrea Barbon's working papers): ETF/mandate rebalancing flows **"induce significant end-of-day momentum and mean-reversion in stock returns, dissipating within the next trading day"** — a concrete end-of-day (last 30 min) signal. Post-2020, unreviewed.
6. **Rosa 2022 (*J. Futures Markets*)** — negative/replication result (OOS decay of Gao et al.), valuable as a **robustness caution**, not a new signal.

---

## Consolidated ranking table

| # | Candidate | Horizon | Peer-reviewed? | Replication | Our testability | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Weekly reversal** (Lehmann 1990 / Jegadeesh 1990) | 1 week | Yes (QJE/JF) | Very high | Excellent (daily data) | **SHORT — deploy first** |
| 2 | **Market intraday momentum** (Gao et al. 2018) | 30 min | Yes (JFE) | Mixed (OOS decay) | Good (ES/MES RTH bars) | **SHORT — thresholded only** |
| 3 | **Overnight Drift** (Boyarchenko et al. 2023) | 1 hour | Yes (RFS) | Replicated but fading post-2021 | Blocked (need globex bars) | **SHORT — need data** |
| 4 | **Overnight/intraday continuation** (Lou et al. 2019) | 1 month formation | Yes (JFE) | High | Good (daily OHLC) | **LONG — decomposition insight** |
| 5 | **Overnight persistence L/S** (Haghani et al. 2022) | Overnight | No (SSRN) | Low | Good (daily OHLC) | **SHORT — pre-cost, unreviewed** |
| 6 | **Overnight sentiment** (Aboody et al. 2018) | days / long | Yes (JFQA) | Moderate | Good | Mixed horizon |
| 7 | **Night/day beta** (Hendershott et al. 2020) + **EOD decay** (Bogousslavsky 2021) | intraday | Yes (JFE ×2) | Moderate | Moderate | **Structural — high effort** |
| 8 | **Berk & van Binsbergen 2016** | n/a | Yes (JFE) | n/a | n/a | **Not an anomaly — skip** |

---

## Bottom line for the trading system

1. **Start with weekly short-term reversal (Rank 1)** — it is the only candidate that is simultaneously (a) truly short-horizon, (b) peer-reviewed and heavily replicated, and (c) fully testable on data we already hold (20y+ daily US equities). Expect the raw spread to be large but eaten by turnover costs — test with realistic cost models and liquidity filters.
2. **Intraday momentum (Rank 2) is the best genuinely-intraday effect** and maps to our ES/MES/NQ 1m/5m RTH bars, but *do not run it always-on*: apply Rosa (2022)'s signal-strength threshold and volatility/volume conditioning.
3. **The Overnight Drift (Rank 3) is the most attractive magnitude-per-hour effect** but requires CME **globex overnight minute bars**, which we appear not to hold — acquire them before building anything.
4. **Lou-Polk-Skouras (Rank 4)** should be read as a *portfolio-timing overlay* (earn premiums overnight vs. intraday; use the TugOfWar EWMA to time factor exposure) rather than a standalone short-horizon signal — its formation is monthly.
5. **Skip Berk & van Binsbergen** (methodology, not an anomaly) and treat the unreviewed post-2020 SSRN items (Rank 5, cross-market intraday TSM, Barbon EOD) as validation candidates only.

### Honesty caveats
- Exact **Sharpe ratios / portfolio-formation returns for Gao et al., Hendershott et al., Bogousslavsky, and Aboody et al.** live in **paywalled tables** I could not open (ScienceDirect/SSRN bot-blocked). The numbers I report above (R², alphas, t-stats, per-annum windows) are **verified from abstracts, RePEc, NBER, and open-access working papers**; the remaining table-level magnitudes are flagged where cited as qualitative.
- No figures in this report were invented; every number is traceable to the cited abstract/working paper/journal page.
