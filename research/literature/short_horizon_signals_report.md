# Short-Horizon (1–5 day) Return Predictors from Existing & Near-Term Data

**Prepared:** 2026-08-24 · **Scope:** equity-index + single-name returns · **Horizon:** 1–5 days
**Method:** academic + practitioner sources (Serper + full-text fetch), cross-checked against the actual S3 data lake schema.

---

## 0. Executive summary

**What we can backtest *today* with existing S3 data (Tier 1, ranked by edge):**

| # | Signal | Data now? | Expected 1–5d edge | Evidence strength |
|---|---|---|---|---|
| 1 | Relative volume (RVOL) | ✅ full 20y+ | Moderate (continuation) | Strong (GKM 2001) |
| 2 | Realized-vol expansion (vol spike) | ✅ full 20y+ | Moderate (vol persistence + reversal) | Strong (BTZ 2009, Black 1976) |
| 3 | VIX level / VIX-SPX contrarian | ✅ 1990+ | Moderate (10–30d; weaker at 1–5d) | Strong (Simon & Wiggins 2001) |
| 4 | Quote/top-of-book imbalance | ✅ (short hist) | Strong intraday → 1–2d | Strong (Gould & Bonart 2016, CKS 2014) |
| 5 | Cumulative delta / VPIN | ✅ (short hist) | Moderate (vol/toxicity, contested) | Moderate (Easley et al. 2012; Andersen-Bondarenko 2014) |
| 6 | Variance risk premium (VIX²−RV) | ✅ 1990+ | Low at 1–5d (quarterly effect) | Strong (BTZ 2009) |

**Requires data we do NOT yet collect (Tier 2, ranked by edge × ease):**

| # | Signal | Missing data | Collection ease |
|---|---|---|---|
| 7 | **VIX term-structure slope / contango-backwardation** | VX (VIX futures) curve | **EASY** (IBKR VX futures via existing `futures-ticks` pipeline, or CBOE VIX9D/VIX/VIX3M daily) |
| 8 | Opening/closing auction imbalance | auction imbalance feed | EASY (IBKR auction feed; or proxy from `futures-ticks/ES` around 15:50–16:00 ET) |
| 9 | Put-call ratio (equity + index) | option volume/OI | MODERATE (CBOE aggregate daily = free; per-ticker needs vendor) |
| 10 | IV skew / risk reversal | option IV or bid/ask per strike | MODERATE (IBKR chain quotes w/ greeks) |
| 11 | Put-call-parity vol spread (Cremers-Weinbaum) | option IV (single-name) | MODERATE |
| 12 | Multi-level depth imbalance (OFI) | L2 book (we only hold L1) | MODERATE (IBKR `reqMktDepth`/L2) |

**Headline finding:** the single highest-value *immediate* backtest is **#1 Relative Volume** (full 20y+ single-name history, well-documented edge, trivial to compute). The single highest-value *near-term* addition is **#7 VIX term-structure slope** — it has the cleanest documented 1-week predictive coefficient in the entire literature (Fassas & Hourvouliades 2019, Table 2) and the missing input (VX futures) is easy to collect.

---

## 1. Data inventory (verified against S3 `trading-datalake-920641308584`)

