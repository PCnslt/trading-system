# Newer Options Anomalies — Six-Layer Triage for Long-Only Single-Option Capture

**Account constraint:** $700 retail CASH, Level 2 (long calls/puts only; no short options, no margin, no spreads). A long straddle = 2 contracts AND is Level 3/margin-only on Robinhood per banked research.

**Six layers:** ① Phenomenon (real/robust? decay?) ② Long-short portfolio (needs short leg?) ③ Long leg (does the long leg alone carry it?) ④ Single contract (survive portfolio→1 contract?) ⑤ Retail $700 (can $700 buy one contract?) ⑥ Net execution (survive spread + $0.65 comm + no-hedge?).

**KEY question:** does the anomaly select DIRECTION (call vs put) or only VOLATILITY (needs straddle/delta-hedge)?

---

## Headline verdict

**All seven are VOLATILITY-ONLY effects. Zero select direction. Zero are capturable as a single long call/put in a $700 cash Level 2 account.**

Structural reason (applies to every candidate): the alpha is measured **delta-hedged** (2,3,6,7), **straddle** (5), **factor-level delta-hedged** (1), or **relative-value IV distortion** (4). Isolating any of them requires either shorting the underlying (margin) or a second option contract (straddle = Level 3). A single long call/put is a DIRECTIONAL bet (delta + vega + negative theta) that *pays* the volatility risk premium — negative-EV by construction (Coval & Shumway 2001, 10.1111/0022-1082.00352). The documented positive expectancy in options is on the *writing*/delta-hedged side, not the naked buyer side (Bakshi–Kapadia 2003; Zhan–Han–Cao–Tong 2022 RFS 10.1093/rfs/hhab067: the delta-hedged WRITING side survives costs; long-only vol does not).

---

## Per-candidate triage

### 1. Option Factor Momentum — Käfer, Moerke, Wiest (JFQA 2025) — 10.1017/S0022109025000225
- ① Real but young (2025), no independent replication yet; authors concede "high autocorrelation"; factor-momentum is the most crowded/arbitraged signal class → high decay risk.
- ② YES: long recent-winner option factors, short recent-losers (28 delta-hedged factors).
- ③ Long leg = a *basket of delta-hedged factor portfolios*, not a directional option; standalone long-leg alpha unreported.
- ④ NO: momentum across 28 factors = thousands of options; no single-contract analog.
- ⑤⑥ N/A (dead at layer 3).
- **KEY: VOLATILITY-ONLY.**

### 2. Option trading volume — Yuan, Liu, Chen, Hu (NAJEF 2024) — 10.1016/j.najef.2024.102229
- ① Lower-tier venue; abstract concedes market cap and IVOL "explain the predictability" → not independent of candidate 3 (IVOL).
- ② YES: long low-volume, short high-volume, delta-hedged.
- ③ Long leg = low-volume (neglected/ILLIQUID) options. Signal *is* illiquidity → widest spreads on exactly the names you buy.
- ④ NO: a single low-volume option has the worst liquidity, no diversification.
- ⑤ Low-volume sub-$7 underlyings barely exist with any liquidity.
- ⑥ Illiquidity cost + no hedge = dead; largely subsumed by IVOL.
- **KEY: VOLATILITY-ONLY.**

### 3. Idiosyncratic volatility — Cao & Han (JFE 2013) — 10.1016/j.jfineco.2012.11.010
- ① Robust, canonical; ~1.4%/mo long-short at midpoint.
- ② YES: long low-IVOL, short high-IVOL, delta-hedged.
- ③ Long leg = low-IVOL (cheap) options, but capture requires delta-hedging to strip directional exposure.
- ④ NO: single option carries delta+vega, cannot isolate the IVOL mispricing.
- ⑤ No hedge possible.
- ⑥ Task-acknowledged: "dies at high cost" — Cao-Han's own spread analysis kills the midpoint spread.
- **KEY: VOLATILITY-ONLY.**

### 4. Retail option demand / IV surface — Eaton, Green, Roseman, Wu — 10.2139/ssrn.4104788 (pub. 2025/26)
- ① Strong microstructural evidence (brokerage-outage natural experiment). Retail net-BUYS short-dated OTM, net-SELLS long-dated → inflates short-dated OTM IV, depresses long-dated IV; distorts term structure, moneyness curve, call-put spread.
- ② The capture is relative value (long underpriced / short overpriced); shorting options = Level 3+ margin.
- ③ **Long leg = "neglected options cheaper":** buy long-dated options retail systematically writes, or buy the wing retail shuns. This is the ONLY candidate with a buyable direction-of-travel — but it buys *cheap IV*, not stock direction.
- ④ A single long-dated option = delta + vega + big theta; the "cheapness" is a vol premium that still needs a hedge or a vol move to monetize.
- ⑤ Long-dated options on sub-$7 underlyings are sparse.
- ⑥ The isolated mispricing is an IV *term-structure/skew* slope → needs a calendar/spread (Level 3). A single long option doesn't isolate it. Faint directional side-note (retail's OTM-call overbuying steepens call-put skew → relative cheapness of OTM puts) is not a tradable call/put signal.
- **KEY: VOLATILITY-ONLY** (relative-value vol); weakest directional residue of the seven, but residue ≠ edge.

