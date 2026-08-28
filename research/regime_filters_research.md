# Regime Filters & Position-Sizing Controls for Short-Horizon Equity Strategies

Scope: rules implementable with **daily OHLCV + 1-min bars + a VIX series + a market-breadth series** (advance/decline, % of stocks above an MA). No intraday L2. Flagged `NOT-EXTRACTED` where the underlying data isn't available.

---

## A. Volatility-regime & portfolio-level sizing controls

### 1. Volatility targeting / inverse-vol scaling (position sizing)
- **Rule:** Scale gross exposure by inverse recent realized variance: `w_t = (σ_target / σ̂_t)`, where `σ̂_t` is trailing realized vol (e.g. 20–60 trading days from daily OHLCV, or a 1-min realized-variance estimator). Rebalance monthly (or daily). Long-only implementation: hold full notional when `σ̂ ≤ σ_target`, scale *down* toward cash as `σ̂` rises — no shorting needed.
- **Source:** Moreira & Muir (2017), "Volatility-Managed Portfolios," *Journal of Finance* 72(4). https://doi.org/10.1111/jofi.12513 (NBER w22208: https://www.nber.org/papers/w22208); corroborated by Harvey, Hoyle, Korgaonkar & Rattray (2018), "The Impact of Volatility Targeting," *J. Portfolio Management*. https://doi.org/10.3905/jpm.2018.45.1.014
- **Effect size:** Market factor: **alpha ≈ 4.9%/yr, appraisal ratio 0.33, ~25% increase in buy-and-hold Sharpe ratio** (NBER 2016 working-paper figures). Holds for market, value, momentum, profitability, ROE, investment, and currency carry. Mean-variance utility gain ≈ **65% of lifetime utility** vs ~35% for return-timing. Harvey et al. confirm Sharpe gains are specific to equities/credit (leverage effect) and that vol targeting **reduces the likelihood of extreme returns across all asset classes**.
- **Implementable?** ✅ YES — realized vol from daily OHLCV or 1-min bars; VIX optional. This is the single highest-value portfolio control for the operator.

### 2. Momentum "panic-state" crash filter (gate momentum off)
- **Rule:** Momentum strategies crash in "panic" states — following market declines and when market volatility is high. Gate: run momentum only when the trailing market return is positive *and* realized vol / VIX is in the lower two terciles. (Full version: scale momentum weight by forecast of its conditional mean & variance.)
- **Source:** Daniel & Moskowitz (2016), "Momentum Crashes," *Journal of Financial Economics* 122(2). https://doi.org/10.1016/j.jfineco.2015.12.002 (NBER w20439: https://www.nber.org/papers/w20439)
- **Effect size:** "An implementable dynamic momentum strategy based on forecasts of momentum's mean and variance **approximately doubles the alpha and Sharpe ratio** of a static momentum strategy." Static WML is prone to infrequent, persistent losses (e.g. ~ −50% in two months in 1932/2009).
- **Implementable?** ✅ YES — market return sign + realized vol from daily OHLCV (VIX as alternative). Directly applicable to the operator's momentum test.

### 3. Market-state gate (momentum only after up-markets)
- **Rule:** Run momentum only when the lagged market return is positive; stand aside (or flip to reversal) after down-markets.
- **Source:** Cooper, Gutierrez & Hameed (2004), "Market States and Momentum," *Journal of Finance* 59(3). https://doi.org/10.1111/j.1540-6261.2004.00665.x
- **Effect size:** 1929–1995: momentum profits **+0.93%/month following positive market returns vs −0.37%/month following negative market returns** (lagged 36-month market return as the state variable).
- **Implementable?** ✅ YES — index trend sign from daily OHLCV. One of the simplest, best-documented gates.

### 4. Cross-sectional dispersion regime (momentum vs value/reversal)
- **Rule:** High recent cross-sectional return dispersion (RD) → value/mean-reversion premia are high and momentum premia are *low*. So: high dispersion → favor the operator's reversal edge; low dispersion → momentum works.
- **Source:** Stivers & Sun (2010), "Cross-Sectional Return Dispersion and Time Variation in Value and Momentum Premiums," *Journal of Financial and Quantitative Analysis* 45(4). https://doi.org/10.1017/s0022109010000384
- **Effect size:** RD is positively related to the subsequent value premium and negatively related to the subsequent momentum premium; relation stays strong controlling for macro state variables. (Dispersion acts as a leading countercyclical state variable.)
- **Implementable?** ⚠️ PARTIAL — RD = cross-sectional std of daily returns over a trailing window; needs a stock universe. The operator's breadth series (% above MA, A/D counts) is a workable proxy; a watchlist of ~20–50 names gives a cleaner RD estimate. No L2 needed.

## B. Breadth / participation filters

