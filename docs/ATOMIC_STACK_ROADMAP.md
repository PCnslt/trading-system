# ATOMIC-STACK Roadmap & Status

The full multimodal AI/ML discovery program remains OPEN. The news branch is ONE
information stream, not the endpoint. This doc preserves the complete architecture.

## Information modalities (each earns survival via incremental OOS evidence)
| modality | status |
|---|---|
| PRICE / VOLUME / VOLATILITY (engineered) | TESTED — no 30m cross-sectional edge (LightGBM rank IC −0.008) |
| CROSS-SECTIONAL / MARKET / SECTOR state | TESTED — null |
| NEWS (forward) | UNDER PROSPECTIVE VALIDATION (day 1, 721 events) |
| NEWS (historical) | DATA-BLOCKED (no free deep archive) |
| SEC 8-K | TESTED — no universal continuation edge |
| NLP (FinBERT-class) | GATED (needs a defined extraction task + compute) |
| OPTIONS information | DATA-BLOCKED (hypothesis-doc first) |
| MICROSTRUCTURE (trade/quote) | DATA-BLOCKED (OHLC null != microstructure null) |
| SOCIAL (Reddit/StockTwits/X) | EXPERIMENTAL (free/low-cost first) |
| GRAPH (dynamic market graph) | GATED (point-in-time construction) |
| FOUNDATION MODELS (TimesFM/Chronos/Moirai/...) | GATED (must consume a *different* representation than the 13 scalars) |

## Model zoo (gated by evidence, not abandonment)
Classical (ridge/lasso/logistic/elastic-net/rank/calibrated) · Boosting (LightGBM/XGB/CatBoost/RF)
· Neural tabular (MLP/TabNet/FT-Transformer) · Sequential (LSTM/GRU/TCN/PatchTST/iTransformer)
· Foundation (TimesFM/Chronos/Moirai/Granite/Lag-Llama/TiRex/Kronos) · Graph (GNN/GAT/temporal)
· Multimodal fusion · Ensemble/stacking (leakage-safe) · Meta-model · Regime detector.

## Bounded interpretation of the LightGBM null
The 13-scalar engineered feature space did NOT demonstrate OOS 30m cross-sectional signal
under the tested target/horizon/validation design. This does NOT prove information is absent
from: full intraday sequences, trade/quote, news streams, or market-wide cross-sectional state.
Those are *different representations* answering *different questions*.

## Current priority order
NOW: live price-join · real-time predictions · outcome resolver · cron (done) · health monitor · immutable PIT verify.
PARALLEL: reusable infra — model/feature/experiment registries · walk-forward engine · model graveyard · cost engine · target registry · prediction ledger.
LATER/GATED: foundation models · GNN · multimodal · social · options · microstructure · paid data.

## Data-acquisition firewall (unchanged)
Every paid dataset requires: hypothesis → expected info gain → min fields → min history → cost → decision threshold.
Never buy data → then search. Always: identify missing info → specify falsifiable hypothesis → justify acquisition.

## Safety (immutable)
CASH / LIVE=DISABLED / TRADING=DISABLED / OPTIONS=ISOLATED / VALIDATED_STRATEGIES=0 / REAL_ORDERS=0.
Research OPEN. Trading DISABLED.
