# INTRADAY GATE-1 VALIDATION — results & verdicts

**Date:** 2026-08-16 · **Operator:** VPS Hermes (builder) · **Paper-only, never-lose-money, no live.**

Companion to `research/INTRADAY_BUILD.md` (the sibling's canonical build-plan carrying the
owner's objective framing — **capital preservation, drawdown-first evaluation, intraday →
2–3-day swing, no asset priority**). This file is the **Gate-1 result**: the honest-fill,
cost-stressed backtest of the five intraday candidates, ranked under BOTH the PF-based bar
and the owner's new drawdown-first standard. Engine: `research/intraday_validate.py`;
full per-symbol cost grid: `research/intraday_validate_results.json`.

---

## 1. DATA — intraday bar depth (S3 `futures-bars/intraday/`, RTH only)

| Timeframe | Sessions | Range | Status |
|---|---|---|---|
| 5-min / 15-min / 1h | 117–251 | MES/ES/GC/CL/NG ≈ 1y (2025-08→); RTY/YM shallower (6–8mo) | **adequate for Gate-1** |
| 1-min | **30** | 2026-07-06 → 2026-08-14 | **thin (~6wk), growing** |

- **5-min (~1y) is the statistically meaningful dataset** used below.
- **1-min is too thin** for a 1m-timeframe edge. Deeper 1-min backfill
  (`ibkr_full_backfill.py` phase 4, "futures 1-min, 16 liquid" → **24 months ≈ ~2y**,
  month-partitioned; symbol list `['ES','NQ','MES','MNQ','RTY','YM','ZB','ZN','ZF','ZT','GC','SI','CL','NG','HG','6M']`
  includes all 9 liquid) is **queued** behind the equities-daily phase (running at report
  time). Do NOT start a competing collector (clientId 50 in use, t3.small memory-starved).
- **Tick recorder** (`futures-tick-recorder.service`, clientId 74): **running**, 23 CME/CBOT
  symbols at `marketDataType=1` (live L1), RTH-gated 09:30–16:00 ET. Restarted Sun 09:32 ET
  post-weekly-2FA; correctly reports RTH CLOSED on Sunday, resumes Monday's open. No ticks
  today = market closed, not a fault.

---

## 2. GO/NO-GO — PF-based bar (pooled, liquid universe, 3-tick + commission)

Pooled across MES MNQ ES NQ RTY YM GC CL NG, one position at a time, EOD flatten.
Cost curve = **slippage ticks/side + flat commission per round-trip**.

| Candidate | n | Win% | PF@0t | PF@1t | PF@2t | PF@3t | OOS PF | Sharpe | **PF verdict** |
|---|---|---|---|---|---|---|---|---|---|
| ORB (30-min range break) | 2319 | ~44% | 1.04 | 1.01 | 0.99 | 0.97 | 0.86 | −0.28 | NO-GO |
| MOM (10-bar ROC) | 12008 | ~39% | 0.95 | 0.90 | 0.85 | 0.80 | 0.78 | −3.17 | NO-GO |
| VWAP (2σ reversion) | 6093 | ~43% | 1.12 | 1.08 | 1.04 | 1.00 | 1.03 | +0.06 | HOLD |
| DONCH15 (15m Donchian/ATR) | 2086 | ~36% | 1.05 | 1.03 | 1.01 | 0.99 | 0.87 | −0.09 | NO-GO |
| FADESHORT (RSI2+Boll short) | 2691 | ~42% | 1.07 | 1.03 | 0.99 | 0.95 | **1.16** | −0.38 | NO-GO |

---

## 3. Drawdown-first ranking — the OWNER'S NEW standard

The owner retired the PF bar as the primary filter (see `INTRADAY_BUILD.md`). Ranking is now:
**maxDD → worst single-trade → consistency (win% + losing streak)**; PF/Sharpe/return secondary.

Pooled @ 3-tick + commission (ticks; smaller |maxDD| = better):

| Rank | Candidate | maxDD (t) | worst trade (t) | Win% | Losing streak | PF | Sharpe | Net (t) |
|---|---|---|---|---|---|---|---|---|
| 1 | **FADESHORT** | **−77,977** | **−941.5** | 41.1% | 15 | 0.95 | −0.38 | −6,895 |
| 2 | VWAP | −113,884 | −1,405.6 | 42.5% | 23 | 1.00 | +0.06 | +1,535 |
| 3 | ORB | −115,854 | −1,811.6 | 40.1% | 13 | 0.97 | −0.28 | −6,721 |
| 4 | DONCH15 | −131,439 | −3,654.5 | 36.0% | 16 | 0.99 | −0.09 | −2,598 |
| 5 | MOM | −171,122 | −3,750.6 | 35.8% | 28 | 0.80 | −3.17 | −93,933 |

**FADESHORT is the lowest-drawdown candidate** (smallest maxDD *and* smallest worst-trade by
a wide margin) — consistent with the owner's capital-preservation objective. But it is still
**net-negative** (PF 0.95), so it does not clear "don't lose money." **VWAP is the only
breakeven-to-positive candidate** (PF 1.00, highest win% 42.5%) but with a longer losing
streak (23).

