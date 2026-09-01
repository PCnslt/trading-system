# IV Skew / Term-Structure / Vol-of-Vol as a $700 Single Long Call/Put — Primary-Source Verdict

**Question:** Do (1) IV-skew *changes*, (2) IV term-structure *transitions*, or (3) vol-of-vol contain
conditional directional/vol signals capturable as ONE long call/put in a $700 Level-2 account?

**Verdict (TL;DR): NO.** All three are real in-sample **cross-sectional portfolio** phenomena, not
single-contract signals. Skew/put-call-parity signals are *directional but sign-conflicted* and
portfolio-based; term-structure and vol-of-vol option-return signals are **volatility-only
(straddle/delta-hedged)**, not call/put direction. A 2024 RFS paper zeroes the risk-adjusted
alphas of ~46 option strategies before costs. Nothing survives to a single long call/put at $700.

---

## 1. IV skew — DIRECTIONAL, but level (not "change"), and sign is contested

The canonical papers measure the **level/slope** of the smirk or a call-minus-put IV spread — none
tests skew *changes* as the predictor.

| Paper | DOI | Signal | Direction |
|---|---|---|---|
| Xing, Zhang, Zhao 2010, JFQA 45(3):641–662 | `10.1017/S0022109010000220` | smirk slope (OTM put IV − ATM call IV) | **steeper smirk → 10.9%/yr UNDERperformance** (informed put trading) |
| Yan 2011, JFE 99(1):216–233 | `10.1016/j.jfineco.2010.08.011` | smile slope | **steeper smirk → HIGHER returns**, low−high quintile = 1.9%/mo (~22.8%/yr) (jump-risk premium) |
| Cremers & Weinbaum 2010, JFQA 45(2):335–367 | `10.1017/S002210901000013X` | put-call-parity deviation (call IV − put IV) | expensive calls → outperform; expensive puts → underperform; **50 bps/week** |
| Bali & Hovakimian 2009, Mgmt Sci 55(11):1797–1812 | `10.1287/mnsc.1090.1063` | call−put IV spread | positive link to returns (jump-risk proxy) |

**Adversarial findings:**
- **Sign conflict:** XZZ (steeper smirk → *lower* returns) vs Yan (steeper smirk → *higher* returns)
  are opposite-sign, both in top journals. You cannot select call vs put without first choosing which
  theory you believe — the raw sign is not settled.
- **All are long-short decile/quintile stock sorts** across 4,000+ names. None tests a single-name,
  single-contract position. Layer-3 (long leg alone) and layer-4 (single contract) are untested.
- **Decay:** Cremers–Weinbaum state in the abstract that "predictability decreases over the sample
  period," i.e., in-sample post-publication decay, driven by "mispricing during the earlier years."

## 2. IV term structure — VOLATILITY only (straddle), no call/put direction

| Paper | DOI | Finding |
|---|---|---|
| Vasquez 2017, JFQA 52(6) | `10.1017/S002210901700076X` | **slope of IV term structure → positive *straddle* returns** (high-slope straddles beat low-slope) |
| Goyal & Saretto 2009, JFE 94(2):248–279 | `10.1016/j.jfineco.2009.01.001` | implied−historical vol spread → **straddle** returns |
| Cheng 2019, RFS 32(1):180–227 | `10.1093/rfs/hhy062` | VIX premium / term structure → VIX-futures returns and *risk* forecasts |
| Bardgett, Gourier, Leippold 2019, JFE 133(1) | `10.1016/j.jfineco.2018.09.008` | VIX term structure identifies **vol-of-vol** dynamics |
| Mixon 2007, J. Empirical Finance 14(3):333–354 | `10.1016/j.jempfin.2006.06.003` | documents the IV term structure (descriptive) |

**Every term-structure result is a straddle/VIX-futures (VOLATILITY) signal.** Contango/backwardation
flips inform *vol-of-vol and risk premia*, not equity direction. Zero call/put content. (Straddles are
also not Level-2 eligible — they need spread approval.)

## 3. Vol-of-vol — two streams, neither a single long call/put

