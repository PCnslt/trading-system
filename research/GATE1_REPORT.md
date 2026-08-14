# GATE-1 VALIDATION REPORT — promote/kill decision + new-strategy screen

Source: yfinance daily (2010–2026, auto_adjust). Re-run on IBKR S3 bars once the
backfill completes (`research/validate_edges.py --source s3`).
Cost model: fee 1.3 bps round-trip of notional + slippage 0/1/2/3 ticks PER SIDE
(round-trip = 2× the stress level). 0-slippage is the ideal reference.
Fill model: entry at signal close + adverse slippage; Donchian GTC stop modelled
INTRADAY (gap-aware: open<stop → fill at open); close-based exits at close.
No double-fill (one entry/exit per bar). Slippage per side is conservative.

## EDGE 1 — index-LONG (Donchian + RSI2 buy-dip)  →  **PROMOTE**

| sleeve | instr | trades | win% | full PF | OOS PF* | maxDD $ | net $ | PF @1t/2t/3t slip |
|---|---|---|---|---|---|---|---|---|
| DONCHIAN | ES=F | 224 | 62 | 1.56 | 1.52 | -20.9k | +83.3k | 1.51 / 1.47 / 1.43 |
| RSI2LONG | ES=F | 199 | 72 | 1.99 | 2.57 | -42.3k | +165.9k | 1.95 / 1.91 / 1.88 |

\* OOS = last 40% of data (true out-of-sample). Both sleeves cost-robust to 3 ticks.

- Walk-forward folds (period stability): DONCHIAN 1.00 / 1.85 / 1.58 · RSI2LONG
  2.41 / **0.87** / 3.26 — RSI2LONG is weak in the middle fold (~2016–2021) and
  its 40/20/40 validate fold is 0.76. Robust overall, but period-dependent.
- **Fill-model finding**: DONCHIAN intraday-GTC stop PF 1.51 vs close-based 1.86.
  The earlier close-to-close scans OVERSTATED the stop edge by ~0.35 PF. Honest
  intraday fills still clear the promote bar (>1.2).
- Regime: DONCHIAN earns in trend (2.45) + high-vol (2.59), ~flat in range/low-vol
  (1.26 / 1.01). RSI2LONG ~regime-neutral (1.98/1.99).
- Correlation: DONCHIAN vs RSI2LONG = 0.002 → two independent bets.

## EDGE 2 — bonds fade-SHORT (RSI2 + Bollinger)  →  **KILL**

| sleeve | instr | trades | win% | full PF | OOS PF | maxDD $ | net $ | PF @1t/2t/3t slip |
|---|---|---|---|---|---|---|---|---|
| RSI2SHORT | ZN=F | 238 | 66 | 1.05 | 1.31 | -36.4k | +6.7k | 0.94 / 0.85 / 0.76 |
| BBANDSHORT | ZN=F | 94 | 61 | 0.99 | 1.01 | -30.3k | -0.8k | 0.92 / 0.86 / 0.80 |

- The edge is structurally thin: avg trade ≈ **$28** (RSI2SHORT) on a $1000/point
  contract. One tick of slippage = $15.6, so 1–2 ticks wipe it. BBANDSHORT is
  already ≈breakeven at 0 slippage.
- The prior "robust FADE-RALLY SHORT (RSI2 OOS 1.5)" label was measured at 0
  slippage + a bps fee; it does NOT survive realistic fill costs.
- RSI2SHORT vs BBANDSHORT correlation 0.646 → the same bet, not independent.
- **KILL both sleeves.** The index-LONG edge is the real money-maker; bonds-short
  is not worth the gateway/slippage risk. Cross-edge corr (index-LONG vs
  bonds-SHORT) = 0.085 — they were already near-uncorrelated, so killing bonds
  loses little diversification.

## TASK 2 — new-strategy screen (5 candidates, first pass)

| candidate | full PF | OOS PF | PF @2t slip | verdict |
|---|---|---|---|---|
| GAP_FADE | 1.08 | 0.94 | 1.03 | reject (OOS<1) |
| NR7_BREAKOUT | 0.72 | 0.69 | 0.69 | reject |
| DONCHIAN_SHORT | 0.54 | 0.63 | 0.53 | reject — justifies the long-only bias |
| OVERNIGHT_LONG | 0.77 | 0.88 | 0.49 | reject — 252 trades/yr, 1.3bp fee dominates |
| BBAND_INDEX_LONG | 1.74 | 1.71 | 1.69 | **survivor** but REDUNDANT |

- BBAND_INDEX_LONG (buy close < lower Bollinger) is 0.69 correlated with the
  existing RSI2LONG buy-dip (73% signal overlap) → same bet, not a new edge.
- **Net: no genuinely new, non-redundant edge survives first-pass cost stress.**
  Direction for round 2: the index buy-the-dip family is the only live vein.

## TASK 3 — continuous daily collection (scheduled)

- **L1 tick recorder** — already deployed by the data-maximization task
  (`bot/tick_recorder.py`, systemd `futures-tick-recorder.service`, clientId 74).
  Live (marketDataType=1), RTH-gated 13:30–20:00 UTC Mon–Fri, S3
  `futures-ticks/<sym>/<date>/<ts>.jsonl` + DynamoDB `QUOTE#<sym>`, auto-reconnect.
  Running; first session data Monday 13:30 UTC.
- **Daily bars collector** — NEW `data/daily_collect.py` (clientId 75), system
  crontab **23:20 UTC daily**. Fetches daily + 15m + 5m bars for all 12 symbols
  → S3 `futures-bars/` (idempotent date-keyed overwrites; self-heals missed days).
  Verified end-to-end (fetched + wrote ES daily 2026-08-10..14).

## Order-fulfillment observations

1. **Stop fills must be intraday + gap-aware.** Close-based stop modelling (the
   old scans) overstated DONCHIAN PF 1.86 vs 1.51 honest. This is the exact
   "fills not modelled correctly" defect — now fixed in the validator.
2. **Found + fixed a shadowing bug in the first pass** (RSI2 threshold compared
   against the bar HIGH instead of 90 → 0 trades on bonds; also silently
   disabled RSI2LONG's signal exit). This is the "order condition evaluated
   against the wrong value" class of defect — the validator now cross-checks
   trade counts against indicator hit-counts.
3. Single entry/exit per bar enforced (no exit-race double-fill in backtest).
4. Execution-layer hardening (fill-verify + reconciliation) remains top roadmap
   priority: the index edge has enough margin to absorb realistic fills; the
   bonds edge does not.
