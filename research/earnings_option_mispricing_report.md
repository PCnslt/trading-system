# Earnings-Event Option Mispricing — Primary-Source Verification

## Sources read (primary)
- **Chung & Louis (2017)** "Earnings announcements and option returns," *Journal of Empirical Finance* 40:220–235. DOI: **10.1016/j.jempfin.2016.07.010**. [ABSTRACT read verbatim; FULL TEXT PAYWALLED — no open-access copy exists (Unpaywall: closed)]
- **Dubinsky, Johannes, Kaeck & Seeger (2019)** "Option pricing of earnings announcement risks," *Review of Financial Studies* 32(2):646–687. DOI: **10.1093/rfs/hhy060**. [FULL TEXT read — accepted manuscript from VU Amsterdam repository / figshare]
- **Barth & So (2014)** "Non-Diversifiable Volatility Risk and Risk Premiums at Earnings Announcements," *The Accounting Review* 89(5):1579–1607. DOI: **10.2308/accr-50758**. [ABSTRACT; paywalled]
- **Lipkin, Arjun K. M. & Tatevossian (2024)** "Earnings moves and pre-earnings implied volatility," *Journal of Risk*. DOI: **10.21314/jor.2024.016** (SSRN "Research Note" 10.2139/ssrn.4701633). [ABSTRACT via RePEc/EconPapers; paywalled]

## Direction (call/put) literature — SEPARATE from the vol/straddle signal
- Roll, Schwartz & Subrahmanyam (2010) JFE, "O/S: The relative trading activity in options and stock." DOI: **10.1016/j.jfineco.2009.11.004**
- Jin, Livnat & Zhang (2012) J. Accounting Research, "Option Prices Leading Equity Prices." DOI: **10.1111/j.1475-679X.2012.00439.x**

## Core findings

### Chung & Louis (2017) — the claim under test
Abstract (verbatim): "While prior studies find that returns on option straddles are generally negative, we show that returns on straddles purchased prior to earnings announcements are actually positive. The earnings announcement impact is compounded when the pre-portfolio formation volatility is low (high) and the pre-expiration realized volatility is high (low). Apparently, the average option trader underestimates future volatility before forthcoming earnings announcements, particularly after a period of relatively low volatility, and overestimates future volatility after recent earnings announcements, particularly after a period of relatively high volatility. The overestimation of future volatility after recent earnings announcements also increases with the magnitude of the earnings surprise."

Signal = **VOLATILITY (straddle), NOT direction.** No call/put content anywhere in the paper.

NOT-EXTRACTED (paywalled): sample period, universe, option maturity, exact straddle construction, entry/exit timing, transaction-cost treatment, long-leg vs long-short return magnitudes, t-stats, robustness detail.

### Dubinsky et al. (2019) — the event-level counterpoint (full text)
- Sample 2000–2015 (16 years), actively traded US stocks with listed options.
- Earnings-announcement jump vol: **option-implied 8.22% vs realized 7.42% → +80 bps earnings vol risk premium** (56 bps close-to-open). Options OVERSTATE earnings vol on average.
- ATM one-day straddle (buy before EAD, close next day): **mean −7.96%, median −10.24%, t = −13.25**, negative in all 16 sample years; straddle returns are MORE negative on earnings days than non-earnings days (non-earnings mean also negative → negative VRP).
- Monte Carlo: a 1% real-vs-risk-neutral earnings-jump-vol wedge ⇒ −8.5% average straddle return.
- **Costs:** "naive trading strategies based on closing bid and ask quotes may consume a substantial portion of these short straddle returns" — even the SHORT side (collecting the premium) is marginal after bid-ask; the LONG side is worse.

### Barth & So (2014)
Volatility risk premiums are concentrated among "bellwether" firms and produce predictable variation in straddle returns around earnings; investors pay a premium to hedge non-diversifiable earnings volatility risk. Consistent with a positive earnings vol risk premium (i.e., long straddles are costly), not a free lunch.

### Lipkin et al. (2024) — "implied earnings move" literature
Descriptive calibration study: short/intermediate-expiry IV on the day before earnings vs realized move, 3 discrete years. The options market predicts the MAGNITUDE of the earnings move well; the distribution is symmetric with ~2.5% in each tail and fat tails. **No claim of a profitable straddle mispricing** — the opposite: implied moves are well-calibrated.

## Answers to the parent's questions

1. **Is the conditional long-straddle return positive?** Only in Chung & Louis's abstract-level claim (positive before EAs, compounded when prior vol is low). The broader, model-based event-level evidence (Dubinsky et al. 2019) is the OPPOSITE sign: long ATM earnings straddles lose ~−8% per event because options embed a +80 bps earnings vol premium. No published reconciliation of the two; Chung & Louis's construction is paywalled so the divergence cannot be resolved here.

2. **Direction or volatility?** **Volatility only (straddle).** The earnings event-vol signal is about under/over-estimation of earnings volatility conditional on prior volatility. Direction (call vs put) is a distinct literature (RSS 2010; JLZ 2012) using different signals (O/S ratio, option-stock informed trading).

3. **Survives costs?** No evidence. Chung & Louis's cost treatment is NOT-EXTRACTED. Dubinsky shows bid-ask consumes a substantial portion of even the premium-collecting side; an ~80 bps vol edge is smaller than typical straddle round-trip costs.

4. **Survives modern/post-publication data?** No replication found. Chung & Louis is lightly cited (2 on RePEc; ~6 on Semantic Scholar). Dubinsky (through 2015) contradicts the unconditional claim; Lipkin et al. (2024) shows implied earnings moves are well-calibrated. No 2023–2026 study reproduces a conditional positive long-straddle edge.

## Six-layer test
1. **Phenomenon** — documented by Chung & Louis (abstract), but contested at the event level by Dubinsky (negative).
2. **Long-short portfolio** — "low prior vol vs high prior vol" implies a conditional spread, but no explicit long-short straddle portfolio is verifiable (NOT-EXTRACTED).
3. **Long leg alone** — Chung & Louis: positive (abstract); Dubinsky: −7.96% mean (event window).
4. **Single contract** — not verifiable; Dubinsky notes firm-level straddle returns are noisy/outlier-sensitive.
5. **Retail $700** — not addressed; an ATM earnings straddle costs ~5–8% of spot per event (a large concentrated single-name bet for retail).
6. **Net execution after bid-ask** — Chung & Louis not net of costs (NOT-EXTRACTED); Dubinsky shows costs are material ⇒ the edge likely does not survive net execution.

## Bottom line
The hypothesis is **not verified as a robust, cost-surviving, direction-neutral edge.** It is a conditional volatility-mispricing claimed in one paywalled study (Chung & Louis 2017), contradicted at the event level by the more rigorous model-based study (Dubinsky et al. 2019), with no modern replication, material cost sensitivity, and a volatility-only (straddle) signal that carries no directional content.
