# ORDER-FLOW / MICROSTRUCTURE LANE — status

**Date:** 2026-08-18 · **Operator:** VPS Hermes (builder) · **Directive:** laptop owner
**Phase:** 1–4 built, serialized (git + S3 + DynamoDB), 239 tests green.
**Reference framework:** `trading/orderflow-auction-strategy` (Creamer) — 4-step:
structure → location → confirmation → execution.

This lane is the **microstructure research + order-flow signal** track, built in
parallel with the VWAP equity-index sleeve (Lane 10 re-activation). Everything
here is **signal-only (exec=NONE)**; the VWAP sleeve is the only paper-EXEC lane.

---

## 1. What is collecting (Phase 2)

| Source | Instrument | Depth | Where |
|---|---|---|---|
| IBKR paper (`reqMktData`) | MES, MNQ | **L1 top-of-book only** — L2 `reqMktDepth` is **NOT entitled** (Error 354 "not subscribed"; separate paid package) | `orderbook/<sym>/<date>.jsonl` + `ORDERBOOK#<sym>` (hot, TTL'd) |
| Robinhood MCP (`get_equity_price_book`) | 15 small-ticket names (F AAL T KHC PFE WBD KVUE DOW SNAP NIO INTC SOFI PARA HPE CCL) | **L2 price book** (asks/bids level arrays, best-first) + L1 quotes | same stores |
| IBKR futures ticks (`tick_recorder`, extended) | 23 CME/CBOT L1-live symbols | bid/ask/last/size, now **`kind`-tagged** (`trade`/`quote`) | `futures-ticks/` + `QUOTE#<sym>` |

Collector: `bot/orderbook_collector.py` (clientId 80, READ-ONLY). RTH-gated
09:30–16:00 ET. `bot/tick_recorder.py` gained the `kind` field (trade vs quote)
for the Phase-3 delta/absorption distinction. Both persist to S3
(`trading-datalake-920641308584`) + DynamoDB (`trading-data`, pk-prefixed
namespaces `ORDERBOOK#`/`MICRO#`/`AUCTION#` — the repo's one-table convention).

**1-min bar archive (Phase 1 prerequisite):** refreshed for all 6 index symbols
via `bot/backfill_bars.py --1m-only` (new flag) — 30 sessions each. **The
"24-month 1-min backfill" target is NOT achievable from any current source**
(IBKR paper 1m ≈ 30d cap; yfinance 1m ≈ 7d). Recorded as an entitlement gap.

## 2. What is computed (Phase 3)

`data/microstructure.py` (pure, unit-tested) + `bot/microstructure_engine.py`
(batch runner, parallel tick load, persists `MICRO#<sym>`):

- **bid-ask delta** — buyer- minus seller-initiated volume/bar (trade classified
  vs prevailing bid/ask).
- **absorption** — aggressive order at the extreme wick with NO price reward
  (sell-absorption = sellers trapped at the low; buy-absorption = buyers trapped
  at the high).
- **volume profile / value area** — session POC / VAH / VAL (70% value area).
- **orderbook imbalance** — (bid − ask depth) / (bid + ask) over top-N levels.
- **spread + capture cost** — inside spread and its round-trip cost in ticks.

Verified on real data: MES 2026-08-17 → 78 bars, 58,731 ticks, POC 7794 / VAH
7809 / VAL 7778; MNQ → 78 bars, 185,825 ticks, POC 30104 / VAH 30218 / VAL 30067.
`book_imbalance` is `None` until the orderbook collector accrues RTH snapshots
(armed, no data yet).

## 3. Creamer auction signal generator (Phase 4, exec=NONE)

`data/auction.py` (pure 4-step framework, 15 tests) + `bot/auction_signals.py`
(signal-only runner, logs `AUCTION#MNQ`):

1. **Environment** — 1h market structure (HH/HL = value up, LH/LL = value down,
   else sideways) over a **multi-day 1h window** (single-session 1h is too thin
   to establish structure — fixed).
2. **Location** — fib golden pocket 0.705/0.788/0.886 from the swing, **outside**
   the session value area, price retraced into the pocket.
3. **Confirmation** — absorption + shift of dominance + bid/ask imbalance
   (imbalance `None` → "pending", does not veto).
4. **Execution** — stop below failed sellers / below 0.886; targets at POC and
   the swing.

Instrument MNQ 5-min, first 90 min of NY open, participation floor 20k
contracts/5-min candle (reachable — MNQ prints ≥20k in ~26% of bars).

**Honest signal count:** **0 candidate setups over the last 8 sessions.** This is
not a crash — every gate is unit-tested and the runner evaluates them correctly.
The conjunction "golden pocket OUTSIDE value area AND price retraced INTO it,
with absorption + dominance shift on the same bar" is genuinely rare with the
current *latest-1h-swing* pocket definition. Likely needs swing-selection tuning
(major swing vs latest minor swing) + orderbook data before it fires
meaningfully — **needs-more-data, not tradeable now.**

## 4. VWAP sleeve paper-forward status (Lane 10)

See `research/LANE10_VWAP_SLEEVE.md`. `bot/live_vwap.py` (clientId 79,
`VWAP_EXECUTION=PAPER`) is **armed with real paper fills** on MES/MNQ
(volume-filtered VWAP 2σ, 2×ATR native-bracket stop, round-trip journal,
cross-bot stand-down, `MES_VWAP`/`MNQ_VWAP` in `TRACKED_TAGS`).

**Fills: 0 (armed, first RTH session pending).** Built at ~00:10 ET Tue; the
next RTH session is the first live-forward window. Note IBKR maintenance
09:00–10:00 ET today may delay the first fills.

## 5. Honest "tradeable now vs needs-more-data" split

| Component | Verdict |
|---|---|
| VWAP sleeve (MES/MNQ, 5-min) | ✅ **paper-forward armed** (validated 5-min edge, real fills from next RTH) |
| VWAP 1-min re-validation (trigger cond. 1) | ❌ blocked on entitlement (30d cap, no 24mo source) |
| Order-flow data collection | ✅ live (armed; accrues from next RTH) |
| Microstructure features | ✅ computed + persisted (delta/absorption/value-area real) |
| Creamer auction signals | ⏳ **needs-more-data** — 0 setups/8 sessions; swing-selection tuning + book data next |

## 6. Files (all committed, authored PCnslt <info@pcnslt.com>)

- `bot/live_vwap.py`, `tests/test_live_vwap.py` — VWAP sleeve (Phase 1).
- `bot/backfill_bars.py` (`--1m-only`), `research/LANE10_VWAP_SLEEVE.md`.
- `bot/orderbook_collector.py`, `tests/test_orderbook_collector.py` (Phase 2).
- `bot/tick_recorder.py` (`kind` field), `tests/test_tick_recorder.py`.
- `data/microstructure.py`, `bot/microstructure_engine.py`,
  `tests/test_microstructure.py` (Phase 3).
- `data/auction.py`, `bot/auction_signals.py`, `tests/test_auction.py` (Phase 4).
- `hardening/reconciler.py` — `MES_VWAP`/`MNQ_VWAP` registered.
