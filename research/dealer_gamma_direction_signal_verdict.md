# Dealer-gamma positioning / gamma-regime changes → single long call/put? — literature verdict

**Question:** Does dealer-gamma positioning (level) or a gamma-regime CHANGE (positive→negative flip)
contain a DIRECTIONAL signal — options positioning → dealer delta/gamma hedging → underlying order flow →
price — that a SINGLE long call or put can capture in a $700 Robinhood Level-2 account (long options only)?

**Answer: NO.** The dealer-gamma literature documents a real, replicable effect, but it is a
**volatility / symmetry / return-autocorrelation (regime) effect, not a standalone directional sign
signal.** The only "directional" content is *conditional* (it needs a second input — the prior price
move — and it *amplifies* that move, it does not choose its sign), and it operates at a ~30-minute
horizon with a few-basis-point expected move that a single long option's spread + theta destroys.
This mirrors the earnings verdict: the effect is real at portfolio scale, unreachable as one call/put.

---

## The six-layer test (owner framework)

| Layer | Finding for dealer-gamma / gamma-regime |
|---|---|
| 1. Phenomenon | **YES, real.** Negative dealer gamma → delta-hedgers trade *with* the move (momentum); positive gamma → trade *against* it (mean-reversion). Verified in peer-reviewed JFE (Baltussen et al. 2021). |
| 2. Portfolio (long-short) | **YES.** Cross-sectional decile strategies timing the last half-hour on gamma-hedging pressure print gross Sharpe ~1.77 (Barbon et al.), but are **long/short, dozens of names, 30-min horizon**. |
| 3. Long leg alone | **WEAK.** The long leg is a cross-sectional tilt, not a market-direction bet; the "signal" is an interaction (gamma × prior return), not a level. |
| 4. Single contract (one call/put) | **NO.** No paper shows gamma level/change alone predicts the *sign* of next-period returns. The directional residue needs the prior move's sign as a second input, and the horizon (last 30 min) is theta-dominated. |
| 5. Retail $700 / Level 2 | **FAILS.** One option; 30-min hold ≈ 0DTE theta; SPX/SPY option spread; gamma (NGE/GEX) itself is unobservable to retail without OptionMetrics or a contested practitioner feed. |
| 6. Net execution | **FAILS.** Conditional expected move is a few bps (R² ≈ 3.6% of a ~15-min return; unconditional ~2.7 bp/day) — far below single-option round-trip spread + theta. |

The deciding failure is **Layer 4 (direction vs symmetry)** — exactly the same fatal layer as the earnings signal.

---

## Ranked evidence (primary sources, DOIs)

### RANK 1 — Baltussen, Da, Lammers & Terhorst 2021, *JFE* 142(1):377–403 — the gamma gate (FULL TEXT verified)
- **DOI:** 10.1016/j.jfineco.2021.04.029
- **Mechanism (abstract, verbatim):** "Hedging short gamma exposure requires trading in the direction of
  price movements, thereby creating price momentum." Market intraday momentum (last 30 min predicted by
  the rest of the day) found in **60+ futures** (equities, bonds, commodities, FX), 1974–2020.
- **NGE proxy:** net gamma exposure from S&P 500 index option open interest (OptionMetrics 1996–2017 +
  SqueezeMetrics to May 2020). **2930 negative-NGE days vs 3158 positive-NGE days** — i.e. under their
  convention dealers are net *long* gamma on ~52% of days, contradicting the practitioner "dealers are
  chronically short gamma" claim.
- **The gate (Table 7, verbatim numbers):**
  - NGE ≥ 0: β_ROD = **0.82 (t = 1.03), R² = 0.05%** → *no* intraday momentum (mean-reversion world).
  - NGE < 0: β_ROD = **6.63 (t = 4.78), R² = 3.58%** → momentum concentrated entirely in negative-gamma days.
- **Level effect (Table 8):** NGE × r_ROD = **−123.04 (t = −3.42)*** and ΔNGE × r_ROD = **−119.79
  (t = −4.06)*** — the *more negative* gamma is, the stronger the momentum.
- **Adversarial read:** this is a **conditional/interaction** result. The direction of the predicted
  last-half-hour move is the sign of the *prior* rest-of-day return r_ROD, **not** the sign of gamma.
  Gamma is a *regime switch* on autocorrelation (momentum ⇄ mean-reversion) and on volatility — it is
  symmetric in the up/down direction.