### 5. Intraday option momentum — Da, Goyenko, Zhang (2024) — 10.2139/ssrn.5018430
- ① Novel, unreplicated. "Intraday returns on option STRADDLES… a given half-hour interval today positively predicts the same interval tomorrow"; morning = vol-shock underreaction, afternoon = market-maker inventory.
- ② YES: cross-sectional straddle momentum.
- ③ Long leg = a straddle (2 contracts, delta-neutral).
- ④ NO — the instrument IS the straddle; a single call/put is directional and does NOT carry the vol-momentum signal.
- ⑤ Half-hour holding ≈ 13 round-trips/day × 2 legs = extreme turnover.
- ⑥ Intraday straddle churn at retail cost = negative by a wide margin.
- **KEY: VOLATILITY-ONLY (explicitly straddle/delta-neutral).**

### 6. Day/night vol seasonality — Muravyev & Ni (JFE 2020) — 10.1016/j.jfineco.2018.12.006
- ① Robust, replicated. Delta-hedged option returns POSITIVE overnight, NEGATIVE intraday.
- ② It's a TIMING split (long vol overnight / short vol intraday), delta-hedged; the "short intraday" side needs writing options.
- ③ "Long vol overnight" = buy near close, sell next open — but the documented return is delta-hedged; being delta-neutral requires shorting the stock.
- ④ A single long call/put held overnight is DIRECTIONAL: collects ~+4bp overnight stock drift via delta (below ~6bp round-trip cost) MINUS theta MINUS the VRP. The positive overnight return is a VOL effect; the single option's delta leg is noise.
- ⑤ sub-$7 underlying, no hedge.
- ⑥ Long call/put overnight = net negative EV (theta + VRP > directional drift).
- **KEY: VOLATILITY-ONLY** (the sign flip is in delta-hedged/vol returns; no call/put signal).

### 7. Cross-section of individual equity option returns — Shafaati, Chance, Brooks (JEF 2026) — 10.1016/j.jempfin.2026.101748
- ① Horse-race of 130 option characteristics; dominant predictors = RV-IV, IVOL, turnover → reconfirms the Goyal–Saretto (RV-IV, 10.1016/j.jfineco.2009.01.001) + Cao–Han (IVOL) family.
- ② YES: delta-hedged cross-sectional sorts.
- ③ Long leg = high-RV-IV (cheap vol) options — already banked as NO (unhedged long call/put cannot capture; ~72% IPCA-factor-explained; cost-fragile).
- ④⑤⑥ NO.
- **KEY: VOLATILITY-ONLY.**

---

## Ranking — long-only single-option potential (best → worst)

The ranking is "least-bad"; **no candidate clears the bar.**

| Rank | Anomaly | DOI | Direction or Vol | Why ranked here |
|---|---|---|---|---|
| 1 | Retail IV-surface distortion (Eaton et al.) | 10.2139/ssrn.4104788 | Vol (rel. value) | Only one with a buyable "underpriced wing/tenor" long leg + faint fade-retail skew note; still needs hedge to isolate |
| 2 | Day/night seasonality (Muravyev–Ni) | 10.1016/j.jfineco.2018.12.006 | Vol (timing) | Concrete single-contract hold schedule (overnight), but signal is delta-hedged; single option's delta leg = noise, theta/VRP make it net-negative |
| 3 | Intraday option momentum (Da et al.) | 10.2139/ssrn.5018430 | Vol (straddle) | Real timing signal, but instrument is a straddle (2 contracts) + extreme turnover; zero single-option content |
| 4 | Option Factor Momentum (Käfer et al.) | 10.1017/S0022109025000225 | Vol (factor) | Factor-level delta-hedged; no single-contract analog; high decay risk |
| 5 | Option trading volume (Yuan et al.) | 10.1016/j.najef.2024.102229 | Vol | Delta-hedged; illiquidity IS the signal (self-defeating); subsumed by IVOL |
| 6 | Cao–Han IVOL | 10.1016/j.jfineco.2012.11.010 | Vol | Delta-hedged; acknowledged cost-death |
| 7 | JEF 130-characteristics (Shafaati et al.) | 10.1016/j.jempfin.2026.101748 | Vol | RV-IV-dominant = already-banked NO (Goyal–Saretto family) |

## Bottom line

None of the seven newer options anomalies produces a **directional** (call-vs-put) signal; every one is a volatility/relative-value effect documented via delta-hedged or straddle returns. Capturing any of them requires either shorting the underlying (margin) or a straddle/spread (Level 3/margin), both structurally off-limits in a $700 cash Level 2 account. A single long call/put is directional, pays theta and the volatility risk premium, and — on the sub-$7 underlying universe $700 forces — faces the widest spreads exactly where these effects are weakest. **Verdict: none tradeable; all volatility-only.**
