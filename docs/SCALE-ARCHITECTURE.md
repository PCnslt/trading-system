# Scale Architecture — Broadening the Equity Universe

**Date:** 2026-08-24 · **Status:** design + phase-1/2 implementation

## Current state (as-built)

- **Universe:** `STOCKS` (190 liquid) + `SMALL_CAP_STOCKS` (154 sub-$35, LIVE whole-share) + `ETFS` → ~344 names total.
- **Data fetch** (`bot/live_equities.py::fetch`): **sequential** `yf.download(sym)` per symbol, 0.15s pacing → {sym: df}.
- **Signals:** vectorized per-name (Wilder RSI(2), SMA200/SMA5, ATR14). Cheap.
- **Writes** (`put_item`): **one `put_item` per signal/position** — unbatched.
- **Positions:** capped (RH `RH_MAX_POSITIONS=5`); breadth lives in the *universe*, not open positions.
- **Scheduler:** `bot_loop.py --daily 19:20` (RTH close) → `live_equities.py`.

## Bottlenecks (measured / inferred)

| # | Bottleneck | At 190 names | At 1,500 names | Fix |
|---|---|---|---|---|
| 1 | Sequential yfinance fetch | ~3–6 min | **~40 min** (misses the 19:20 window) | batch `yf.download(list)` in one call, or S3 lake + latest-bar only |
| 2 | Unbatched DynamoDB writes | 1 call/signal | 1,500 calls (slow + $$$ on-demand) | `batch_writer()` (25 items/call → 60 calls) |
| 3 | RAM: `fetch` holds all `{sym: df}` + all signals in memory | ~100 MB | **>1 GB** (t3.small = 2 GB, already 65% + 47% swap) | chunked process→write→release |

## Target architecture

1. **Batch fetch** — one `yf.download(" ".join(syms), group_by='ticker', auto_adjust=True)` → restructure to `{sym: df}`. 1,500 names = 1 network round-trip.
2. **Batch writes** — accumulate signal/position rows in a list → flush via `table.batch_writer()` (or `client.batch_write_item`, 25/req).
3. **Chunked pipeline** — process N symbols (e.g. 200), write, release, next chunk. Bounds peak RAM regardless of universe size.
4. **Optional history-source swap** — the S3 lake already holds `ibkr/equities/daily/*.parquet` (6,548 symbols, ~20y). Use it for history + fetch only the latest bar (yfinance/RH quote). Removes the 20y re-download entirely.

## Phased plan (safe — never break the live lane)

- **Phase 1 — batch writes** (low risk, immediate): swap `put_item` loop for a `batch_writer`. No behaviour change, 25× fewer API calls.
- **Phase 2 — batch fetch** (moderate, tested): `fetch_batch()` alongside `fetch()`, gated by a flag; verify identical bars vs sequential on the 190-name universe before flipping default.
- **Phase 3 — universe expansion** (190 → 500 → 1,500), each step: `--dry-run --force` smoke + `pytest` + a timed real run. Gate on fetch time staying inside the 19:20→entry window.
- **Phase 4 — S3-lake history** (optional): eliminate the daily re-download; backfill latest bar only.

## DB / infra readiness

- **DynamoDB** `trading-data`: on-demand (`PAY_PER_REQUEST`), 9.7k items / 2.7 MB, **0 throttle events / 24h**. No capacity work needed at any realistic universe size.
- **S3** lake: all 9 prefixes healthy; 6,548 symbols of daily history already archived.
- **VPS** (t3.small): disk 51%, load 0.25, **RAM 65% + 953 MB swap** ← the binding constraint. Chunked pipeline (Phase 3) keeps RAM flat; a **t3.medium (4 GB)** is the simple fix if 1,500 names is the target.
- **Safety invariants (must hold across every phase):** `--dry-run` never orders; `--force` requires `--dry-run`; earnings guard intact; position cap intact; reconciler still reconciles; kill-switch `CONTROL` read before any entry.

## Non-goals

- Not adding new signal sources (alt-data/VIX-term-structure/reversal variants all NO-GO — lanes 36–44). This is pure *execution scale* on the validated RSI2/REV2 edge.