| Prefix | Contents | Schema notes | Relevance |
|---|---|---|---|
| `macro/VIXCLS.json` | **Spot VIX**, daily, **1990-01-02 → 2026-08-13** | `{series, source, observations:[{date,value}]}` | VIX signals (level, spike, VRP) |
| `yf/etfs/SPY.json` | **SPY daily OHLCV, 1993-01-29 → 2026-08-21** (8,448 bars) | `{daily:[{ts,open,high,low,close,volume}]}` | index return + realized vol leg |
| `ibkr/equities/daily/*.parquet` | **Single-name daily OHLCV, ~20y** (AAPL from 2006-08) | cols `date,open,high,low,close,volume` | single-name signals (RVOL, vol) |
| `futures-bars/daily/ES/…` | ES futures daily, **2023-08 → 2026-08** (~3y) | per-day JSON | index futures leg |
| `futures-bars/intraday/ES/15min/…` | ES 15-min OHLCV, **2025-08 → now** | `{bars:[{ts,o,h,l,c,volume}]}` | intraday realized vol |
| `futures-ticks/ES/…` | **L1 top-of-book ticks**, sub-second, ~50 symbols | `{ts,bid,bidSize,ask,askSize,last,lastSize,volume}` | orderflow: quote imbalance, CVD, VPIN |
| `orderbook/MES/, MNQ/` | L1 snapshots ~10s, **5 days** (08-18→08-24) | same L1 schema | same (micro e-mini) |
| `options/*/chains.json` | **Chain metadata only** (strikes, expirations, tradingClasses) — 12 symbols, all futures options (ES/NQ/CL/GC/…) | **NO quotes, NO IV, NO greeks, NO volume/OI** | ⚠️ cannot compute IV/PCR/skew from this |
| `macro/*.json` | FRED: DGS2/10/30, T10Y2Y, CPI, UNRATE… | daily/monthly | context only |

**Confirmed gaps:**
- ❌ **No VIX futures (VX)** in `futures-bars/` or `futures-ticks/` (verified — no VX/VIX symbol).
- ❌ **No auction data** (`auction/` prefix does not exist; no imbalance feed).
- ❌ **No option quotes/IV/greeks** — `options/` holds chain skeletons only.
- ❌ **No L2 depth** — orderbook + ticks are top-of-book (L1) only.

---

## 2. Tier 1 — Testable NOW with existing data

### 2.1 Relative volume (RVOL) — *single-name & index*

**Signal definition:**
```
RVOL(t) = Volume(t) / (1/N) * Σ_{i=1..N} Volume(t-i)          # N = 20 or 21 trading days
```
Practitioner variant thresholds: `RVOL ≥ 2.0` ("in play"), `RVOL ≥ 3.0` ("extreme"). Academic equivalent: volume percentile over trailing window, or residual volume (log-vol − 20d avg log-vol).

**Tradable rule (continuation/momentum):**
- Entry: close-of-day `t` when RVOL ≥ 2 (top-decile volume shock) **and** the day's return is positive (volume+return aligned) → long next open.
- Exit/holding: hold 1–5 days (this captures the early, strongest leg of the documented 20-day premium).
- Refinement: rank cross-sectionally within a universe (top decile RVOL long / bottom decile short).

**Reported edge / significance:**
- Gervais, Kaniel & Mingelgrin (2001), *The High-Volume Return Premium*, **Journal of Finance 56(3):877–919** — unusually high 1-day/1-week volume is followed by positive abnormal returns over the following weeks; the high-minus-low volume portfolio "generates 20-day returns of 0.45% and 0.29% (0.49% and 0.21%) for small and large stocks respectively." The effect is **strongest over ~1–3 weeks** — at 1–5 days you capture the front-end, so expect a smaller (but same-sign) premium.
- Confirmed/robust across markets; the signal is *orthogonal* to momentum (information in volume is distinct from price).

**Backtestable with:** `ibkr/equities/daily/*.parquet` (single names, 20y) and `yf/etfs/SPY.json` + `futures-bars/daily/ES` (index). ✅ **Full history, no new data.**

**Priority: #1 — do this first.** Cheapest signal with the longest history and a clean, replicated effect.

---

### 2.2 Realized-vol expansion (vol spike) — *single-name & index*

**Signal definition (3 variants, all computable from daily OHLC):**
```
Parkinson:   σ²_P = (1 / 4 ln2) * (1/N) Σ (ln H_i − ln L_i)²
Garman-Klass:σ²_GK = 0.5(ln H_i−ln L_i)² − (2ln2−1)(ln C_i−ln O_i)²
RV:          σ²_RV = Σ r_i²  (r = log returns)
Expansion:   ΔRV(t) = RV(t) / RV_20d(t)      # ratio of current to trailing realized vol
```

