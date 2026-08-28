# Cross-Sectional Equity Factors: Post-Publication, Cost-Aware Reality and Portfolio Construction

Prepared for a small (~$700) long-only fractional account with a 1–5 day holding horizon.

---

## 0. Bottom line up front

- Momentum, value, quality, low-vol, and reversal are all **real, well-documented** cross-sectional effects — but their *gross* (pre-cost) academic returns are a poor guide to what is *actually harvestable today*.
- The single best estimate of harvestable returns is brutal: after effective bid–ask spreads, post-publication decay, and the modern trading-technology era, the **average stock-market anomaly nets ~4 basis points per month**; the **strongest individual anomalies net ~10 bps/month**, and **combining anomalies nets ~20 bps/month (~2.4%/yr, long–short)**.[11]
- Post-publication, portfolio returns fall **26% out-of-sample and 58% after publication** (with ~32% attributable to publication-informed trading).[9]
- The operator's failed single-signal mean-reversion test is **the expected outcome**, not a bug: short-horizon reversal is the highest-turnover, most bid–ask-spread-sensitive strategy, and it is precisely the kind that does **not** survive trading costs.[2][10]
- On a **$700 long-only account held 1–5 days**, the realistic net expectation of these factors is **≈ zero to negative after costs**. They are real at institutional scale; they are not harvestable under these constraints (details in §5).

---

## 1. Ground rules: what "a factor" actually means

All five factors share mechanics that matter for feasibility:

- **Cross-sectional sort** over the broad CRSP universe (thousands of stocks), ranked on a signal, long the top decile/tercile, short the bottom, **rebalanced monthly** (value/quality often annual/semi-annual).[1][17]
- Returns are quoted as **long–short spread**; a **long-only** implementation captures roughly **half** the spread (and often less, because the short leg is disproportionately important for momentum and low-vol).
- Gross academic returns are measured **before** transaction costs, price impact, and short-sale costs — the gap between gross and net is exactly where most of the edge dies.[10][11][16]

---

## 2. The five factors: rule, gross evidence, and realistic net

### 2.1 Momentum (cross-sectional, "12–1")
- **Rule:** rank stocks on cumulative return from t−12 to t−1 (skip the most recent month), long winners / short losers, rebalance monthly. Positive over 3–12 month horizons; part of the abnormal return dissipates over the following two years.[1]
- **Gross evidence:** large and significant in the original sample.[1]
- **Reality:** momentum has **very high turnover**, suffers **infrequent but severe crashes** (panic states, market rebounds — e.g. it can lose most of its multi-year gains in weeks),[14] and is among the most heavily decayed factors post-publication.[9] High-turnover strategies rarely generate significant net returns after costs.[10] Long-only momentum on a 1–5 day hold is *not momentum* — it is short-term reversal (§2.5), the worst net performer.

### 2.2 Value (book-to-market / HML)
- **Rule:** rank on book-to-market (or earnings yield), long cheap / short expensive; the HML factor is a cornerstone of the Fama–French three-factor model.[17]
- **Gross evidence:** a foundational, long-documented premium.[17]
- **Reality:** value is the **cheapest to trade** (low turnover) and has the **greatest capacity** to absorb new capital; strategies based on size, value, and profitability survive costs best.[10] Caveat: value has been in a long weak patch in recent decades, and its performance improves dramatically once you **control for profitability** (cheap-and-profitable vs. cheap-and-junky).[5]

### 2.3 Quality / profitability
- **Rule:** rank on gross profitability (gross profits / assets) — it has "roughly the same power as book-to-market" for predicting returns;[5] the Quality-Minus-Junk (QMJ) composite adds growth and safety.[6]
- **Gross evidence:** high-quality stocks earn high risk-adjusted returns; QMJ is a significant factor.[6]
- **Reality:** low-to-moderate turnover, high capacity, holds up well post-publication.[10] **Quality is the most robust long-only building block** — it strengthens value when the two are combined.[5]

### 2.4 Low-vol / low-beta
- **Rule:** rank on beta (Betting-Against-Beta: long leveraged low-beta, short high-beta)[7] or on idiosyncratic volatility — stocks with high idiosyncratic vol earn "abysmally low" average returns.[4]
- **Gross evidence:** BAB produces significant positive risk-adjusted returns;[7] the IVOL effect is robust to size, B/M, momentum, liquidity controls.[4]
- **Reality:** low-vol is real but **capacity-constrained** (concentrated in large, liquid names), its short leg (high-vol junk) drives much of the return, and long-only low-vol mostly *lowers volatility* rather than *raising return*. Overlaps heavily with value/quality.

### 2.5 Reversal
- **Short-term (weekly/monthly):** negative first-order serial correlation is highly significant; the extreme-decile spread was **2.49%/month gross (1934–1987)**.[2]
- **Long-term (3–5 yr):** "losers" outperform "winners" over multi-year horizons (De Bondt–Thaler overreaction).[3]
- **Reality:** the **short-term version is the textbook un-tradeable anomaly** — its entire edge lives inside the bid–ask spread (microstructure/bid–ask bounce), turnover is the highest of any factor, and it is exactly the strategy that fails net of costs.[2][10] Long-term reversal is low-turnover but is largely a repackaged value trade and requires a 3–5 year horizon — incompatible with a 1–5 day hold.[3]

---

## 3. How to combine them into a portfolio

