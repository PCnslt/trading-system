# ATOMIC-STACK — AI Trading Intelligence System (Architecture & Research Design)

Status: RESEARCH DESIGN (Phase 0). No implementation beyond the feature-engine
prototype yet. LIVE=DISABLED, no orders, no data purchase.

---

## 0. Purpose (verbatim, non-negotiable)

Determine whether the *joint* information across market/price, technical state,
cross-sectional structure, market/sector context, volatility/liquidity, events,
news, social, options, fundamentals, and learned representations materially
changes the conditional distribution of short-horizon stock returns — and
whether any such edge survives realistic costs and is executable by the ~$700
Robinhood CASH account.

The objective is **discovery and evidence**, never deployment. The system must
be simultaneously **aggressive in research, ruthless in validation**.

---

## 1. Honest prior (why this exists)

~35 mechanisms have been tested and killed with documented cause: beta,
survivorship, spread artifact, liquidity premium, inversion, negative alpha,
noise, sub-cost volatility. The individual-indicator, conditional-combination,
and simple-cross-sectional approaches were all negative.

This is evidence, NOT permission to declare the prediction problem impossible.
The open question is *which* explanation is correct: insufficient
representation, wrong target, wrong horizon, wrong cross-sectional
architecture, missing information (trade/quote, news, social, options), poor
model class, poor calibration, poor ranking objective, or regime mixing.

This program exists to answer that question rigorously.

---

## 2. Architecture (target, built incrementally)

```
DATA LAKE (S3/DynamoDB)
  ├─ MARKET/PRICE (OHLCV, intraday 1m/5m, daily, futures)
  ├─ TEXT/EVENTS (SEC EDGAR, earnings; news/social = NOT YET ACQUIRED)
  └─ RELATIONSHIPS (sector/ETF/industry membership, correlation)
        ↓
FEATURE / STATE REPRESENTATION LAYER (feature store, versioned, causal)
        ↓
NUMERICAL MODELS (ridge/elastic-net, LightGBM/XGBoost, random forest)
FOUNDATION MODELS (Chronos/TimesFM/Moirai — requires GPU, see §6)
SPECIALISTS (reversal, momentum, breakout, event, extreme-move)
        ↓
MODEL PREDICTION / EMBEDDING LAYER
        ↓
RETURN MODEL │ RANKING MODEL │ EVENT MODEL
        ↓
MIXTURE-OF-EXPERTS / META-MODEL (out-of-fold only)
        ↓
UNCERTAINTY + OOD ENGINE
        ↓
CROSS-SECTIONAL OPPORTUNITY RANKER
        ↓
COST / EXECUTION TRANSLATION
        ↓
RISK ENGINE (existing PreTradeRiskFirewall, authoritative state)
        ↓
PAPER / FORWARD VALIDATION (prediction-only, immutable ledger)
```

Not every component is built immediately. The architecture grows into this.

---

## 3. Prediction targets (not "predict the price")

Conditional distribution + cross-sectional ranking, at horizons 1m/5m/10m/15m/
30m/60m/120m/rest-of-day/next-day:

- P(R>0), E[R], P(R>±0.25%/±0.5%/±1%/±2%)
- P(top 1%/5%/10% daily return), P(bottom 1%/5%/10%)
- residual (market-neutral) and sector-neutral expected return
- volatility-adjusted return

**Ranking is a first-class objective.** Target transformations tested: raw,
log, vol-normalized, market-residual, sector-residual, rank, quantile.

---

## 4. Feature families (causal, availability-timestamped)

1. Technical states (EMA/SMA slope, RSI, MACD, VWAP distance, Bollinger, ATR,
   ADX, stochastic, Donchian, momentum)
2. Cross-sectional (return rank, volume rank, volatility rank, dispersion,
   breadth, relative strength vs market/sector)
3. Market/sector context (market return, sector return, breadth, advance/decline)
4. Volatility/liquidity (realized vol, range expansion, volume ratio, spread
   proxy where available)
5. Time-of-day (explicit session states — first 5m/15m/30m, midday, close)
6. Event/information state (earnings, SEC filings, gap, abnormal volume/return)
7. NOT YET AVAILABLE: news, social, options flow, trade/quote microstructure,
   point-in-time fundamentals — see §5.

Every feature carries: definition, lookback, timestamp availability, economic
mechanism, missing-data behavior, causal-at-decision-time flag, redundancy map.

---

## 5. Data reality (what is and is NOT available)