**Tradable rule:**
- **Vol persistence (the robust, well-documented effect):** long a volatility position (or size-down risk) when `ΔRV ≥ 1.5–2` — realized vol is highly persistent (GARCH), so a spike predicts elevated vol over the next 1–5 days. This is a *volatility* trade, not directional.
- **Directional (leverage/vol-feedback):** after a *down-move* vol spike (ΔRV high, return < 0), the vol-feedback channel predicts elevated subsequent risk premium / short-term reversal — long equity 1–5d. After an *up-move* spike, expect short-term continuation. (Weaker and noisier than the vol-persistence trade.)

**Reported edge / significance:**
- Bollerslev, Tauchen & Zhou (2009), *Expected Stock Returns and Variance Risk Premia*, **Review of Financial Studies 22(11):4463–4492** — the variance risk premium (below) "explains more than fifteen percent of the ex-post time-series variation in quarterly returns." (Long-horizon, but establishes the vol→return link.)
- Volatility persistence is one of the most robust facts in empirical finance (GARCH/ARCH lineage, Engle 1982; Bollerslev 1986); the leverage effect (negative return-vol correlation) is documented in Black (1976), Christie (1982).
- Realized-vol *forecasting* (not directional returns) is strongly supported short-horizon: realized vol predicts future realized vol with high R².

**Backtestable with:** `ibkr/equities/daily` (OHLC → Parkinson/GK), `yf/etfs/SPY`, and `futures-bars/intraday/ES/15min` (high-frequency RV via 5/15-min returns). ✅ **Full history.**

**Priority: #2.** Directional edge at 1–5d is modest; vol-persistence edge is strong and usable for sizing/vol targeting even if not directional.

---

### 2.3 VIX level / VIX-SPX ratio (fear-gauge contrarian) — *index*

**Signal definition:**
```
VIX level:    VIX(t)  (CBOE 30-day SPX implied vol)
VIX-SPX ratio: VIX(t) / SPX(t)     # "fear per unit of index level" practitioner normalization
VIX z-score:   (VIX(t) − VIX_252d_mean) / VIX_252d_std
```
The academically documented signal is the **VIX level itself** (high VIX = fear = future buying opportunity). The `VIX/SPX` ratio is a practitioner re-scaling with thinner direct evidence — treat it as a normalization of the VIX-level signal (it is ~equivalent to VIX level after a slow-moving scale factor, so its *incremental* value over raw VIX is unproven).

**Tradable rule (contrarian):**
- Entry: long S&P futures/SPY when VIX (or VIX z-score) is in its top decile / above a threshold (e.g. VIX > 30–35, or VIX z > +2).
- Exit/holding: hold 5–10 days (the documented effect is strongest at 10–30d; at 1–5d it is weaker and front-loaded).
- Symmetric short side is *not* recommended — low VIX (complacency) has little short-horizon predictive power (Fassas & Hourvouliades 2019 found contango/normal curves "did not have significant predictive power").

**Reported edge / significance:**
- Simon & Wiggins (2001), *S&P Futures Returns and Contrary Sentiment Indicators*, **Journal of Futures Markets 21(5):447–462** — VIX, put-call ratio, and TRIN "frequently have statistically and economically significant forecasting power" over **10-, 20-, and 30-day** horizons; "buying S&P futures when the fear indicators were high rather than low" enhanced risk-adjusted profits out-of-sample (Jan 1989–Jun 1999). Contrarian.
- Whaley (2000, 2009) *Understanding the VIX* — VIX is the canonical fear gauge; spikes cluster with market bottoms.
- Caveat for our horizon: the effect is documented at **10–30 days**, not 1–5. At 1–5 days, VIX-spike mean-reversion is present but materially weaker (many false "knife-catches" in the first days).

**Backtestable with:** `macro/VIXCLS.json` (1990+) + `yf/etfs/SPY.json` (index return) or `futures-bars/daily/ES`. ✅ **Full history.** (VIX/SPX ratio is a one-line division — also testable, but flag as unproven-incremental.)

**Priority: #3.**

---

### 2.4 Quote / top-of-book imbalance — *index futures (intraday→1–2d)*

