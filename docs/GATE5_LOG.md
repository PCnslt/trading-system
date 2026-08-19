# Gate 5 — Paper-Forward Validation Log

> **index-LONG** (`live.py`: MES/MNQ Donchian + RSI2 buy-dip) → the sole live-capital candidate.
> Gate on **execution-correctness per fired signal/cycle**, NOT signal count (index edge is low-frequency, ~12 signals/yr).

> **⚠ Stop-adjusted strategy under validation.** The live bots rest a **2×ATR hard
> protective stop** on every entry (Never-Lose-Money rule 1): the index Donchian
> already carried a 2×ATR GTC stop; the RSI2 buy-dip and intraday FADESHORT
> previously rested **NO stop** in the original backtest and now rest their 2×ATR
> distance as a real protective order. Gate 5 therefore validates the
> **stop-adjusted** version — a deliberate behavior change vs the no-stop
> backtest. Backtest-vs-live differences attributable to the stop are EXPECTED
> and are not, by themselves, execution defects.

## Criteria — ALL must hold over 10 RTH sessions

| # | Criterion | Measure |
|---|---|---|
| (a) | Every fired signal → correct `TradeIntent` → verified fill → reconcile `MATCH` end-to-end | 0 failures across window |
| (b) | Zero fill-verification failures | 0 (no `UNKNOWN`/`REJECTED`/`PARTIAL` attributed to our flow) |
| (c) | Zero **unexplained** HALTs | any HALT must trace to a documented cause (risk-cap trip, reconcile non-MATCH, gateway down) |
| (d) | Risk ledger persists correctly across restarts | `RISK#<date>/<scope>` load-on-start restores daily_pnl/trades/consec-loss/halt — no reset-to-zero |

## Window

- **Declared:** 2026-08-14 (gate STARTED)
- **Target:** 10 RTH sessions (Mon–Fri, 09:30–16:00 ET)
- **First counted session:** Mon 2026-08-17
- **Sessions completed:** 1 valid / 10 (1 voided: 2026-08-18 — see per-session log)
- **Counter resets to 0** on any (a)–(d) failure → root-cause, fix, restart window.

## Why 10 sessions (tuning justification)

- Index edge fires ~12 signals/yr (≈1/month). 10 RTH sessions ≈ 2 weeks will likely fire 0–1 index signals → the gate **cannot** be signal-count based.
- The intraday MES lane (`live_intraday.py`) fires every 15 min during RTH (~25 cycles/session → ~250 cycles/10 sessions), supplying the execution-volume validation the sparse index edge can't.
- Therefore the gate is: **zero execution defects** across every fired signal + intraday cycle in the window.

## Per-session log

| # | Date (RTH) | Index signal fired? | Intent→fill→MATCH | Fill-verify fails | HALTs (explained?) | Ledger persisted | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | 2026-08-17 (Mon) | No — MES/MNQ Donchian+RSI2 all `NONE` (flat) | n/a (no signal) | 0 | 1 (explained) — intraday `unaccounted fills: MES` from the ~13:37 manual flatten of an orphaned long (documented 16:27 report; reconciler scan-pagination fix `65430ee` already resolved it; RECONCILE=MATCH streak 0) | Yes (RISK#live/live_gc persisted, halted=false) | **Session 1 — no index signal; 0 new execution defects.** Sizing audit (this session) found the $50k sleeve would return size=0 on a signal → raised to $350k paper sleeve BEFORE any signal fired (see REPORT). |
| 2 | 2026-08-18 (Tue) | **VOID — EOD eval skipped** | n/a | n/a | n/a | n/a | **Voided (data-integrity defect, NOT an execution defect).** The 02:02 ET off-hours deploy (pre-fix code) ran the daily bot on a *partial Globex bar* (close ~7737, RSI2 13.4 → "no signal"), stamped `RUN#live`, then the 19:00 ET EOD run was dedupe-skipped. **Reconstruction of the finalized 08-18 close shows an RSI(2)<10 buy-the-dip LONG on BOTH MES and MNQ (ES close 7714.0 RSI2 9.8 > SMA200; NQ 29586.0 RSI2 9.8) that was therefore MISSED** — a lost forward-test entry. Root cause fixed by `5277bc7` (`data_finalized()` guard + off-hours catch-up window + mark-ran-after-eval). Not backfilled (would falsify the forward-test record). |

## Reconstruction note (08-18 missed signal)

Deterministic replay of `live.py` `compute()` on yfinance `ES=F`/`NQ=F` daily as of the
**finalized** 2026-08-18 close:

| Sym | close | don_hi | rsi2 | sma200 | Donchian | RSI2 |
|---|---|---|---|---|---|---|
| MES (ES=F) | 7714.0 | 7838.5 | **9.8** | 7110.3 | no (close ≤ 20d-high) | **LONG** (RSI2<10 & close>SMA200) |
| MNQ (NQ=F) | 29586.0 | 30343.0 | **9.8** | 26892.7 | no | **LONG** |

The 02:02 ET off-hours run had read a partial bar (close 7737.5 / RSI2 13.4) → classified
flat; the proper 19:00 ET run never happened. Net: **1 RSI2 LONG entry (2 contracts, MES+MNQ)
lost to the operational bug.** The fix (`5277bc7`) makes off-hours daily-bot runs a no-op, so
this class cannot recur.

## Decision

- **PASS** → proceed to Gate 6 (shadow mode: real signals, no submission) → Gate 7 (micro-live).
- **FAIL** → record root cause, fix, reset counter.
