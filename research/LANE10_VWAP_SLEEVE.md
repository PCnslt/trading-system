# LANE 10 — VWAP equity-index intraday sleeve: RE-ACTIVATION (scoped)

**Date:** 2026-08-18 · **Operator:** VPS Hermes (builder) · **Directive:** laptop owner
**Status:** Lane 10 re-opened as a **scoped equity-index sleeve** and promoted to
**paper-forward (real fills)** on MES/MNQ. This is the execution of the re-activation
trigger recorded in `research/LANE10_VWAP_SWEEP.md` (see "Re-activation trigger").

---

## 1. What changed (why this is NOT a reversal of the cross-asset NO-GO)

`LANE10_VWAP_SWEEP.md` concluded **NO-GO cross-asset**: the VWAP 2-sigma reversion edge
does not generalize to metals (0.94) / energy (0.97). That verdict **stands** — metals and
energy remain **permanently excluded**.

The material sub-finding was that the **equity-index sleeve** (S&P/Nasdaq/Dow/Russell
group: MES/MNQ/ES/NQ/RTY/YM) is consistently positive OOS @1t with the high-volume filter
(group medians 1.11–1.38, stable across VWAP_K ∈ {1.5–2.5}). The laptop directive is to
stand up **only that sleeve** — a correlated single-bet pocket, not a universal edge.

## 2. Signal (exact port of the sweep)

- Session-cumulative VWAP on RTH 5-min bars; `z = (close − VWAP) / σ(close−VWAP)`.
- Enter LONG when `z < −VWAP_K`, SHORT when `z > +VWAP_K`; `VWAP_K = 2.0`.
- **High-volume filter:** enter only when `volume ≥ HV_MULT × 20-bar rolling mean`
  (`HV_MULT = 1.0` default) — fade only genuine high-participation extensions.
- Exit on reversion to VWAP; **2×ATR hard protective stop** (never-lose-money); EOD flatten.

Implementation: `bot/live_vwap.py` (clientId 79). Tests: `tests/test_live_vwap.py`.

## 3. Paper-forward config (real fills)

- **Instruments:** MES + MNQ (micro index contracts; % action == ES/NQ), front-month.
- **Execution:** IBKR paper `:4002`, `VWAP_EXECUTION=PAPER` (real paper fills via the
  hardened `ExecutionManager` — native-bracket protective stop at fill, idempotent
  `TradeIntent`, `INTENT#` conditional writes). Signal-only = `VWAP_EXECUTION=NONE`.
- **Risk:** $25k intraday sleeve, 1% risk/trade, ≤2 concurrent positions (MES+MNQ).
  Sizing via `risk.position_size` (stop distance × point value). MES/MNQ fill at 1%
  on 5-min 2×ATR stops (stop risk ~$20–80/contract vs $250 budget).
- **Round-trip journal:** `SIGNAL#`/`TRADE#`/`POSITION#` keyed `<sym>_VWAP`.
- **Cross-bot stand-down:** refuses entry on a symbol held by the daily bot (`live.py`)
  or the intraday bot (`live_intraday`) — never nets the same contract.
- **Safety:** `MES_VWAP`/`MNQ_VWAP` registered in `hardening/reconciler.py::TRACKED_TAGS`
  (bidirectional, side stored in the POSITION row) so the reconciler verifies a protective
  stop exists on every open position.
- Schedule: Hermes cron every 15 min during RTH (to be wired — not yet in jobs.json).

## 4. 1-min archive status (honest)

- **1-min collection resumed** via `bot/backfill_bars.py --1m-only` (new flag). The six
  index symbols' 1m archives are refreshed to the latest ~30 sessions.
- **The "24-month 1-min backfill" target in the re-activation trigger is NOT achievable
  from any current source.** Measured entitlement caps: IBKR paper 1m ≈ **30 days**;
  yfinance 1m ≈ 7 days. There is no 24-month 1-min futures source on this account. The
  deeper-archive re-validation condition (1) of the trigger therefore **cannot be met on
  1-min bars** — it is a data-entitlement gap, not a code gap. (See
  `docs/PROJECT-STATE.md` "Gaps".)
- What *is* achievable and in place: the **5-min archive (~1y, 118–179 sessions/sym)** on
  which the sleeve already validated OOS 1.11–1.38 @1t, plus a rolling ~30d 1-min archive
  for microstructure work (Phase 2/3 of the order-flow lane).

## 5. Honest status — "tradeable now vs needs-more-data"

| Item | Status |
|---|---|
| VWAP sleeve signal (equity-index only) | ✅ implemented, tested, paper-forward armed |
| VWAP sleeve paper fills | ⏳ collects from next RTH session (market was Globex/overnight at build time) |
| Cross-source 1-min confirmation (trigger cond. 2) | ❌ not possible (no 2nd 1-min source) |
| 24-month 1-min re-validation (trigger cond. 1) | ❌ blocked on entitlement (30d cap) |
| Metals/energy VWAP | 🚫 permanently excluded (cross-asset NO-GO) |

The sleeve is paper-forwarding on the **validated 5-min timeframe** with real fills; the
1-min re-validation condition is recorded as un-met for an entitlement reason (not a code
reason) and the owner is the arbiter of whether to fund a deeper 1-min feed.

## 6. Files

- `bot/live_vwap.py` — VWAP sleeve forward-test bot (exec=PAPER).
- `tests/test_live_vwap.py` — signal/stop/roll tests.
- `hardening/reconciler.py` — `MES_VWAP`/`MNQ_VWAP` registered.
- `bot/backfill_bars.py` — `--1m-only` flag.