### RANK 2 — Barbon, Beckmeyer, Buraschi & Moerke (WP) — end-of-day gamma + LETF flow (FULL TEXT verified)
- Author PDF: `abarbon.com/assets/Liquidity_Provision_to_Rebalancing_Flows_from_Leveraged_ETFs_and_Equity_Options.pdf` (2013–2020 sample).
- ΓHP (gamma-hedging pressure) → end-of-day returns: coeff **−9.46 (t = −4.71)**; joint with LETF flow −10.96 (1% sig).
- 1 SD decrease in ΓHP → **+113%** of the average last-half-hour return; 1 SD increase in LETF flow → **+430%**.
- L/S decile strategies timing the last 30 min: **Sharpe up to 1.77** (gross, combined ΓHP + ΩLETF).
- **"gamma effects are persistent throughout our sample, while those from leveraged ETFs are decreasing over time."**
- **Adversarial read:** the tradeable strategies are **long/short cross-sectional deciles** (long low-gamma
  decile / short high-gamma decile), requiring shorting and many names; the magnitude is a *fraction of a
  tiny average last-30-min return*. Not a single directional option. Also note their own estimate is
  attenuated by measurement noise (delta-hedgers' rebalancing is discretionary, not necessarily at close).

### RANK 3 — Ni, Pearson, Poteshman & White 2020, *RFS* — the channel is VOL/TALLS, not direction (abstract verified)
- **DOI:** 10.1093/rfs/hhaa082
- Abstract (verbatim): option market-maker hedge rebalancing is a "**noninformational channel** through
  which option market maker hedge rebalancing affects **stock return volatility and the probability of
  large stock price moves**."
- The paper's own framing is the cleanest primary statement of the symmetry point: dealer gamma hedging
  moves *volatility and tails*, not the *sign* of returns.

### RANK 4 — 0DTE / modern-data literature (abstracts verified via Wayback of SSRN)
- **Brogaard, Han & Won 2023** — "Does 0DTE Options Trading Increase Volatility?" SSRN 4426358,
  **DOI 10.2139/ssrn.4426358**. 0DTE index volume 0.08M → 34.4M contracts/mo (2011–2023), 48% of index
  option volume; **1 SD more 0DTE trading → +10.40% (relative to mean) volatility**, 1.49× the Harris (1989)
  options-volatility effect. **VOLATILITY, not direction.**
- **Almeida, Freire & Hizmeri 2024** — "0DTE Asset Pricing" SSRN 4701401, **DOI 10.2139/ssrn.4701401**.
  0DTE has a high **upside** variance risk premium that "negatively predicts market returns" — a
  directional claim, but via the **VRP channel (already ruled out by the operator)**, not gamma positioning;
  and the exploitable price-bound-violation strategy is "**profitable up to 2022, but dissipates after the
  daily availability of 0DTEs**" → direct post-publication-decay evidence.
- **Madtzog Fagerlid & Skarpnes 2024** — "The Rise and Impacts of Zero Days-to-Expiration Options" SSRN
  4724972, **DOI 10.2139/ssrn.4724972**. 0DTE trading "associated with volatility and sudden price
  movements"; puts correlate with SPX declines, calls with increases — **contemporaneous** dealer hedging,
  not a *forward* directional predictor.

### RANK 5 — Pinning / expiration-day clustering (mechanism = mean-reversion to a level, not a sign)
- **Avellaneda & Lipkin 2003**, *Quantitative Finance* 3(6), **DOI 10.1088/1469-7688/3/6/301** — "A
  market-induced mechanism for stock pinning."
- **Golez & Jackwerth 2012**, *JFE*, **DOI 10.1016/j.jfineco.2012.06.010** — "Pinning in the S&P 500 futures."
- **Ni, Pearson & Poteshman 2005**, *JFE*, **DOI 10.1016/j.jfineco.2004.08.005** — "Stock price clustering
  on option expiration dates."
- Pinning is a **pull toward a known strike level** (a locally directional *mean-reversion*, the opposite of
  a trend) concentrated on expiration days. It is not a "market will go up/down" signal and it is a *fade*
  signal, structurally inconsistent with a single directional call/put.

### RANK 6 — 2026 SSRN preprints (abstracts NOT-EXTRACTED — Cloudflare-walled + not yet in Wayback)
- **Maurer 2026**, "Dealer Gamma Exposure and Overnight Gap Risk: Incremental Information in
  Low-Volatility Regimes", SSRN 6650858, **DOI 10.2139/ssrn.6650858** — single-author, 0 citations; title
  indicates the claimed info is about *gap risk* (magnitude), not a directional sign. **ABSTRACT
  NOT-EXTRACTED.**
- **Chilingarian 2026**, "The Sign of Dealer Gamma: A Reproducible, Auditable Framework for Computing S&P
  500 Gamma Exposure (GEX)", SSRN 7131778, **DOI 10.2139/ssrn.7131778** — the title itself is the
  miscalculation flag: the practitioner GEX **sign convention is contested/non-reproducible**. **ABSTRACT
  NOT-EXTRACTED.**

---

## The two structural killers (adversarial conclusions)

1. **Gamma is a REGIME/SYMMETRY variable, not a direction variable.** It modulates the *autocorrelation*
   (momentum vs mean-reversion) and the *volatility/tails* of returns — symmetric in up vs down. The only
   directional content is a **second-order interaction**: (negative gamma) × (prior move sign) → the move
   *continues*. That is an *amplifier of whatever direction already happened*, not a predictor of direction.
   No primary paper shows gamma level, or a positive→negative "flip", predicts the *sign* of next-period
   returns unconditionally.

2. **The horizon and magnitude are structurally un-buyable as one option.** The effect lives in the
   **last 30 minutes** (Baltussen/Barbon) with a few-bp expected move (R² ≈ 3.6% of a ~15-min return;
   unconditional ~2.7 bp/day for a 6.86%/yr futures effect). A single ATM SPX/SPY option held 30 min is a
   near-0DTE position: theta + spread exceed a few bps. This is the already-banked **negative-EV long
   0DTE premium** result (Coval & Shumway 2001, 10.1111/0022-1082.00352; Bakshi & Kapadia 2003,
   10.1093/rfs/hhg002) applied to the gamma horizon. A *gamma-flip* "trigger" for buying a directional
   option is practitioner folklore, not in the peer-reviewed literature.

---

## Cost / decay / modern-data checks

- **Cost:** the tradeable forms are (a) cross-sectional L/S deciles needing shorting + many names (Barbon),
  or (b) the conditional last-half-hour momentum (Baltussen) = ~2.7 bp/day gross → **dies on SPY at ~6 bp,
  survives only on MES/ES at ~1 tick** (already banked in `academic-short-horizon-anomalies.md`). Neither is
  a single directional option. The single-option spread+theta on a 30-min hold is *larger* than the whole edge.
- **Post-publication decay:** MIM's always-on version fades OOS (Rosa 2022, *J. Futures Markets* 42(12)); the
  0DTE price-bound strategy "dissipates after daily availability of 0DTEs" (Almeida et al. 2024); LETF-flow
  effects are "decreasing over time" (Barbon et al.) while gamma effects persist — but persistence of the
  *regime* effect ≠ a tradeable single-contract edge.
- **Modern data (2023–2026):** the 0DTE papers (2023–2024) confirm the mechanism now concentrates in 0DTE
  (48% of index volume) and that its documented effect is *volatility*, not direction. The two 2026 SSRN
  preprints on dealer gamma are unreviewed, uncited, and their abstracts could not be extracted (flagged
  NOT-EXTRACTED). There is no peer-reviewed 2023–2026 paper demonstrating a *directional* single-contract
  gamma signal.
- **Index concentration:** the gamma literature is index-dominant (SPX/SPY, S&P futures) — which *does* make
  a single retail contract cheap to enter — but cheap entry does not fix the negative-EV premium/theta on the
  direction the literature does not actually provide.

## Adversarial flags — this literature is popular and frequently miscalculated

1. **The GEX sign convention is contested.** Baltussen et al. find NGE *positive on ~52% of days* and note
   JP Morgan's industry estimate is that **short puts dominate** dealer books — the opposite of the popular
   "dealers always short gamma" narrative. Chilingarian 2026 (SSRN 7131778) exists *because* the practitioner
   GEX sign is non-reproducible. Any retail "gamma flip" signal inherits this sign ambiguity.
2. **NGE/GEX is unobservable and model-dependent.** It requires OptionMetrics (institutional) or a
   SqueezeMetrics/SpotGamma feed with opaque assumptions (which options are "dealer-held," delta-hedged, the
   OI×gamma×price scaling). Barbon et al. show measurement noise attenuates the true coefficient (their
   simulation) — the published magnitudes are *under*-estimates of a small effect, not a robust trade.
3. **"Gamma flip" (positive→negative) as an event is folklore.** The peer-reviewed papers condition on the
   *level/sign* of gamma (Baltussen Table 7/8), not on a "flip event." No primary source documents a
   tradeable discontinuity at the flip.
4. **Contemporaneous vs predictive.** Several 0DTE papers (Madtzog & Skarpnes 2024) show *contemporaneous*
   correlation between option flow and index moves (dealer hedging is the *simultaneous* transmission
   mechanism) — that is not a forward-tradeable direction signal.

## Four-way classification (single-contract level)
- **Gamma LEVEL / NGE sign** → **EVIDENCE OF NO EDGE** as a standalone direction signal (symmetric regime/vol effect).
- **Gamma-regime CHANGE / "flip"** → **NO PEER-REVIEWED DIRECTIONAL SIGNAL** (folklore; sign convention contested).
- **Conditional momentum (negative-gamma × prior move)** → real but **unreachable as one call/put** (30-min, few bps, theta-dominated, needs the prior move as input).
- **0DTE upside VRP** → directional only via the **VRP channel (already ruled out)**, and post-2022 decay documented.

**Final: dealer-gamma positioning changes the autocorrelation and volatility of returns — not the sign.
The directional residue is a conditional 30-minute amplifier of a few basis points, below a single option's
spread + theta, and requires institutional gamma data with a contested sign convention. No primary source
supports a single long call/put on a $700 Level-2 account.**

## NOT-EXTRACTED (flagged)
- Maurer 2026 (SSRN 6650858) and Chilingarian 2026 (SSRN 7131778) abstracts — Cloudflare-walled, unarchived.
- Barbon et al. per-decile bps magnitudes (figures/Online Appendix) beyond the coefficients quoted above.
- Brogaard-Han-Won 2023 published-version details (still SSRN WP at time of check).
