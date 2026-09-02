# Phase 4 — Intraday SEQUENCE dataset + sequential-vs-flat benchmark

Research only: no trading, no data purchase, no model promotion.

## What this does

Builds a per-symbol 5-minute feature frame *and* a sequence representation for
40 liquid US equities from the S3 data lake, then benchmarks sequential models
(MLP, 1D-CNN) against flat baselines (Ridge, LightGBM) on the forward 30-minute
return target (`30m_return`, horizon = 6 bars).

## Files

- `build_dataset.py` — downloads raw parquet, builds causal features + sequence
  tensors, applies chronological 70/30 split, writes `cache/`.
- `benchmark.py` — trains/evaluates the five models, writes
  `../sequence_results.json`.
- `cache/` — intermediate artifacts (git-ignored):
  - `samples.parquet` — 518,269 samples (flat features + label + split).
  - `seq.npy` — (518,269, 12, 4) float32 sequence tensor.
  - `meta.json` — dataset metadata.

## Dataset

- Source: `s3://trading-datalake-920641308584/ibkr/equities/5min/{SYMBOL}.parquet`
  (40 symbols, 2025-12-30 → 2026-09-01, 5-min OHLCV).
- 519,709 raw bars → 518,269 usable samples (warmup + tail dropped).
- Flat features (all causal, ≤ t): `r1 r3 r6 r12 rsi14 vwap_dist rel_vol
  realized_vol20 cs_ret_rank cs_vol_rank minute_of_day`.
- Sequence channels (last 12 bars × 4): `[return, volume_ratio, range_pct,
  vwap_dist]` — the raw recent bar history, genuinely different from the
  aggregated flat scalars.
- Label = forward 30-min return (`close.shift(-6)/close - 1`), strictly future.
- Cross-sectional ranks (`cs_ret_rank`, `cs_vol_rank`) are computed at each
  timestamp across the ~40 names using only data ≤ t.
- Split: chronological 70/30 by bar timestamp (threshold
  `2026-06-22 09:55 ET`), never shuffled. Train 361,076 / test 157,193.

## Results (see `../sequence_results.json` for full detail)

| model             | rank IC  | top-decile excess (bp) |
|-------------------|----------|------------------------|
| Ridge (flat)      | -0.0042  | +0.75                  |
| LightGBM (flat)   | +0.0017  | +1.22                  |
| momentum (past r6)| -0.0015  | -0.16                  |
| MLP (sequence)    | +0.0042 ± 0.0049 | +1.22 ± 0.88  |
| 1D-CNN (sequence) | +0.0069 ± 0.0068 | +2.42 ± 2.24  |

**Honest verdict: SEQUENCE rank_IC ≈ 0.** No model finds a tradable 30m
intraday cross-sectional signal. The 1D-CNN posts the largest *nominal* mean
rank IC (0.0069) but its cross-seed standard deviation (0.0068) is as large as
the mean (per-seed ICs swing from -0.0018 to +0.0148), so the sequence
representation does **not** reliably beat flat scalars. Every top-decile excess
return (best mean 2.42 bp) is below the 5.0 bp base round-trip cost.

## Reproduce

```bash
cd /home/ubuntu/trading-system
venv/bin/python research/atomics/sequence/build_dataset.py   # ~1 min
venv/bin/python research/atomics/sequence/benchmark.py       # ~2.5 min
```
