# LANE 10 — Intraday VWAP (2σ reversion): definitive param sweep + volume filter

**Date:** 2026-08-18 · **Operator:** VPS Hermes (builder) · **Validation only — no live/exec.**
**Engine:** `research/lane10_vwap_sweep.py` (reuses `intraday_validate.py` loader/engine/cost).
**Full results:** `research/lane10_vwap_sweep_results.json` (mirrored to S3 `research/lane10_vwap_sweep_results.json`).

Follow-up to `INTRADAY_GATE1_VALIDATION.md` (VWAP HOLD: pooled 1.12 @0t / 1.08 @1t / 1.00 @3t,
OOS 1.03, "Nasdaq positive / S&P & energy negative"). This is the definitive sweep the
laptop directed: **VWAP_K ∈ {1.5, 2.0, 2.5} × high-volume entry filter**, per-symbol-group
consistency, GO bar = **OOS ≥ 1.1 @1-tick+comm AND consistent across ≥ 2 symbol groups**.

---

## 1. Method (unchanged from Gate-1)

- Data: S3 `futures-bars/intraday/{sym}/5min/`, RTH-only, ~1y (117–252 sessions/sym). 9 liquid
  symbols → 6 groups: **S&P** {MES,ES}, **Nasdaq** {MNQ,NQ}, **Dow** {YM}, **Russell** {RTY},
  **Metals** {GC}, **Energy** {CL,NG}.
- VWAP 2-sigma reversion: enter long when close crosses below VWAP − K·σ, short above
  VWAP + K·σ; exit on reversion to VWAP; 2×ATR hard stop; EOD flatten.
- **High-volume filter (the new axis):** enter only when `volume[i] ≥ HV_MULT × 20-bar rolling
  mean volume`. HV_MULT ∈ {0 (off), 1.0, 1.5, 2.0}. Rationale: only fade VWAP extremes that
  occur on genuine participation (a "real" extension, not a low-volume drift).
- Honest fills (entry @close + adverse slip; GTC stop gap-through-aware); cost = slip
  0/1/2/3 ticks/side + flat commission RT. Walk-forward 60/40 by session date.

## 2. Data-quality caveat (recorded)

Intraday **volume is only partially populated** in the archive (MES 37%, ES 42%, YM 45%,
GC 50%, RTY 53%, NQ 54%, MNQ 70%, CL 77%, NG 93%). The volume filter is therefore noisiest
on **MES/ES** (the primary execution instruments) and most meaningful on energy. This does
not invalidate the result but it bounds confidence on the MES/ES read specifically.

## 3. Result — the volume filter is the unlock, but only for equity-index futures

**Group pooled OOS PF @1-tick + commission, across all 12 combos:**

| Group | min | **median** | max | ≥1.1 in |
|---|---|---|---|---|
| Russell | 1.03 | **1.38** | 2.83 | 10/12 |
| Nasdaq | 0.97 | **1.17** | 1.26 | 8/12 |
| Dow | 0.95 | **1.13** | 1.67 | 8/12 |
| S&P | 0.93 | **1.11** | 1.49 | 6/12 |
| **Energy** | 0.89 | **0.97** | 1.12 | 1/12 |
| **Metals** | 0.88 | **0.94** | 1.21 | 1/12 |

**Per-symbol median OOS PF @1t (all combos):** NQ **1.26** (≥1.1 in 12/12) · RTY **1.38**
(10/12) · ES 1.13 (6/12) · YM 1.13 (8/12) · MNQ 1.07 (6/12) · MES 1.05 (4/12) ·
CL 1.05 (3/12) · GC 0.94 (1/12) · **NG 0.75 (0/12)**.

The volume filter turns the equity-index sleeve from "only Nasdaq positive" (original Gate-1)
into **consistently positive across all four index groups**. The mechanism is coherent:
high-volume VWAP extensions on liquid index futures mean-revert; on energy they do not.

## 4. Why this is NOT a clean GO (the correlation + generality problem)

The GO bar is "consistent across ≥ 2 symbol groups". **Four** groups clear it — but the four
that clear are **S&P, Nasdaq, Dow, Russell: four US-equity-index futures with ~0.85–0.95
pairwise correlation.** They are **one bet**, not four independent edges (the
`trading-backtest-validation` "redundancy, not a new edge" pitfall). The two *genuinely
different* asset classes in the sweep — **Metals (0.94) and Energy (0.97) — fail every time**
(NG is 0.71–0.81 in all 12 combos). A universal VWAP-reversion edge does **not** exist; only
an equity-index-futures pocket does.

Secondary honesty flags: (a) OOS is ~4.8 months and per-symbol OOS still unstable across
adjacent params (MNQ 0.67→1.19, MES 0.91→1.33); (b) the filter halves trade count (6,127→
2,991 full / 2,403→1,004 OOS), concentrating the "edge" on fewer, higher-volume bars; (c)
volume is only 37% populated on MES.

## 5. VERDICT — NO-GO-WITH-REASON (cross-asset), strong sleeve candidate

- **NO-GO** for "intraday VWAP 2-sigma reversion" as a cross-asset strategy: the edge does
  not generalize to metals/energy (the only independent asset classes in the sweep), so it
  does not clear "consistent across ≥ 2 symbol groups" once correlation is priced in.
- **Sub-finding (material):** with the high-volume filter, the **equity-index sleeve
  (MES/MNQ/ES/NQ/RTY/YM)** is consistently positive OOS @1t (group medians 1.11–1.38, stable
  across VWAP_K ∈ {1.5, 2.0, 2.5}). This is a real, repeatable improvement over Gate-1 and is
  the lane's actual asset class ("Index futures (MES/MNQ)"). It is a **strong re-validation
  candidate**, not a dead end.

### Re-activation trigger (explicit)

Re-open Lane 10 as a **scoped equity-index sleeve** when **all** of:
1. The deeper **1-min archive** (24-month backfill, queued behind equities-daily) is in place,
   and the sleeve re-validates with **OOS ≥ 1.1 @1t stable across VWAP_K ∈ {1.5–2.5}** on
   **1-min bars** (not just 5-min).
2. **Cross-source confirmation**: the sleeve is positive on a second independent data source
   (IBKR `futures-bars` vs yf 1-min), agreeing on direction.
3. **Paper-forward the MES/MNQ sleeve only** (signal-only first), never the cross-asset
   universe. Metals/energy stay excluded permanently unless independently re-proven.

Until (1)–(2) land, the lane stays **RESEARCHING → NO-GO-WITH-REASON (sleeve-scoped)** and no
paper/exec activation of any kind.