1. **Exploit the negative correlation between value and momentum.** Value and momentum are negatively correlated within and across eight asset classes, so combining them materially raises the Sharpe ratio versus either alone.[8]
2. **Composite-score (recommended).** Z-score each signal cross-sectionally, average into a single composite score, then long the top names / short the bottom. This is how QMJ[6] and the "value-and-momentum-everywhere" strategy[8] are built. A composite of value + quality + low-vol (+ a light momentum sleeve) is the standard "multi-factor" product.
3. **Prefer 1/N or equal-weight sleeves over optimized weights.** Out of sample, no optimization model consistently beats the naive 1/N portfolio once estimation error is accounted for.[15]
4. **Control turnover — it is the single most effective cost mitigation.** A **buy/hold spread** (tighter bar to enter a position than to stay in it) is the most effective simple cost-reduction technique; most anomalies only generate significant net returns when one-sided monthly turnover is **under ~50%**.[10]
5. **Set the honest ceiling on expectations:** even well-executed anomaly *combinations* net only ~20 bps/month (~2.4%/yr) long–short — and that is at institutional scale with cost mitigation.[11]

---

## 4. Data-mining and replication caveats (why "gross" numbers lie)

- A new factor must now clear a **t-statistic > 3.0** (vs. the old 2.0) to be credible, because hundreds of factors have been tried; "most claimed research findings in financial economics are likely false."[12]
- Roughly **half of ~80 well-known anomalies are insignificant** in the broad cross-section once properly tested.[13]
- Post-publication decay is large and systematic: **26% out-of-sample, 58% post-publication**, with decay concentrated in the highest in-sample performers and in illiquid, high-idiosyncratic-vol names.[9]

---

## 5. Realistic expectations for a $700, long-only, 1–5 day account

This is the decisive section. The factors above are **monthly-to-annual, long–short, thousands-of-stock portfolios**. Translating them to the stated account:

1. **Horizon mismatch.** A 1–5 day hold converts every factor into a high-turnover short-horizon trade — i.e. short-term reversal, which is the one factor the literature shows is *not* profitable net of costs (microstructure/bid–ask bounce).[2][10]
2. **Long-only halves an already-thin edge.** Long-only captures roughly half the gross spread, and the short legs of momentum and low-vol carry disproportionate weight.[1][4][7]
3. **Concentration risk.** Factor premia are measured on diversified portfolios (dozens-to-hundreds of names). A $700 fractional account can hold a handful of names, and idiosyncratic stock risk will swamp any residual factor tilt. There is no way to "receive" a 4–20 bps/month factor premium in 3–5 names.[11]
4. **Costs dominate at this size.** 20 bps/month at the *best* institutional estimate is ~$0.04/month on $700 even if perfectly scalable; real per-trade spread, slippage, and fractional-lot costs on tiny orders exceed the gross edge. Expected net is **zero to negative**.
5. **Verdict.** The factors are real but not harvestable under these constraints. The honest conclusion of the failed single-signal mean-reversion test is consistent with the published evidence: short-horizon reversal is un-tradeable after costs.[2][10][11] If a factor tilt is still wanted, the only defensible form on this account is a **long-only, low-turnover, buy-and-hold quality/value tilt** (e.g. a broad cheap-profitable ETF), with no expectation of outperformance over days — that is a multi-year positioning decision, not a 1–5 day trade.

---

## Sources

[1] https://doi.org/10.1111/j.1540-6261.1993.tb04702.x — Jegadeesh & Titman (1993), Returns to Buying Winners and Selling Losers
[2] https://doi.org/10.1111/j.1540-6261.1990.tb05110.x — Jegadeesh (1990), Evidence of Predictable Behavior of Security Returns
[3] https://doi.org/10.1111/j.1540-6261.1985.tb05004.x — De Bondt & Thaler (1985), Does the Stock Market Overreact?
[4] https://doi.org/10.1111/j.1540-6261.2006.00836.x — Ang, Hodrick, Xing & Zhang (2006), Cross-Section of Volatility and Expected Returns
[5] https://doi.org/10.3386/w15940 — Novy-Marx (2013), The Other Side of Value: Gross Profitability
[6] https://doi.org/10.1007/s11142-018-9470-2 — Asness, Frazzini & Pedersen (2018), Quality Minus Junk
[7] https://doi.org/10.1016/j.jfineco.2013.10.005 — Frazzini & Pedersen (2014), Betting Against Beta
[8] https://doi.org/10.1111/jofi.12021 — Asness, Moskowitz & Pedersen (2013), Value and Momentum Everywhere
[9] https://doi.org/10.1111/jofi.12365 — McLean & Pontiff (2016), Does Academic Research Destroy Stock Return Predictability?
[10] https://doi.org/10.1093/rfs/hhv063 — Novy-Marx & Velikov (2016), A Taxonomy of Anomalies and Their Trading Costs
[11] https://doi.org/10.1017/s0022109022000874 — Chen & Velikov (2022), Zeroing In on the Expected Returns of Anomalies
[12] https://doi.org/10.1093/rfs/hhv059 — Harvey, Liu & Zhu (2016), ...and the Cross-Section of Expected Returns
[13] https://doi.org/10.1093/rfs/hhu068 — Hou, Xue & Zhang (2015), Digesting Anomalies: An Investment Approach
[14] https://doi.org/10.1016/j.jfineco.2015.12.002 — Daniel & Moskowitz (2016), Momentum Crashes
[15] https://doi.org/10.1093/rfs/hhm075 — DeMiguel, Garlappi & Uppal (2009), Optimal Versus Naive Diversification
[16] https://doi.org/10.2139/ssrn.2294498 — Frazzini, Israel & Moskowitz (2018), Trading Costs of Asset Pricing Anomalies (SSRN WP)
[17] https://doi.org/10.1016/0304-405x(93)90023-5 — Fama and French 1993 Common Risk Factors