**Signal definition (computable from our L1 ticks):**
```
QI(t)  = (bidSize − askSize) / (bidSize + askSize)          # instantaneous queue imbalance
QI_agg = Σ_t QI(t) over a 1–15 min window                   # aggregate imbalance
Microprice = (bid·askSize + ask·bidSize)/(bidSize + askSize)  # size-weighted fair price
```
(Full multi-level version is the "Order Flow Imbalance" OFI of Cont–Kukanov–Stoikov — see §3.5.)

**Tradable rule (short-horizon):**
- Entry: when cumulative/smoothed `QI_agg` is strongly positive (bids persistently heavier) and price has not yet moved → long; negative → short.
- Exit/holding: **intraday to 1–2 days**. This signal decays rapidly — its documented power is at the tick-to-minutes scale; aggregated versions carry only weakly to daily horizon. Use for execution timing and same-day/short-horizon futures trades, not 5-day holds.

**Reported edge / significance:**
- Gould & Bonart (2016), *Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book*, **Market Microstructure and Liquidity 2(2)** (arXiv:1512.03492) — bid/ask queue imbalance has a "strongly statistically significant" relationship with the direction of the next mid-price move (logistic regression); improvement is "considerable" for large-tick stocks, "moderate" for small-tick.
- Cont, Kukanov & Stoikov (2014), *The Price Impact of Order Book Events*, **Journal of Financial Econometrics 12(1):47–88** — "linear relation between order flow imbalance and price changes, with a slope inversely proportional to market depth." (L2 OFI, theoretical anchor.)
- Chordia, Roll & Subrahmanyam (2002), *Order Imbalance, Liquidity, and Market Returns*, **JFE 65:111–130** — daily aggregate order imbalance is strongly contemporaneously related to returns and predicts next-day returns at index level.

**Backtestable with:** `futures-ticks/ES` (sub-second L1: bid/ask/bidSize/askSize) and `orderbook/MES|MNQ`. ⚠️ **Computable now, but history is only ~1 week** (ticks from 2026-08-17, orderbook 5 days) — insufficient for a robust *daily 1–5d* backtest today, but the signal is intraday so even a week gives useful microstructure evidence. **Start a rolling collection now.**

**Priority: #4** (highest *raw* short-horizon edge of Tier 1, but horizon mismatch + short history).

---

### 2.5 Cumulative delta (CVD) / VPIN — *index futures (intraday→1–2d)*

**Signal definition (computable from our L1 ticks):**
```
Trade sign (Lee–Ready):  s = +1 if last > mid; −1 if last < mid; else tick-rule
Delta(t)     = s · lastSize                                    # signed volume per trade
CVD(t)       = Σ_{t0..t} Delta                                  # cumulative volume delta
Bulk Volume Classification (BVC):
  V_buy  = V_bucket · Z( ΔP / σ_ΔP ) ;  V_sell = V_bucket − V_buy
VPIN = (1/n) Σ_buckets |V_buy − V_sell| / V_bucket              # n equal-volume buckets
```
Our `futures-ticks` rows carry `last`, `lastSize`, `volume`, `bid/ask` → both Lee–Ready sign and BVC are computable.

**Tradable rule:**
- **CVD divergence (practitioner reversal signal):** price makes a new high (low) while CVD makes a lower high (higher low) → short (long), intraday to 1–2 day hold. Practitioner note: divergence is *descriptive*, widely used (footprint/delta charts) but not rigorously backtested as standalone alpha.
- **VPIN (toxicity/vol):** when VPIN rises into its top decile → expect elevated short-horizon volatility and reduced liquidity → de-risk / buy vol, NOT a directional equity signal. The honest interpretation (below) is that VPIN predicts *volatility/toxicity*, not sign of returns.

