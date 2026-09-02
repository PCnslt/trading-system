# Forward News Information-Arrival Experiment — Schema & Point-in-Time Rules

## Layered architecture (each reproducible)
```
RAW NEWS (immutable, cold)  ->  NORMALIZED NEWS  ->  POINT-IN-TIME EVENT
   ->  FEATURE SNAPSHOT  ->  PRE-EVENT PREDICTION (immutable)  ->  OUTCOME (appended)
```

## Immutability rules
- `observed_at_utc` = when OUR collector fetched the item = **information-availability boundary**. All predictions/features use only info ≤ observed_at.
- `published_at_utc` = source timestamp (may be empty/untrusted → flagged, never silently used).
- Events are append-only; `append_jsonl` never overwrites an existing `event_id`.
- Predictions are written BEFORE the outcome window; the resolver only appends outcome fields, never edits the prediction.

## Leakage controls
- No backfill of historical news. The ledger starts accumulating from first run forward only.
- No future article content used; dedupe by `source_url_hash`.
- Repeated syndications are NOT independent events (deduped by URL/title hash).
- Universe is `CURRENT_UNIVERSE_FORWARD_ONLY` (40 symbols) — NOT a historical-survivorship claim.

## Event record fields
event_id, observed_at_utc, published_at_utc, source, symbol, headline, source_url_hash,
news_count_5m/15m/30m/60m (filled at price-join), pre_return_*, market_return_*, sector_return_*,
relative_return_*, volume_state, volatility_state, gap_state, time_of_day.

## Prediction record fields
signal_id, timestamp, symbol, direction, predicted_edge, confidence, model_version,
feature_snapshot_hash, then (appended later) realized_return_5m/15m/30m/60m, MAE, MFE,
outcome_timestamp, status (UNRESOLVED -> RESOLVED).

## Pre-registered hypotheses (v0, NOT optimized)
H1 velocity->continuation, H2 velocity->reversal, H3 neg-reaction+hi-vel->continuation,
H4 neg-reaction+lo-vel->reversal, H5 pos-reaction+hi-vel->continuation, H6 pos-reaction+lo-vel->reversal.

## Acceptance (eventual)
positive OOS conditional return + statistical significance + economic significance + realistic
costs + date/symbol/regime stability + placebo failure + no-lookahead. CANDIDATE_EDGE != VALIDATED_STRATEGY.