| Paper | DOI | Finding | Type |
|---|---|---|---|
| Baltussen, van Bekkum, van der Grient 2018, JFQA 53(4) | `10.1017/S0022109018000480` | high vol-of-vol → **8%/yr underperformance** in *stock* returns | directional, but cross-sectional stock sort |
| Ruan 2020, J. Financial Markets 47:100516 | `10.1016/j.finmar.2019.03.002` | **negative** relation vol-of-vol → *option* returns; negative VOV price of risk | volatility/risk-premium |
| Huang, Schlag, Shaliastovich, Thimme 2019, JFQA 54(6) | `10.1017/S0022109018001436` | VOV risk factor; **delta-hedged** index & VIX option returns negative, more so with VOV exposure | volatility/risk-premium |

The vol-of-vol "option-return" results (Ruan; HSST) are risk-premium/volatility statements about
delta-hedged or straddle-like option returns — not a call-vs-put directional bet.

## 4. Directional vs volatility — the key split

- **Directional (stock-level) signals exist only for skew/parity** (XZZ, Yan, CW, Bali–Hovakimian,
  Baltussen VOV). But they are (a) cross-sectional long-short portfolios, (b) **sign-conflicted**
  (XZZ vs Yan), and (c) decaying (CW).
- **Term-structure and vol-of-vol option-return signals are VOLATILITY-only** (straddle/delta-hedged).
- **No paper implements any of these as a single long call or put.** The closest to call/put-selectable
  is Cremers–Weinbaum (call-expensive → up), but even that is a 50 bps/week long-short spread with
  in-sample decay.

## 5. Costs + post-publication decay + modern data — FAILS

- **Goyal & Saretto 2024, RFS 38, `10.1093/rfs/hhae087`** ("Can Equity Option Returns Be Explained by a
  Factor Model? IPCA Says Yes"): the average IPCA alpha of **46 long-short option strategies built on
  previously discovered signals is ≈ 0 even before transaction costs**, versus ~80 bps/mo gross realized.
  This is by the same authors who published the 2009 vol-spread result — an explicit self-correction
  that absorbs the option-return anomalies (term-structure slope, VOV, vol-spread, skewness assets).
- **Harvey–Liu–Zhu 2016, RFS 29(1), `10.1093/rfs/hhv059`**: t > 3.0 hurdle for new factors; many of these
  effects were documented under the old (t > 2) standard.
- **$700 single-contract reality:** every headline is a diversified long-short decile spread. One contract
  = one name = full idiosyncratic risk, no diversification. Single-name (especially OTM) option bid-ask is
  typically 10–50% of premium — the gross edges (50 bps/wk CW; ~80 bps/mo option alphas) are an order of
  magnitude below round-trip retail spread + fee on a single contract.

## Six-layer result (all three signal families)

1. Phenomenon — YES (in-sample).
2. Long-short portfolio — YES (that *is* the headline; all are decile spreads).
3. Long leg alone — only partially claimed (CW reports both legs; XZZ/Yan/Vasquez/Ruan are spreads).
4. Single contract — **NOT TESTED anywhere.**
5. Retail $700 — **FAILS** (no diversification; bid-ask ≫ gross edge; straddles not Level-2).
6. Net execution — **FAILS** (IPCA alpha ≈ 0 before costs; CW in-sample decay; t > 3 hurdle).

**Bottom line:** No primary source supports a *single long call/put* capturing IV-skew, term-structure, or
vol-of-vol signals at $700. Skew is directional but sign-disputed and portfolio-only; term-structure and
vol-of-vol are volatility-only; and the 2024 IPCA result removes the risk-adjusted edge before costs.

## Paywalled / NOT-EXTRACTED flags

- Exact magnitude tables (returns, t-stats, decile legs, DTE grids, cost numbers) for **Yan 2011**,
  **Cremers–Weinbaum 2010**, **Goyal–Saretto 2009**, **Ruan 2020**, and **Mixon 2007** are paywalled
  (Elsevier/CUP/Oxford). Only verbatim abstracts (via Crossref/EconPapers/SSRN metadata) were extracted;
  abstract-level figures are quoted above, deeper table magnitudes are **NOT-EXTRACTED**.
- Ruan 2020 instrument (straddle vs delta-hedged vs single leg) is not specified in the abstract →
  characterized as "option-return risk premium" (volatility) with that caveat.