> Note: pooled ticks mix contract sizes (CL/GC/NG $10/tick vs MES $1.25/tick), so these
> pooled drawdowns are indicative only; per-symbol $ is the honest read (below).

---

## 4. Realistic cost — the MES/MNQ micros nuance

3-tick/side is the *brutal* stress. MES/MNQ trade a 1-tick spread, so **1-tick/side is the
realistic slippage** for the execution instrument. At 1-tick + commission:

| Candidate | PF | Sharpe | Win% | Note |
|---|---|---|---|---|
| **VWAP** | **1.08** | **+1.04** | 44.6% | **marginal positive edge at realistic cost** |
| FADESHORT | 1.03 | +0.22 | 43.7% | breakeven+ |
| DONCH15 | 1.03 | +0.21 | 38.0% | breakeven+ |
| ORB | 1.01 | +0.11 | 42.2% | breakeven |
| MOM | 0.90 | −1.56 | 40.8% | dead even at 1-tick |

**VWAP is the only candidate with a positive edge at realistic micros cost** — but it is thin
and per-symbol-inconsistent (Nasdaq micros/minis positive; S&P and energy negative), so it is
**HOLD, not promote**.

---

## 5. Per-symbol headline (3-tick + commission) — pockets are isolated, not robust

| Sym | ORB PF (OOS) | MOM PF (OOS) | VWAP PF (OOS) | DONCH15 PF (OOS) | FADESHORT PF (OOS) |
|---|---|---|---|---|---|
| MES | 0.98 (0.87) | 0.68 (0.68) | 0.84 (0.86) | 0.77 (0.73) | 0.77 (0.93) |
| MNQ | 1.05 (0.81) | 0.92 (0.89) | **1.11 (1.13)** | **1.16 (1.02)** | 1.01 (1.28) |
| ES | 1.05 (0.83) | 0.75 (0.70) | 0.82 (0.91) | 0.86 (0.72) | 0.72 (1.02) |
| NQ | 1.00 (0.95) | 0.93 (0.86) | **1.16 (1.18)** | 1.14 (0.92) | 0.98 (1.35) |
| GC | 1.00 (1.04) | 0.83 (0.81) | 1.04 (0.82) | 0.87 (0.81) | **1.14 (1.16)** |
| CL | 0.57 (0.68) | 0.51 (0.63) | 0.75 (0.88) | 0.67 (0.80) | 0.61 (0.67) |
| NG | 0.56 (0.61) | 0.25 (0.21) | 0.44 (0.40) | 0.56 (0.51) | 0.46 (0.53) |

Nasdaq micros/minis (MNQ/NQ) and GC show positive *isolated* pockets; MES/ES and energy
(CL/NG) are consistently negative. **Energy is structurally un-tradeable at this cost level on
every candidate.** No candidate is positive across the full universe → per-symbol regime noise,
not an edge.

---

## 6. VERDICT — nothing promoted to paper execution

- **Promoted to paper execution: NONE.** No candidate clears either the PF bar *or* the
  owner's drawdown-first "don't lose money" bar at the binding cost.
- **VWAP = HOLD** — closest to promotable (PF 1.08 / Sharpe 1.04 at realistic 1-tick cost on
  micros; breakeven at 3-tick). Follow-up: param sweep (VWAP_K ∈ {1.5, 2, 2.5}, high-volume
  entry filter) + re-validation once the deeper 1-min archive lands.
- **FADESHORT = lowest-drawdown, still net-negative** — keep collecting signals (signal-only),
  do not paper-execute. Its OOS PF 1.16 is regime-dependent (recent window only), not robust.
- **ORB / MOM / DONCH15 = NO-GO.**

---

## 7. Execution change (signal-only)

`bot/live_intraday.py` (clientId 72) now defaults to **`EXECUTION_MODE=NONE`**: it still
fetches 5m/15m bars, archives them to S3, computes signals and writes `SIGNAL#` — but **places
no paper orders** on FADESHORT/DONCH15 (both NO-GO). Set `INTRA_EXECUTION=paper` to re-enable
paper fills for a later validated edge. This implements "validated edges only +
never-lose-money" and is fully reversible.

The fail-closed execution path (`TradeIntent → risk/admission → ExecutionManager stop-on-entry →
IBKR paper`, reconciled every 45s) is intact for when a survivor exists. Intraday risk config
already in place: $25k sleeve, **1% risk/trade**, max 5 contracts, 4 trades/day, −2% daily-loss
halt, 6-loss brake, 1 concurrent position, mandatory protective stop, EOD flatten 15:45 ET.

---

## 8. Volume profile / order flow — DEFERRED

Requires L2 size-at-price (separate paid feed; not on paper DUR193467). **VWAP (volume bars
already archived) is the interim execution-timing layer** — already backtested above (HOLD).
