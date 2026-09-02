# ATOMIC-STACK MASTER ARCHITECTURE (canonical source of truth)

> This file is the permanent specification. If conversational context is lost,
> this document — plus the registries it references — is authoritative.
> Update it whenever the program changes.

## 1. Mission
Discover whether a robust, statistically defensible, cost-adjusted, $700-executable
short-horizon equity edge exists that prior research missed. Null = success; false
positive = failure. Maximize expected risk-adjusted return subject to strong evidence
+ capital preservation. Never force a return target.

## 2. Ground truth (preserve exactly)
ACCOUNT = CASH · CAPITAL ≈ $700 · LIVE = DISABLED · TRADING = DISABLED ·
OPTIONS = ISOLATED · VALIDATED_STRATEGIES = 0 · REAL_ORDERS = 0.

Research status:
- PRICE/TECHNICAL ENGINEERED FEATURES → NO ROBUST 30M CROSS-SECTIONAL EDGE (LightGBM rank IC −0.008)
- HISTORICAL NEWS → DATA-BLOCKED (no free deep archive)
- SEC 8-K → TESTED; NO UNIVERSAL CONTINUATION EDGE
- FORWARD NEWS → PROSPECTIVE VALIDATION RUNNING (day 1, 721 events, 40 sym, 0 conclusions)
- FOUNDATION MODELS / GRAPH / MULTIMODAL → GATED, NOT ABANDONED
- OPTIONS INFO / TRADE-QUOTE MICROSTRUCTURE → DATA-BLOCKED
- SOCIAL → DATA-BLOCKED / PROSPECTIVE where free

## 3. Scientific correction (permanent)
LightGBM null established: the 13-scalar engineered feature representation showed no OOS
30m cross-sectional alpha under the tested design. It did NOT establish: returns are
unpredictable / AI cannot predict / foundation models can't help / more info can't help.
Justification for keeping branches alive (NOT proof of alpha): 2023 J.Fin.Econometrics
5-min market-return predictability from lagged constituent returns + ML; 2025 Mgmt.Sci.
high-frequency predictability from trade/quote predictors, sensitivity to timeliness.

## 4. Canonical architecture
RAW DATA (market / events / external) → POINT-IN-TIME LAYER → FEATURE/REPRESENTATION STORE
→ (cross-sectional · temporal sequences · event) → MODEL ZOO (statistical · boosting ·
neural · foundation · graph) → ENSEMBLE/STACKING → RETURN DISTRIBUTION → TRADEABILITY
FILTER → COST/EXECUTION → WALK-FORWARD OOS → FORWARD PAPER → VALIDATION FIREWALL
→ CANDIDATE (still paper-only).

## 5. Data modality registry (see research/modality_registry.json)
PRICE, VOLUME, VOLATILITY, CROSS_SECTION, MARKET_STATE, SECTOR_STATE, INDUSTRY_STATE,
NEWS, SEC_FILINGS, FINANCIAL_NLP, OPTIONS, MICROSTRUCTURE, SOCIAL, MACRO, GRAPH.
Each carries: status/availability/depth/timestamp_quality/PIT_quality/cost/hypothesis/
min_history/min_fields/expected_gain/decision_threshold.

## 6. Point-in-time layer (critical)
Every feature must answer "what was available at prediction time?" via observed_at,
effective_at, source_timestamp, ingestion_timestamp. Never use today's universe/revised
fundamentals/future sector/future news/completed-day volume/future corporate actions/
future options/future labels for historical predictions. Automated leakage tests required.

## 7. Feature store families
Price (returns/log/multi-horizon/gap/range/ATR/VWAP-dist/high-low-dist/realized-vol/jump).
Volume (rel-vol/accel/surprise/turnover/concentration). Cross-sectional (rank_return/
rank_volume/rank_vol/sector-relative/industry-relative/market-relative/dispersion/breadth/
leadership/laggard). Time (minute-of-day/day-of-week/month/expiration-prox/session).
Market-state (SPY/QQQ/IWM/VIX/breadth/dispersion/realized-vol/trend/risk-on-off).
PLUS full intraday sequences (last 5/15/30/60/120 bars × channels return/volume/range/
vol/market-rel/sector-rel/cs-rank) — a genuinely different representation from the 13 scalars.