**Reported edge / significance:**
- Easley, López de Prado & O'Hara (2012), *Flow Toxicity and Liquidity in a High-Frequency World*, **Review of Financial Studies 25(5):1457–1493** — VPIN is an early-warning measure of order-flow toxicity that rose to extremes ahead of the May 6 2010 Flash Crash.
- **Contested:** Andersen & Bondarenko (2014), *VPIN and the Flash Crash*, **Journal of Financial Markets 17:1–46** — argue VPIN's apparent predictive power is weak and largely mechanical (driven by volume/volatility). Treat as a *volatility/risk* signal, not directional alpha.

**Backtestable with:** `futures-ticks/ES` (+ other symbols). ✅ Computable now; ⚠️ short history (~1 week). Best used intraday → next-day, so history accumulates fast.

**Priority: #5** (directional claim is contested; vol-toxicity use is better supported).

---

### 2.6 Variance risk premium (VIX² − realized variance) — *index*

**Signal definition:**
```
VRP(t) = VIX²(t) − RV²(t)          # RV = realized vol of SPX/SPY over trailing 21d (or next 30d)
```
(VIX² and RV² are both annualized variance units, so the difference is the "premium" paid for variance insurance.)

**Tradable rule:** long SPX when VRP is high (investors over-paying for variance protection → subsequent high returns); low VRP → cautious. This is a **quarterly-horizon** signal in the literature.

**Reported edge / significance:**
- Bollerslev, Tauchen & Zhou (2009), RFS 22(11):4463–4492 — VRP (VIX² − realized variance) "explains more than fifteen percent of the ex-post time-series variation in quarterly market returns" and predicts returns with R² ~ 13–16% at the **quarterly** horizon (predictive R² is much lower at daily/weekly horizons).

**Backtestable with:** `macro/VIXCLS.json` + realized variance from `yf/etfs/SPY.json` (or `futures-bars/intraday/ES` for high-frequency RV). ✅ Full history.

**Priority: #6** — strong evidence but explicitly **not** a 1–5 day effect; include mainly as a regime/bias filter for the shorter-horizon signals.

---

## 3. Tier 2 — Requires new data (flagged by ease)

### 3.1 VIX term-structure slope / VIX-futures contango-backwardation — *index*  ⭐ **highest-value addition**

**Signal definition:**
```
Slope(t) = d(VIX_futures) / d(TTM)           # OLS slope of VIX futures (incl. spot at TTM=0) vs days-to-maturity
Contango:      Slope > 0   (spot VIX < futures)  → "complacency"
Backwardation:  Slope < 0   (spot VIX > futures)  → "panic"
Practitioner ratio: VIX / VIX3M   (or VXV/VIX inverse)
```
Fassas & Hourvouliades fit a linear model through cash VIX + all listed VX contracts each day; the slope is in vol-points-per-year (their sample: mean +0.023, min −0.08, max +0.068).

**Tradable rule (contrarian, asymmetric):**
- Entry: **long S&P when the curve is inverted (Slope < 0 / backwardation)** — the strongest, most significant predictor.
- Exit/holding: 1–5 days (documented significant at 1 day and 1 week; strongest and monotonic through 1 month–1 quarter).
- **Do NOT short on contango** — normal/upward-sloping curves had *no* significant short-horizon predictive power.

**Reported edge / significance (this is the cleanest short-horizon coefficient we found):**
- Fassas & Hourvouliades (2019), *VIX Futures as a Market Timing Indicator*, **Journal of Risk and Financial Management 12(3):113** — regressing future S&P500 returns on the term-structure slope (split positive/negative), the **negative-slope (backwardation) coefficient is significant at the 1% level at every horizon**:
  - K = 1 day: **−0.1687***, K = 1 week: **−0.5084***, K = 1 quarter: −1.1809*** (Table 2). Positive slope (contango) is insignificant at 1-day/1-week.
  - Interpretation: inverted curve → significantly higher forward returns (contrarian buy). The percentile regression (Table 3) confirms low-slope deciles predict higher returns, monotonically.
- Luo & Zhang (2012), *The Term Structure of VIX*, **Journal of Futures Markets 32:1092–1123** — the term structure embeds more information than spot VIX.
- Johnson (2017), *Risk Premia and the VIX Term Structure*, **JFQA 52(6):2461–2490** — the slope "summarizes nearly all this information," predicting excess returns of variance assets.
- Simon & Campasano (2014), *The VIX Futures Basis: Evidence and Trading Strategies*, **J. Futures Markets** — contango → short VX captures positive roll yield (vol trade, not equity directional).