| source | status | note |
|---|---|---|
| 5-min OHLCV (40 liquid) | ✅ available | 8 months, clean (post-audit) |
| 1-min OHLCV | ✅ available | ~2yr, monthly parquet |
| daily OHLCV (1000) | ⚠️ `open` UNRELIABLE | close usable; open 64-85% == close |
| crypto daily (13) + 1h | ✅ available | |
| SEC EDGAR 8-K + earnings | ✅ available | 19 mega-caps, 30yr; timestamped |
| futures daily | ⚠️ shallow (~1-3yr) | carry/seasonality DATA-BLOCKED |
| news / social / options flow / trade-quote / PIT fundamentals | ❌ NOT acquired | DATA-BLOCKED, purchase-justified only |
| 1,000-strategy library | ❌ NOT_RECEIVED | ingest on delivery, verbatim IDs |

---

## 6. Compute reality (honest)

- AWS t3.medium, CPU-only, no local GPU.
- Foundation models (Chronos/TimesFM/Moirai), LLMs, and deep transformers
  require **GPU spot instances** (estimated, gated on demonstrated signal).
- Baseline path: DuckDB/Polars/Parquet feature store on CPU; LightGBM/XGBoost
  and regularized linear models are cheap and sufficient for the *first* test
  of "does information exist at all."
- Foundation-model and LLM tracks are **gated** on (a) GPU spot budget and
  (b) a baseline showing incremental signal worth the cost.

---

## 7. Validation firewall (non-negotiable)

- Chronological walk-forward (never random CV).
- Final LOCKED OOS period, opened exactly once at the end.
- Symbol holdouts (train A-M / test N-Z, then reverse).
- Time holdouts (bull/bear/high-vol/low-vol/COVID/2022/2025).
- Market-wide placebo (shuffled labels/timestamps/identities).
- Multiple-testing accounting (experiment count tracked; FDR where applicable).
- Clustered standard errors by date.
- Leakage audit: every feature has availability_timestamp; no future universe
  membership, no final Yahoo ranking as an input, no out-of-fold base-model
  predictions feeding the meta-model (stacking leakage).
- Cost scenarios: optimistic/base/pessimistic/extreme (spread/slippage/latency).
- Frozen model + champion/challenger discipline (no constant re-selection).

---

## 8. Experiment accounting (the research factory)

Every experiment: experiment_id, git_commit, data_snapshot, feature_version,
target, universe, model_version, hyperparameters, train/val/OOS periods, cost
assumptions, seed(s), results. No anonymous experiments. Killed models →
research graveyard with cause.

---

## 9. Decision tree (terminal)

```
NO PREDICTIVE INFORMATION            → STOP
PREDICTIVE BUT SUB-COST              → RESEARCH / STOP
PREDICTIVE + COST-ADJUSTED           → FORWARD PAPER VALIDATION
PAPER VALIDATED                      → EXECUTABILITY ANALYSIS
EXECUTABLE WITH $700                 → CANDIDATE (explicit auth only)
NOT EXECUTABLE WITH $700             → CAPITAL/BROKER BLOCKED
```

Statuses: HYPOTHESIS → RESEARCHING → PREDICTIVE → OOS-PREDICTIVE →
COST-ADJUSTED → EXECUTABLE → PAPER-VALIDATED → VALIDATED (or KILLED/DECAYED).

---

## 10. What we build FIRST (next concrete steps)

1. **Feature store + baselines** (extend feature_engine.py): full causal feature
   set, and a "no free lunch" baseline suite (random, market, momentum,
   reversal, time-of-day) so every future model has a floor to beat.
2. **Regularized linear / LightGBM cross-sectional ranking** with strict
   walk-forward — the first honest test of "does joint information beat
   baselines." (This is the natural next step after the null linear result.)
3. **Prediction ledger + shadow mode** against live stream (prediction-only).
4. **Deferred until signal demonstrated:** news/social/options acquisition,
   foundation models, graph models, multimodal fusion, meta-learning.

---

## 11. Prohibitions (absolute)

Never fabricate data/results/features/performance/OOS; never use future info,
future universe membership, or final rankings as inputs; never tune the locked
OOS set; never cherry-pick model/seed/threshold; never hide negative results;
never place real orders; never weaken the risk firewall; never claim a paper
proves profitability it does not.

---

## 12. Terminal state (unchanged)

CASH / LIVE=DISABLED / TRADING=DISABLED / OPTIONS=ISOLATED /
VALIDATED_STRATEGIES=0 / REAL ORDERS=0.
