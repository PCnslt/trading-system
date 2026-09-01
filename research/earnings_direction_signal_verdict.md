# Can any PRE-EVENT signal select CALL vs PUT around earnings? — literature verdict

**Question:** Does any signal available *before* an earnings announcement reliably predict the
*DIRECTION* of the post-earnings move at the individual-stock level, net of cost, strongly
enough that EVENT_VOL_EDGE + DIRECTION could select a single long call or put on a $700
(Robinhood Level 2 = long options only, no short/margin) account?

**Answer: No.** No pre-event signal in the literature meets that bar. The credible effects are
(a) *post*-event (they need the surprise itself), (b) *cross-sectional portfolio* tilts, or
(c) *volatility-magnitude* (straddle) phenomena. None reliably breaks the per-event coin flip
for a single stock after single-contract option costs. Below, ranked by evidence strength, with
DOIs and the six-layer realism applied.

---

## The six-layer test (owner framework) applied to "directional earnings signal"

| Layer | Generic finding for every candidate below |
|---|---|
| 1. Phenomenon | YES — several signals are statistically real (PEAD, revision momentum, option-skew/O-S). |
| 2. Portfolio (long-short) | YES — modest positive spreads, but *cross-sectional*, needing 100s of names. |
| 3. Long leg alone | WEAK/MARGINAL — often indistinguishable from market beta (operator's own 2026-08-24 PEAD result). |
| 4. Single contract (one call/put) | **NO** — none of these breaks the per-event coin flip on one name. |
| 5. Retail $700 / Level 2 | Fails — one option only; must pay the pre-announcement IV run-up, then the post-earnings **vol crush**; cheap underlyings a $700 account can reach have the *widest* option spreads and the *least* informed-option signal. |
| 6. Net execution | Fails — cross-sectional tilts (a few bps to ~1–2% per event) are smaller than the round-trip bid/ask + theta on a single retail option. |

The deciding question at Layer 4 (direction vs magnitude) is fatal for all of them.

---

## Ranked verdict by signal

### RANK 1 — (e) Options skew / put-call pricing  — *best available, still insufficient*
The ONLY family that is genuinely **pre-event** (measured in the options market before the
announcement) **and** has documented *directional* content.

- **Pan & Poteshman 2006** (10.1093/rfs/hhj024) — signed put-call volume (informed traders
  disproportionately use options) predicts future stock returns, strongest around earnings.
- **Xing, Zhang & Zhao 2010** (10.1017/S0022109010000220) — option volatility *smirk* predicts
  negative future equity returns.
- **Cremers & Weinbaum 2010** (10.1017/S002210901000013X) — put-call-parity deviations (vol
  spread) predict returns.
- **Bali & Hovakimian 2009** (10.1287/mnsc.1090.1063) — volatility spreads predict returns.
- **Roll, Schwartz & Subrahmanyam 2010** (10.1016/j.jfineco.2009.11.004) — O/S (option-to-stock
  volume) negatively predicts earnings-announcement returns.
- **Johnson & So 2012** (10.1016/j.jfineco.2012.05.008) — O/S ratio negatively predicts returns,
  concentrated around earnings (informed negative-news traders use puts).
- **Jin, Livnat & Zhang 2012** (10.1111/j.1475-679X.2012.00439.x) — option-implied skewness
  measured *before* earnings predicts the announcement-return direction (informed option traders
  position ahead of earnings).
- **Hu 2014** (10.1016/j.jfineco.2013.12.004) — option trading conveys stock-price information.

**Adversarial assessment:** All of these are *cross-sectional return predictors* with modest
magnitude, concentrated in small/less-followed names where option bid-ask is widest. They are a
statistical *tilt* (e.g., "high skew → lower returns on average"), not a reliable per-event
direction call — the single-stock announcement return is still dominated by the idiosyncratic
surprise. Post-publication decay is documented (**Chordia, Subrahmanyam & Tong 2014**,
10.1016/j.jacceco.2014.06.001). Net of a single retail option's spread + theta, the tilt does
**not** survive at single-contract scale. **Verdict: EVIDENCE OF NO EDGE at the single-stock /
single-option level** (real phenomenon, unreachable as one call/put).

### RANK 2 — (b) Estimate-revision momentum  — real, but wrong horizon/direction
- **Stickel 1991** (10.2308/tar-9605070389); **Chan, Jegadeesh & Lakonishok 1996**
  (10.1111/j.1540-6261.1996.tb05222.x); **Gleason & Lee 2003** (10.2308/accr.2003.78.1.193);
  **Jegadeesh, Kim, Krische & Lee 2004** (10.1111/j.1540-6261.2004.00657.x).

These predict *multi-week/month cross-sectional returns* (slow drift after revisions), NOT the
direction of the *next earnings-day* move. Revisions are themselves biased and largely priced in
before the event. Single-stock signal is noisy; portfolio effect decays (Chordia et al. 2014).
**Verdict: cross-sectional drift predictor, not a pre-event direction selector.**

### RANK 3 — (d) Historical sign of the firm's own surprises ("streaks")  — *post*-event, not pre
- **Loh & Warachka 2012** (10.1287/mnsc.1110.1485) — "investors underreact to streaks of
  consecutive same-sign earnings surprises… **when the most recent surprise extends a streak,
  post-earnings-announcement drift is strong**; drift is negligible after streak termination;
  streaks explain ~half of PEAD."

This is the closest paper to "historical sign matters," but read the mechanism carefully: the
streak signal operates **after** the surprise is public (it conditions the size of the *drift*).
It does **not** claim a firm that has beaten repeatedly will beat *next* time. As a *pre-event*
directional selector it is unsupported. **Verdict: post-event drift amplifier, not pre-event
direction.**

### RANK 4 — (a) Analyst surprise / consensus  — *post*-event signal (PEAD)
- **Foster, Olsen & Shevlin 1984** (10.2308/tar-4483133); **Bernard & Thomas 1989**
  (10.2307/2491062); **Bernard & Thomas 1990** (10.1016/0165-4101(90)90008-R); **Livnat &
  Mendenhall 2006** (10.1111/j.1475-679X.2006.00196.x).

PEAD is the most-replicated earnings anomaly, but the signal *is* the surprise (actual −
consensus), which only exists **at/after** the announcement. Pre-event, only the (biased,
already-priced) consensus level is available. It is also decayed and cost-sensitive on liquid
names: **Sadka 2006** (10.1016/j.jfineco.2005.04.005, liquidity risk), **Ng, Rusticus & Verdi
2008** (10.1111/j.1475-679X.2008.00290.x, transaction costs absorb much of PEAD), **Chordia et
al. 2014** (10.1016/j.jacceco.2014.06.001, attenuation). Operator's own 2026-08-24 test on ~190
US liquid names / 6,193 events: short leg *reverses* (missers bounce), long-only = beta.
**Verdict: post-event, decayed; cannot select direction before the event.**

### RANK 5 — (c) Recent price trend / pre-earnings drift  — unconditional long premium, no direction
- **Jegadeesh & Titman 1993** (10.1111/j.1540-6261.1993.tb04702.x); **Lamont & Frazzini 2007**
  (10.3386/w13090); **Barber, De George, Lehavy & Trueman 2013** (10.1016/j.jfineco.2012.10.006).

Momentum and the "earnings announcement premium" document an *unconditional* positive average
return for holding through earnings (a long/call-like *bias*), not a per-stock direction signal.
There is no credible evidence that pre-event price trend predicts the *sign* of the next
announcement move at the single-stock level net of cost. **Verdict: long-only drift, not a
call-vs-put selector.**

### RANK 6 — (f) PEAD direction  — *post*-event by definition
Unusable for pre-event direction (needs the surprise). Same papers as (a). Also decayed / weak on
liquid names per the operator's own backtest.

---

## The two structural killers (adversarial conclusions)

1. **The direction is the unpredictable part.** The earnings surprise (actual − expectation) is,
   by construction, the component of the announcement return the market has *not* priced. Every
   pre-event public signal (consensus, revisions, trend, own-history, even option skew) is, at
   best, a weak *unconditional tilt*; the per-stock announcement return remains dominated by
   idiosyncratic surprise, so a single call/put is close to a coin flip *after* costs.

2. **EVENT_VOL_EDGE gives magnitude, not direction — and the premise is likely backwards.**
   The operator's hypothesis is a *volatility* (straddle) bet. The literature's stronger, more
   replicated finding is the **opposite sign**: implied volatility runs up into earnings and the
   earnings straddle tends to be *overpriced* (implied move > realized move on average), i.e. the
   volatility risk premium is concentrated at earnings — buying a straddle is negative-EV on
   average, not positive. See **Goyal & Saretto 2009** (10.1016/j.jfineco.2009.01.001), **Ni,
   Pan & Poteshman 2008** (10.1111/j.1540-6261.2008.01352.x), **An, Ang, Bali & Cakici 2014**
   (10.1111/jofi.12181), **Cao & Han 2013** (10.1016/j.jfineco.2012.11.010), **Atilgan 2014**
   (10.1016/j.jbankfin.2013.10.007), **Goyal & Saretto 2024** (10.1093/rfs/hhae087). So the
   "historical move > implied move" condition is the *exception*, not the rule — and even when it
   holds, it selects a straddle (two premiums, Level 3/margin), not a call vs a put.

## Four-way classification (each signal, single contract level)
- (a) PEAD/consensus — **EVIDENCE OF NO EDGE** pre-event (post-event signal, decayed).
- (b) revision momentum — **EVIDENCE OF NO EDGE** as a *direction* selector (wrong horizon).
- (c) price trend / pre-earnings drift — **EVIDENCE OF NO EDGE** (unconditional long bias).
- (d) own-surprise streaks — **EVIDENCE OF NO EDGE** pre-event (mechanism is post-event).
- (e) options skew/put-call — **EVIDENCE OF NO EDGE at single-stock/single-option scale**
  (real cross-sectional tilt, unreachable as one call/put).
- EVENT_VOL_EDGE (direction arm) — **INSUFFICIENT DATA for direction**; the magnitude premise is
  contradicted by the vol-risk-premium literature.

**Final: no pre-event directional signal reliably selects call vs put around earnings for a
$700 long-only account. Direction selection is the unsolved half of the problem, and no public
signal in the primary literature closes it at single-contract scale.**