**Missing data:** VX futures curve. ❌ Not collected.
**Collection ease: EASY** — (a) add `VX` (and optionally VX1/VX2 monthlies) to the existing `futures-ticks`/`futures-bars` IBKR pipeline (same code path as ES/NQ), or (b) pull CBOE's daily VIX9D/VIX/VIX3M/VIX6M term-structure from FRED/CBOE (free, no key). We already have spot VIX (`VIXCLS`), so only the futures leg is missing.

**Priority: #7 / top of Tier 2 — collect VX futures first.**

---

### 3.2 Opening/closing auction imbalance — *single-name & index*

**Signal definition:**
```
Closing auction imbalance:  (MOC buy − MOC sell)  /  total auction volume        # NYSE/Nasdaq imbalance feed
Auction volume share:       auction_volume / total_day_volume                     # Bogousslavsky-Muravyev "disagreement"
Opening auction imbalance:   (opening buy − sell) imbalance at the 9:30 cross
```

**Tradable rule:**
- **Closing imbalance → overnight/next-day reversal:** closing-auction price pressure reverts "by half shortly after the close and fully overnight" → fade large closing imbalances into the open.
- **Auction volume share → positive next-day drift:** higher auction-to-total-volume ratio (indexing-driven, disagreement) "positively predicts future stock returns."
- **Opening imbalance → intraday continuation:** opening auction imbalance predicts the first 30–90 min direction.

**Reported edge / significance:**
- Bogousslavsky & Muravyev (2023), *Who Trades at the Close? Implications for Price Discovery, Liquidity, and Disagreement*, **Journal of Financial Economics** — closing auction = 7.5% of daily volume in 2018 (3.1% in 2010); closing-price deviations revert by half post-close, fully overnight; auction-to-total-volume ratio positively predicts future returns.
- Narayan, Ahmed & Narayan (2015), *Do order imbalances predict Chinese stock returns?*, **Pacific-Basin Finance Journal** — order imbalances predict returns from 1-min out to 90-min; profits persist intraday.

**Missing data:** auction imbalance feed. ❌ Not collected (no `auction/` prefix).
**Collection ease: EASY** — IBKR auction imbalance feed, or **proxy now**: compute closing-auction volume/pressure from `futures-ticks/ES` (or `orderbook/`) in the 15:50–16:00 ET window (the imbalance is published every second into the close). Opening imbalance proxy from first minutes of ticks/bars.

---

### 3.3 Put-call ratio (equity + index) — *contrarian*

**Signal definition:**
```
PCR_total   = put_volume / call_volume
PCR_equity  = equity-option put/call volume      # excludes index options
PCR_index   = index-option put/call volume       # "smart money" version
Smoothed:   PCR_5d = 5-day MA of PCR_total ;  PCR_21d = 21-day MA
```

**Tradable rule (contrarian):** long S&P when PCR is in its top decile (excessive put buying = fear); exit when it reverts below its 21-day MA. Horizon 5–20 days. (The 21-day MA is the widely-followed CBOE convention.)

**Reported edge / significance:**
- Simon & Wiggins (2001), JFM 21(5):447–462 — put-call ratio (along with VIX and TRIN) has significant contrarian forecasting power for S&P futures over 10–30 days.
- Dennis & Mayhew (2002) and Bandopadhyaya & Jones (2006) document PCR's information content; equity-only PCR is the better sentiment gauge (index PCR is more hedging/structural).

**Missing data:** option volume (or OI) by put/call. ❌ Not collected — `options/` has only chain skeletons.
**Collection ease: MODERATE** — CBOE publishes aggregate daily total/equity/index PCR free; per-ticker PCR needs an options-data vendor (ORATS, ThetaData, Polygon, or IBKR option volume subscriptions).

---

