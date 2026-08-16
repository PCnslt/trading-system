# Index Regime-Gate Validation — SPY>SMA200 filter on RSI(2) buy-the-dip

**Date:** 2026-08-16 · **Task:** laptop build-task part (1) · **Verdict:** ⛔ **DROP the gate**

**Question:** does adding an index-level `SPY close > SPY SMA200` gate to the
Connors RSI(2) strategy kill the 2008 (PF 0.36) / 2022 (PF 0.81) bear-year bleed
WITHOUT gutting the walk-forward OOS (1.47)?

**Answer:** **No.** The gate leaves OOS PF basically unchanged (1.47 → 1.47) but
**does not remove bear-year decay** — it makes 2022 *worse* (0.81 → 0.21 at thr=5)
and only "fixes" 2008/2001/2002 by shrinking them to ~0–5 trades. It also cuts
cumulative OOS return ~21% (fewer trades). **Drop it.** Keep the per-name
`close > SMA200` filter (mandatory, already in spec) + satellite sizing + an
explicit bear-year warning flag on every signal.

---

## Method

- **Universe:** the same fixed 50-name S&P100 liquidity universe (split+dividend
  adjusted) as `STOCK_MR_VALIDATION.md` — 1962→2026 per-name history.
- **Strategy (both variants):** entry `RSI(2)<thr AND close>SMA200`, next-open
  fill; exit 2×ATR intraday GTC stop → 5-day time stop → revert (`close>SMA5` |
  `RSI2>70`).
  - **BASE** = per-name SMA200 filter only.
  - **GATED** = BASE **AND** `SPY close > SPY SMA200` at the signal bar.
- **The gate is baked into the engine's entry loop** (not post-filtered), so a
  gated-out trade correctly unblocks a later re-entry BASE never took.
- **Window:** 1993-02-01 → 2026-08 (SPY inception onward). SPY only exists from
  1993-01-29, so the gate is unevaluable before that; restricting BOTH variants to
  the same window keeps the comparison apples-to-apples. All bear years of interest
  (2001/2008/2018/2020/2022) are deep inside the window.
- **Reproduction check:** BASE walk-forward pooled OOS = **1.47 (n=1321)** — exactly
  the documented number, confirming the harness is faithful.

## Full-sample PF (1993+, 0bps / 5bps)

| thr | BASE 0bps | BASE 5bps | GATED 0bps | GATED 5bps |
|----:|----------:|----------:|-----------:|-----------:|
| 2   | 1.65      | 1.55      | 1.69       | 1.57       |
| 5   | 1.50      | 1.40      | 1.50       | 1.39       |

Gate is PF-neutral full-sample (slightly positive at thr=2, neutral at thr=5).

## Walk-forward pooled OOS (threshold-selected from train only)

| cost | BASE | GATED |
|------|------|-------|
| 0bps | PF **1.47** (n=1321), net +645% | PF **1.47** (n=1143), net +507% |
| 5bps | PF **1.36**, net +513%          | PF **1.35**, net +392%          |

**The gate does not gut the OOS PF** — but it removes ~13% of trades (1321→1143)
and ~21% of cumulative return. The PF held only because the removed trades were
PF-neutral on average; the surviving edge is not stronger.

## Per-year PF @0bps — the bear-year question (thr=5 spec threshold)

| year | BASE PF (n) | GATED PF (n) | Δ |
|------|-------------|--------------|---|
| 2001 | 0.94 (71)   | — (0)        | trades eliminated |
| 2008 | 0.86 (80)   | ∞ (5)        | trades eliminated (n→5) |
| 2018 | 0.83 (197)  | 0.83 (170)   | unchanged |
| 2020 | 0.81 (186)  | **0.74** (171) | worse |
| 2022 | 0.81 (110)  | **0.21** (39)  | **much worse** |
| 2025 | 0.84 (167)  | **0.70** (149) | worse |

(thr=2, reference): 2008 0.36→—(0); 2022 **0.81→0.46**; 2020 1.01→0.53; 2018
0.80→0.74; 2025 1.71→1.55. Same direction.

## Why the gate fails (mechanism, not noise)

`SPY > SMA200` is a **lagging** binary. A bear market's *first leg* happens while
SPY is still nominally above its 200-day MA (the MA hasn't rolled over yet) — those
early-breakdown dip-buys are exactly the falling knives that lose. By the time SPY
is *below* SMA200, the market is often bottoming, and the below-MA dip-buys include
the best mean-reversion trades of the cycle. The gate therefore **keeps the early
losers and filters out the recovery winners**, concentrating loss into the
breakdown phase — visible in 2022 going 0.81 → 0.21.

This is the third independent confirmation of the standing finding (see
`trading-backtest-validation` skill): **regime filters do not reduce maxDD / bear
decay.** A regime gate only helps if the kept-out regime is itself the drawdown
source; here the *timing within* the regime is what matters, and a lagging MA
filter cannot see it.

## Decision

| option | result |
|--------|--------|
| KEEP SPY>SMA200 gate | ✗ fails primary purpose (2022 worse), costs ~21% return |
| **DROP gate** | ✓ keep per-name SMA200 + satellite sizing + bear-year warning |

**Deploy spec (unchanged from plan §2–§5, minus the index gate):** per-name
`close > SMA200` mandatory; thr=5 (primary); fixed 2×ATR stop; 5d cap; revert exit;
1%/trade capped at 5% capital; $150/day loss cap; run as a **satellite**, and carry
an explicit **bear-year warning flag** on every signal (the edge is negative in
single bear years — 2008/2022/2018/2020/2025).

*Files:* `research/regime_gate_validate.py` (harness), `research/regime_gate_results.json`
(data), `research/stock_mr_engine.py` (added optional `gate=` param, backward-compatible).
