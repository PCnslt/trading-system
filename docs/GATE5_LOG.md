# Gate 5 — Paper-Forward Validation Log

> **index-LONG** (`live.py`: MES/MNQ Donchian + RSI2 buy-dip) → the sole live-capital candidate.
> Gate on **execution-correctness per fired signal/cycle**, NOT signal count (index edge is low-frequency, ~12 signals/yr).

## Criteria — ALL must hold over 10 RTH sessions

| # | Criterion | Measure |
|---|---|---|
| (a) | Every fired signal → correct `TradeIntent` → verified fill → reconcile `MATCH` end-to-end | 0 failures across window |
| (b) | Zero fill-verification failures | 0 (no `UNKNOWN`/`REJECTED`/`PARTIAL` attributed to our flow) |
| (c) | Zero **unexplained** HALTs | any HALT must trace to a documented cause (risk-cap trip, reconcile non-MATCH, gateway down) |
| (d) | Risk ledger persists correctly across restarts | `RISK#<date>/<scope>` load-on-start restores daily_pnl/trades/consec-loss/halt — no reset-to-zero |

## Window

- **Declared:** 2026-08-14 (gate STARTED)
- **Target:** 10 RTH sessions (Mon–Fri, 13:30–20:00 UTC)
- **First counted session:** Mon 2026-08-17
- **Sessions completed:** 0 / 10
- **Counter resets to 0** on any (a)–(d) failure → root-cause, fix, restart window.

## Why 10 sessions (tuning justification)

- Index edge fires ~12 signals/yr (≈1/month). 10 RTH sessions ≈ 2 weeks will likely fire 0–1 index signals → the gate **cannot** be signal-count based.
- The intraday MES lane (`live_intraday.py`) fires every 15 min during RTH (~25 cycles/session → ~250 cycles/10 sessions), supplying the execution-volume validation the sparse index edge can't.
- Therefore the gate is: **zero execution defects** across every fired signal + intraday cycle in the window.

## Per-session log

| # | Date (RTH) | Index signal fired? | Intent→fill→MATCH | Fill-verify fails | HALTs (explained?) | Ledger persisted | Verdict |
|---|---|---|---|---|---|---|---|
| — | _(none yet)_ | — | — | — | — | — | — |

## Decision

- **PASS** → proceed to Gate 6 (shadow mode: real signals, no submission) → Gate 7 (micro-live).
- **FAIL** → record root cause, fix, reset counter.