### 3.4 Implied-vol skew / risk reversal — *index & single-name*

**Signal definition:**
```
25Δ risk reversal (index):  RR = σ_imp(25Δ put) − σ_imp(25Δ call)      # "put skew"
Put skew (single-name):     Skew = σ_imp(OTM put) − σ_imp(ATM)          # or ATM−OTM-call
Cremers-Weinbaum vol spread: VS = σ_imp(call) − σ_imp(put)  at matched K,T  # put-call parity deviation
```

**Tradable rule:**
- Index put skew (very negative RR) → long-horizon crash hedging signal, weak for 1–5d directional trading.
- Single-name **Cremers-Weinbaum vol spread**: long stocks with relatively expensive calls (VS > 0), short stocks with expensive puts — this is a **cross-sectional 1-week to 1-month** signal with documented spread returns.

**Reported edge / significance:**
- Cremers & Weinbaum (2010), *Deviations from Put-Call Parity and Stock Return Predictability*, **JFQA 45(2):335–367** — the call-minus-put IV spread predicts returns; a weekly-rebalanced portfolio long high-spread/short low-spread quintiles earns significant abnormal returns.
- Dennis & Mayhew (2002), *Risk-Neutral Skewness: Evidence from Stock Options*, **JFQA 37(3):471–493** — risk-neutral skewness is informative and more negative for high-beta stocks.
- Bali & Murray (2013) — risk-neutral skewness predicts negative cross-sectional returns.

**Missing data:** per-strike option IV (or bid/ask + underlying to solve IV). ❌ Not collected.
**Collection ease: MODERATE** — IBKR `reqMktData`/`calculateImpliedVolatility` on ES/NQ/equity options, or a vendor (ORATS/ThetaData). Note: our `options/` chain metadata (strikes + expirations) is a useful *scaffold* to request quotes against.

---

### 3.5 Multi-level depth imbalance (OFI) — *futures/equities*

**Signal definition:**
```
OFI = Σ_levels [ e_k · Δq_k^bid − e_k · Δq_k^ask ]      # Cont-Kukanov-Stoikov
    = sum over L2 levels of (net change in bid size − net change in ask size), weighted
```
We currently hold **only L1** (top-of-book), which gives the rank-1 approximation (`Δq_bid − Δq_ask`).

**Reported edge / significance:** Cont, Kukanov & Stoikov (2014), JFEcon 12(1):47–88 — OFI is linearly related to concurrent and short-horizon price change, slope inversely proportional to depth; OFI is a stronger short-horizon predictor than top-of-book imbalance alone.

**Missing data:** L2 depth snapshots. ❌ Not collected (L1 only).
**Collection ease: MODERATE** — IBKR `reqMktDepth` (L2) on ES/NQ, or Polygon/other L2 vendor. Marginal gain over our existing L1 quote-imbalance signal is real but modest at 1–5d horizons.

---

## 4. Recommended execution order

1. **Backtest #1 (RVOL) + #2 (realized-vol expansion) immediately** on `ibkr/equities/daily` (20y single-name) + `yf/etfs/SPY` (33y index) — zero new data, longest history, cleanest methodology (panel regressions + long/short deciles + 1/2/3/4/5-day forward returns with Newey-West t-stats).
2. **Backtest #3 (VIX level/VIX-SPX) + #6 (VRP) immediately** on `macro/VIXCLS` + `yf/etfs/SPY` — full 1990+ history; the 1–5d edge is the weak end of a documented 10–30d effect, so report both horizons.
3. **Build the VX futures collector** (EASY, reuses the `futures-ticks` pipeline) → then backtest **#7 VIX term-structure slope**, the strongest documented 1-week signal (Fassas & Hourvouliades coefficient −0.51*** at 1-week). This is the single best ROI on new data.
4. **Add an auction-imbalance collector** (EASY) → backtest **#8**; meanwhile proxy it from `futures-ticks/ES` in the 15:50–16:00 ET window.
5. **Let `futures-ticks` accumulate** (currently ~1 week) so **#4 (quote imbalance)** and **#5 (CVD/VPIN)** can be tested at 1–5d forward with enough observations — these are the highest *raw* short-horizon edge but need history.
6. **Defer #9–#12** (PCR, IV skew, CW spread, L2 OFI) — highest data cost per unit of edge; revisit once VX + auction are in.