### 5. Market breadth (rising-minus-falling) as a return predictor
- **Rule:** Breadth = average (#rising − #falling stocks); go long / stay invested when breadth is high and rising; reduce exposure when breadth is negative or diverging from price.
- **Source:** Zaremba, Szyszka, Karathanasopoulos & Mikutowski (2020), "Herding for profits: Market breadth and the cross-section of global equity returns," *Economic Modelling*. https://doi.org/10.1016/j.econmod.2020.04.006
- **Effect size:** High-breadth portfolios **significantly outperform low-breadth portfolios**, robust across **64 countries (1973–2018)** and to controls for size, style, volatility, skewness, momentum, and trend signals.
- **Implementable?** ✅ YES — advance/decline breadth series. Strongest academic support for the operator's breadth input.

### 6. Advance-decline breadth + TRIN (arms index) timing
- **Rule:** Use A/D breadth and the TRIN/Arms index as near-term (days) market-timing inputs; note the signal has decayed since ~1990s.
- **Source:** Qi & Zhao (2008), "Market Breadth, Trin Statistic, and Market Returns," *Journal of Investing*. https://doi.org/10.3905/joi.2008.701962
- **Effect size:** "Strong predictive power for returns in the near future," but profits come mainly from frequent trading in small, low-transaction-cost stocks and predictability **weakens drastically in the most recent decade**.
- **Implementable?** ✅ YES (breadth series) — but treat as weak/decayed; better as a tiebreaker than a primary gate. Practitioner complement: Zweig Breadth Thrust (10-day EMA of adv/(adv+decl) thrusting from <0.40 to >0.615) — every major bull move since 1945 began with one; rare signal (~a few/decade). (Zweig, *Winning on Wall Street*, 1986 — practitioner.)

### 7. 200-day (10-month) moving-average trend filter
- **Rule:** Hold the index (or run long-side strategies) only when price > 200-day SMA (Faber uses 10-month SMA); move to cash/bills otherwise.
- **Source:** Faber (2007), "A Quantitative Approach to Tactical Asset Allocation," *Journal of Wealth Management* 9(4). https://doi.org/10.3905/jwm.2007.674809
- **Effect size:** "Equity-like returns with bond-like volatility and drawdown," out-of-sample across 20+ markets since 1972. **Caveat:** Zakamulin (2017), https://doi.org/10.1111/irfi.12132, shows the originally reported MA returns had look-ahead bias; corrected performance is **only marginally better than buy-and-hold**, so treat as a drawdown reducer, not an alpha source.
- **Implementable?** ✅ YES — index daily OHLCV. Best used as a regime/drawdown filter, not a return generator.

## C. VIX regime filter

### 8. VIX level / change as a style-and-size regime switch
- **Rule:** When VIX is high (≈>25), favor small-cap and value; when VIX is low (≈≤25), favor large-cap and growth. Also: VIX *changes* are leading indicators of daily index returns — large-cap/value outperform on days following VIX *increases*, small-cap/growth after VIX *decreases*.
- **Source:** Copeland & Copeland (1999), "Market Timing: Style and Size Rotation Using the VIX," *Financial Analysts Journal* 55(2). https://doi.org/10.2469/faj.v55.n2.2262 ; VIX construction/interpretation: Whaley (2000) https://doi.org/10.3905/jpm.2000.319728 and Whaley (2009) https://doi.org/10.3905/JPM.2009.35.3.098
- **Effect size:** VIX changes are statistically significant leading indicators of daily market returns; the style/size rotation materially outperformed static style/size allocations (timing "at least for portfolio yield enhancement").
- **Implementable?** ✅ YES — VIX level + daily change series (which the operator has). Note: threshold ~25 is the paper's documented cutoff; the change-based rule needs only the VIX series.

## D. Seasonality / day-of-week & month effects

### 9. Day-of-week (Monday) + turn-of-month timing
- **Rule:** Avoid opening new long positions on Mondays (negative expected return), especially Mondays in the 4th/5th weeks of the month; concentrate/rebalance exposure in the **turn-of-month window** (last trading day + first 3 days).
- **Source:** French (1980), "Stock Returns and the Weekend Effect," *JFE* 8(1). https://doi.org/10.1016/0304-405x(80)90021-5 ; Keim & Stambaugh (1984) https://doi.org/10.1111/j.1540-6261.1984.tb03675.x ; Lakonishok & Smidt (1988), "Are Seasonal Anomalies Real?" *RFS* 1(4). https://doi.org/10.1093/rfs/1.4.403 ; Ariel (1987), "A monthly effect in stock returns," *JFE*. https://doi.org/10.1016/0304-405X(87)90066-3 ; Wang, Li & Erickson (1997), "A New Look at the Monday Effect," *JF*. https://doi.org/10.1111/j.1540-6261.1997.tb02757.x
- **Effect size:** Mean S&P 500 Monday return ≈ **−0.17%** (1953–1977) vs positive on other weekdays; Monday effect is **concentrated in weeks 4–5** (first 3 weeks ≈ 0). Turn-of-month (last day + first 3 days) captures ≈ **0.35%**, with most of the month's cumulative return in the first half of the month.
- **Implementable?** ✅ YES — pure calendar, zero data cost. Directly useful for entry/exit timing of the operator's RSI2/RSI14 reversal trades.

### 10. Halloween indicator ("Sell in May")
- **Rule:** Hold long exposure Nov–Apr; reduce/stand aside May–Oct.
- **Source:** Bouman & Jacobsen (2002), "The Halloween Indicator, 'Sell in May and Go Away'," *American Economic Review* 92(5). https://doi.org/10.1257/000282802762024683 ; robustness: Zhang & Jacobsen (2020) https://doi.org/10.1016/j.jimonfin.2020.102268
- **Effect size:** Nov–Apr returns exceed May–Oct in **36 of 37 countries**, by **~4.5%/yr on average (≈10% in the UK)**.
- **Implementable?** ✅ YES — calendar only. Seasonal tilt, not a standalone edge.

### 11. Fractional-Kelly position sizing (for a ~$700 account)
- **Rule:** Size each trade at a **fraction (¼–½) of full Kelly**: discrete `f* = (p·b − q)/b` (p = win prob from own backtest, b = avg win/avg loss, q = 1−p), or continuous `f* = (μ−r)/σ²`. Then use `f = 0.25–0.50 · f*` to cut drawdowns. Hard-cap any single position (e.g. ≤25–50% of the $700) and cross-cap total gross exposure.
- **Source:** Thorp (2006), "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market," *Handbook of Asset & Liability Management*. doi:10.1016/S1872-0978(06)01009-X ; MacLean, Thorp, Zhao & Ziemba (2011), "How Does the Fortune's Formula Kelly Capital Growth Model Perform?" *JPM*. https://doi.org/10.3905/jpm.2011.37.4.096 ; Carta & Conversano (2020) https://doi.org/10.3389/fams.2020.577050
- **Effect size:** Full Kelly maximizes long-run growth and median terminal wealth but has very volatile short-run paths; **fractional Kelly at fraction c ≈ c(2−c) of full growth with ≈ c² of the variance** — i.e. half-Kelly keeps ~75% of growth at ~25% of variance. Over-betting above full Kelly reduces growth *and* increases risk.
- **Implementable?** ✅ YES — needs only win-rate and payoff ratio from the operator's own backtest (daily OHLCV). Key guard for a small account (avoids ruin; commissions/spread eat full-Kelly edges).

---

## Baseline edges the operator already runs (for calibration)
- **Short-term reversal** — Jegadeesh (1990), *JF* 45(3): extreme-decile reversal spread **2.49%/month** (1934–1987). https://doi.org/10.1111/j.1540-6261.1990.tb05110.x ; Lehmann (1990), *QJE* 105(1): weekly winners/losers reverse the next week, persistent after transaction costs. https://doi.org/10.2307/2937816
- **Momentum** — Jegadeesh & Titman (1993), *JF* 48(1): 3–12-month momentum ≈ **~1%/month**. https://doi.org/10.1111/j.1540-6261.1993.tb04702.x

---

## NOT-EXTRACTED (data the operator cannot compute from daily+1-min OHLCV + VIX/breadth)
- **VIX futures term-structure (contango/backwardation) as a contrarian timing signal** — Fassas & Hourvouliades (2019), *J. Risk & Financial Mgmt*. https://doi.org/10.3390/jrfm12030113 — requires the **VIX futures curve**, which is NOT in the available data. ❌
- **Real-time intraday breadth feeds / tick advance-decline** — intraday (1-min) breadth requires per-minute A/D counts, not derivable from index 1-min OHLCV alone. Any intraday-breadth rule is ❌ unless the breadth series is time-stamped at 1-min frequency.
- **Shorting-dependent cross-sectional long-short** (the momentum/reversal/dynamic-momentum alphas above are long-short) — a ~$700 long-only account captures only the long leg; effect sizes should be roughly halved and re-verified long-only.
- **Options-based signals** (VIX construction, variance-risk-premium timing) — the VIX *level* is provided, but any strategy needing option prices or the VRP is ❌.

## Bottom line (top 4 by expected value for a $700 long-only account)
1. **Vol targeting / inverse-vol sizing** (filter #1) — largest, most robust risk-adjusted improvement; no extra data.
2. **Market-state + panic-state gates on momentum** (filters #2, #3) — avoid the −0.37%/mo down-market regime and the crashes that halve momentum's Sharpe.
3. **Breadth participation + dispersion regime** (filters #4, #5) — align reversal vs momentum with the cross-sectional regime.
4. **Fractional-Kelly cap + calendar timing** (filters #9, #10, #11) — cheap, protects the small account, and sharpens entries/exits.