## 8. Model zoo (hierarchy)
Tier1 cheap: Ridge/ElasticNet/Logistic/linear-rank/LightGBM/XGBoost/CatBoost/RF/ExtraTrees.
Tier2 neural tabular: MLP/FT-Transformer/TabNet.
Tier3 sequential: LSTM/GRU/TCN/Transformer/PatchTST/iTransformer.
Tier4 foundation (registry, tested not assumed): TimesFM(-3.0 multivariate) / Chronos-2 /
Moirai / Kronos / Granite-TS / TiRex(-2) / Toto / Lag-Llama / PatchTST / iTransformer.
Evaluate foundation models on rank IC / directional / top-decile / conditional return /
tail capture / cost-adjusted / drawdown / Sharpe — NOT forecast RMSE alone.

## 9. Branches
- Financial NLP: FinBERT-class extract event/direction/severity/novelty/surprise/uncertainty/
  entity/duration. LLM transforms unstructured → testable variables; never decides trades.
- News: forward ledger (NewsAPI/RSS → normalize → dedupe → immutable ledger → observed_at
  boundary → price-join → pre-registered prediction → outcome → eval). No backfill.
- Options-as-information: predict underlying, not "trade options". Fields: call/put vol,
  OI, IV/IV-chg, skew, term structure, delta/gamma exposure, unusual activity. Data-blocked.
- Microstructure: bid/ask/spread/mid/trade size+direction/quote chg/depth/imbalance/
  intensity/impact. Distinct from OHLC. Data-blocked.
- Social: Reddit/StockTwits/X (legit). sentiment/velocity/accel/author-count/disagreement/
  propagation/novelty. Info first, model second. No paid feeds without evidence.
- Daily-gainer: top 1/2/5/10%; predict rank/excess/abs return/extreme P. PIT universe only.
- Extreme-move: P(|R|>X), P(R>X), P(R<-X) — rare high-opportunity setups.
- Return-distribution: expected_return, q05/q25/q50/q75/q95, P(up), P(large up/down),
  expected vol, MFE, MAE.
- Model disagreement, meta-model (leakage-safe OOF), regime engine, self-supervised,
  multimodal fusion (cross-modal attention; incremental ablation).

## 10. Validation firewall (mandatory)
Chronological walk-forward (default). Locked final OOS (opened once). Symbol/time/regime
holdouts. Purged/embargoed cross-sectional folds. Placebo (timestamp/symbol/feature/target/
market/wrong-event/future-event shuffles). Clustering by date/symbol. Multiple-testing
ledger (no silent discards). Ablation (baseline vs +modality vs +shuffled-modality).
Stacking-leakage prohibition. Model graveyard with failure_reason. Champion/challenger.

## 11. Data & compute firewalls
Data: hypothesis → missing-info → min-fields → min-history → expected-gain → cost →
decision-threshold → authorization. NEVER buy-data-then-search.
Compute: CPU → cheap baseline → small neural → GPU-spot → large foundation. Benchmark
prediction-quality-per-dollar, not prediction-quality.

## 12. Deployment firewall
RESEARCH → OOS → FORWARD PAPER → RISK REVIEW → EXECUTION REVIEW → CAPITAL REVIEW →
HUMAN AUTHORIZATION. Never model-success → LIVE. Prediction exists before outcome;
no retroactive modification.

## 13. Implementation order (do not wait for news)
1 news collection ✓ · 2 price-join+prediction ✓ · 3 reusable platform (feature/target/
dataset/experiment registries, walk-forward engine, cost engine, evaluation engine,
prediction ledger, model registry, graveyard) · 4 full intraday sequence datasets ·
5 test Ridge/LightGBM/XGBoost/MLP/TCN/LSTM/Transformer on sequences · 6 market-wide
cross-sectional representation · 7 cross-sectional sequence models · 8 forward news eval
when sample meaningful · 9 financial NLP · 10 news+price fusion · 11 dynamic graph ·
12 GNN/temporal graph · 13 TSFM benchmark harness · 14 multimodal fusion · 15 social ·
16 options-data (if justified) · 17 trade/quote (if justified) · 18 PIT equity (if justified) ·
19 ensemble/meta · 20 forward championship.

## 14. Philosophy
Aggressive discovery + extremely conservative acceptance. Search broadly, kill aggressively,
require evidence, never manufacture evidence. The program must not forget what it learned.

## 15. Registries (see files)
research/data_source_registry.json · research/ai_model_registry.json ·
research/prediction_target_registry.json · research/model_experiment_registry.json ·
research/modality_registry.json · research/model_graveyard/ · research/model_predictions/ ·
research/model_features/ · research/model_evaluations/ · research/forward_validation/.