---

## 5. Source list (all verified via search + full-text fetch)

1. Gervais, S., Kaniel, R., Mingelgrin, D. (2001). "The High-Volume Return Premium." *Journal of Finance* 56(3):877–919.
2. Simon, D.P., Wiggins, R.A. (2001). "S&P Futures Returns and Contrary Sentiment Indicators." *Journal of Futures Markets* 21(5):447–462.
3. Bollerslev, T., Tauchen, G., Zhou, H. (2009). "Expected Stock Returns and Variance Risk Premia." *Review of Financial Studies* 22(11):4463–4492.
4. Fassas, A., Hourvouliades, N. (2019). "VIX Futures as a Market Timing Indicator." *Journal of Risk and Financial Management* 12(3):113.
5. Luo, X., Zhang, J.E. (2012). "The Term Structure of VIX." *Journal of Futures Markets* 32:1092–1123.
6. Johnson, T.L. (2017). "Risk Premia and the VIX Term Structure." *JFQA* 52(6):2461–2490.
7. Simon, D.P., Campasano, J. (2014). "The VIX Futures Basis: Evidence and Trading Strategies." *Journal of Futures Markets*.
8. Gould, M.D., Bonart, J. (2016). "Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book." *Market Microstructure and Liquidity* 2(2); arXiv:1512.03492.
9. Cont, R., Kukanov, A., Stoikov, S. (2014). "The Price Impact of Order Book Events." *Journal of Financial Econometrics* 12(1):47–88.
10. Easley, D., López de Prado, M., O'Hara, M. (2012). "Flow Toxicity and Liquidity in a High-Frequency World." *RFS* 25(5):1457–1493.
11. Andersen, T., Bondarenko, O. (2014). "VPIN and the Flash Crash." *Journal of Financial Markets* 17:1–46.
12. Bogousslavsky, V., Muravyev, D. (2023). "Who Trades at the Close?" *Journal of Financial Economics*.
13. Narayan, P.K., Ahmed, H.A., Narayan, S. (2015). "Do order imbalances predict Chinese stock returns?" *Pacific-Basin Finance Journal*.
14. Cremers, M., Weinbaum, D. (2010). "Deviations from Put-Call Parity and Stock Return Predictability." *JFQA* 45(2):335–367.
15. Dennis, P., Mayhew, S. (2002). "Risk-Neutral Skewness: Evidence from Stock Options." *JFQA* 37(3):471–493.
16. Chordia, T., Roll, R., Subrahmanyam, A. (2002). "Order Imbalance, Liquidity, and Market Returns." *JFE* 65:111–130.
17. Whaley, R. (2000/2009). "The Investor Fear Gauge / Understanding the VIX." *Journal of Portfolio Management*.

---

## 6. Honesty / caveats

- **Horizon mismatches are flagged explicitly.** Several strong papers (Simon & Wiggins, BTZ, GKM peak effect) are documented at 10–30 days or quarterly; I state where the 1–5 day edge is the *weak* end of a longer effect. None of the "1–5 day" magnitudes above are fabricated — where a paper reports a specific horizon, I quote that horizon.
- **VPIN and CVD divergence are contested/descriptive** (Andersen–Bondarenko critique; practitioner folklore) — not to be traded as standalone directional alpha without our own validation.
- **`options/` in our lake is metadata-only.** None of the options-derived signals (PCR, IV skew, CW spread, VIX term structure) can be computed from current data — all require collection. The one options *adjacent* signal we *can* run today is spot-VIX-based (§2.3, §2.6) because `macro/VIXCLS.json` is complete.
- **Orderflow history is ~1 week.** Quote-imbalance, CVD, and VPIN are computable *now* but not yet backtestable at daily forward horizons with statistical power; they need ~3–6 months of rolling collection.
