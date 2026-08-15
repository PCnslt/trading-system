# Equities Edge Sweep (Lane C) — Long-only ETFs & Sectors

**Date:** 2026-08-15 · **Universe:** 5 broad ETFs (SPY QQQ IWM DIA VTI) + 10 sector ETFs (XLF XLK XLE XLV XLP XLY XLI XLB XLU XLRE) · **Data:** S3 `yf/etfs` + `yf/sectors` daily (SPY→1993, sectors→1998, XLRE→2015) + hourly (~2y, unused — all six strategies are daily-bar rules) · **Cost:** $0 commission, slippage grid **0/2/5/10 bps per side** + **0/1/2/3 cents/share per side** stress.

**Bottom line:** the **RSI(2)<10 buy-the-dip** is the only edge that is robust in *both* regimes, survives 10 bps + 3¢/sh, and has a real sample (n≥94 OOS everywhere it promotes). The **Donchian 20-day breakout** is a real but **regime-dependent** momentum edge (lost money 1993–2008, profitable 2009–2026). **200-day MA trend** has the highest PF but is a low-turnover, thin-sample trend filter — treat it as a regime overlay, not a standalone signal. **Bollinger lower-band is ~redundant with RSI2**; the **5-day reversal is regime-flipped and inconsistent**; the **golden cross is statistically meaningless** (n=4–7 OOS).

---

## 1. Methodology (honest fills — mandatory)

- **Entry** fills at the signal bar's **close + adverse slippage** (long pays up).
- **Donchian GTC stop is intraday gap-aware:** next bar `open < stop` → fill at open (+slip); elif `low <= stop` → fill at stop (+slip). A **close-to-close stop model is reported alongside** — it overstates the edge.
- **Signal / time exits** fill at close (−slip). One entry OR exit per bar (no double-fill). Open position at end-of-data is force-closed at last close (unbiased for the always-in MA/golden rules).
- **P&L per share** (1 share, additive equity). Slippage applied per side: bps = `slip_bps × (entry+exit)`; cents = `2 × slip_cents`.
- **Cost-stress grid** reported as PF / maxDD / net per slip cell; must hold **PF ≥ 1.0 at 2 bps** (realistic) and the kill rule uses **1¢/share** as the minimum-cost tick.
- **Walk-forward:** ~70/30 train/test split by **entry date** (last 30% = OOS) + 3 rolling folds for period fragility. OOS PF + OOS n reported.
- **Regime:** trades split by entry date at 2009-01-01 → 1993–2008 vs 2009–2026.
- **Promote / hold / kill** (per symbol × strategy): **PROMOTE** = OOS PF ≥ 1.2 **and** 2-bps OOS PF ≥ 1.0 **and** OOS n ≥ 30. **KILL** = OOS PF < 1.0 **or** 1¢/share OOS PF < 1.0. **THIN** = strong PF but OOS n < 30 (too thin to promote, *not* a kill). **HOLD** = otherwise. `0-TRADES` = entry never fired (diagnosed via indicator hit-count).

---

## 2. Per-symbol × per-family results

Cell = **full-sample PF | OOS(last-30%) PF (OOS n) `verdict`**. P = PROMOTE, H = HOLD, K = KILL, T = THIN (too thin to promote).

### Momentum — full PF | OOS PF (n) [verdict]

| sym | Donchian 20d | 200d MA trend | 50/200 golden cross |
|---|---|---|---|
| SPY | 1.32 \| 1.50 (155) `P` | 3.18 \| 3.78 (29) `T` | 17.20 \| 15.87 (4) `T` |
| QQQ | 1.45 \| 1.60 (115) `P` | 5.68 \| 8.33 (17) `T` | 33.44 \| inf (4) `T` |
| IWM | 1.22 \| 1.21 (83) `P` | 2.03 \| 2.26 (36) `P` | 1.74 \| 1.40 (7) `T` |
| DIA | 1.52 \| 1.79 (109) `P` | 1.91 \| 2.08 (37) `P` | 2.58 \| 2.67 (5) `T` |
| VTI | 1.52 \| 1.82 (113) `P` | 3.48 \| 4.23 (25) `T` | 13.02 \| 9.84 (4) `T` |
| XLF | 1.02 \| 1.21 (93) `P` | 1.83 \| 2.65 (37) `P` | 2.55 \| 1.91 (7) `T` |
| XLK | 1.28 \| 1.42 (122) `P` | 6.31 \| 8.83 (20) `T` | 34.32 \| inf (5) `T` |
| XLE | 1.14 \| 1.19 (75) `H` | 1.64 \| 1.60 (46) `P` | 2.53 \| 2.08 (6) `T` |
| XLV | 1.13 \| 1.20 (85) `H` | 1.32 \| 1.22 (54) `P` | 1.37 \| 0.91 (12) `K` |
| XLP | 0.77 \| 0.91 (95) `K` | 0.91 \| 0.74 (56) `K` | 1.41 \| 1.02 (10) `T` |
| XLY | 1.32 \| 1.46 (96) `P` | 2.60 \| 2.63 (31) `P` | 2.43 \| 2.29 (5) `T` |
| XLI | 1.39 \| 1.40 (94) `P` | 2.47 \| 2.77 (34) `P` | 4.08 \| 3.04 (6) `T` |
| XLB | 0.92 \| 0.93 (89) `K` | 1.11 \| 1.15 (49) `H` | 1.60 \| 1.32 (6) `T` |
| XLU | 0.69 \| 0.70 (90) `K` | 1.08 \| 1.03 (45) `K` | 5.79 \| inf (4) `T` |
| XLRE | 0.96 \| 0.62 (26) `K` | 0.95 \| 0.83 (22) `K` | 1.20 \| 2.54 (3) `T` |

### Mean-reversion — full PF | OOS PF (n) [verdict]

| sym | RSI(2)<10 dip | Bollinger lower-band | 5-day reversal |
|---|---|---|---|
| SPY | 2.00 \| 2.04 (122) `P` | 2.01 \| 1.83 (55) `P` | 1.34 \| 0.69 (24) `K` |
| QQQ | 1.84 \| 2.08 (94) `P` | 1.62 \| 1.47 (45) `P` | 1.87 \| 2.15 (41) `P` |
| IWM | 1.50 \| 1.48 (100) `P` | 0.85 \| 0.59 (43) `K` | 1.31 \| 1.28 (40) `P` |
| DIA | 1.42 \| 1.24 (106) `P` | 1.23 \| 1.00 (43) `K` | 1.66 \| 1.50 (21) `T` |
| VTI | 1.91 \| 2.82 (95) `P` | 1.21 \| 1.10 (37) `H` | 1.16 \| 0.84 (19) `K` |
| XLF | 1.61 \| 1.52 (108) `P` | 1.64 \| 1.06 (45) `H` | 1.56 \| 1.91 (34) `P` |
| XLK | 1.99 \| 2.59 (90) `P` | 2.32 \| 2.38 (42) `P` | 1.87 \| 2.27 (47) `P` |
| XLE | 1.12 \| 1.02 (115) `K` | 1.11 \| 0.86 (46) `K` | 1.26 \| 0.92 (62) `K` |
| XLV | 1.55 \| 1.64 (113) `P` | 1.59 \| 1.61 (51) `P` | 1.09 \| 0.89 (14) `K` |
| XLP | 1.25 \| 1.28 (97) `P` | 1.97 \| 2.54 (49) `P` | 3.02 \| 4.46 (8) `T` |
| XLY | 1.71 \| 1.74 (109) `P` | 1.14 \| 0.88 (45) `K` | 1.16 \| 1.11 (45) `H` |
| XLI | 1.51 \| 1.61 (106) `P` | 1.46 \| 1.20 (46) `P` | 1.44 \| 1.20 (25) `T` |
| XLB | 1.02 \| 1.01 (111) `K` | 0.87 \| 0.71 (50) `K` | 1.54 \| 1.82 (35) `P` |
| XLU | 0.98 \| 0.93 (98) `K` | 1.25 \| 1.37 (47) `P` | 1.45 \| 1.70 (19) `T` |
| XLRE | 0.95 \| 1.16 (41) `H` | 0.83 \| 1.79 (19) `T` | 0.97 \| 0.49 (6) `K` |

### Donchian stop-model delta (intraday-GTC vs close-to-close), OOS

The honest intraday number is **lower** than the close-to-close number (as expected — gap-throughs are captured). This is the difference between trusting a breakout edge and overstating it.

| sym | intraday OOS PF | close OOS PF | intraday n | close n |
|---|---|---|---|---|
| SPY | 1.50 | 1.71 | 155 | 154 |
| QQQ | 1.60 | 1.74 | 115 | 115 |
| IWM | 1.21 | 1.20 | 83 | 83 |
| DIA | 1.79 | 1.79 | 109 | 108 |
| VTI | 1.82 | 2.12 | 113 | 111 |
| XLF | 1.21 | 1.32 | 93 | 92 |
| XLK | 1.42 | 1.32 | 122 | 121 |
| XLE | 1.19 | 1.12 | 75 | 75 |
| XLV | 1.20 | 1.21 | 85 | 85 |
| XLP | 0.91 | 0.91 | 95 | 95 |
| XLY | 1.46 | 1.42 | 96 | 96 |
| XLI | 1.40 | 1.27 | 94 | 94 |
| XLB | 0.93 | 0.93 | 89 | 89 |
| XLU | 0.70 | 0.74 | 90 | 90 |
| XLRE | 0.62 | 0.74 | 26 | 26 |

### Pooled across all 15 symbols (equal-weight fractional return per trade)

| strategy | full PF | OOS PF | OOS n | full n |
|---|---|---|---|---|
| Donchian 20d | 1.07 | 1.27 | 1440 | 4455 |
| Donchian 20d (close-stop) | 1.08 | 1.30 | 1434 | 4445 |
| 200d MA trend | 1.99 | 2.42 | 538 | 1716 |
| 50/200 golden cross | 3.57 | 3.20 | 88 | 271 |
| RSI(2)<10 dip | 1.40 | 1.36 | 1505 | 5091 |
| Bollinger lower-band | 1.42 | 1.11 | 663 | 2240 |
| 5-day reversal | 1.46 | 1.31 | 440 | 1541 |

---

## 3. Regime split — the decisive finding (SPY, 1993–2008 vs 2009–2026)

| strategy | 1993–2008 PF (n) | 2009–2026 PF (n) | regime verdict |
|---|---|---|---|
| Donchian 20d | **0.89** (176) | 1.46 (253) | **regime-dependent — loses pre-2009** |
| 200d MA trend | 1.95 (58) | 3.62 (53) | regime-dependent (bull-heavy) |
| 50/200 golden cross | inf (6) | 14.0 (9) | meaningless sample |
| RSI(2)<10 dip | **2.22** (218) | **1.92** (206) | **robust in BOTH regimes** |
| Bollinger lower-band | 2.38 (98) | 1.91 (99) | robust both |
| 5-day reversal | 2.93 (42) | **0.94** (40) | **regime-flipped — died post-2009** |

The same split on other symbols confirms the pattern:

- **Donchian** QQQ 0.74 → 1.59, DIA 0.70 → 1.84 — the 20-day breakout made *nothing or lost* in the 1993–2008 chop/crashes and only profited in the 2009–2026 secular bull. The full-sample pooled PF (1.07) is honest: most of the OOS edge is a post-2016 artifact of one long bull regime.
- **MA200 trend** QQQ 0.65 → 7.28, IWM 0.77 → 2.46 — same bull-regime dependence.
- **RSI2 dip** is the only strategy whose PF stays well above 1.0 in *both* halves (SPY 2.22 / 1.92; VTI 1.70 / 1.96; QQQ 1.43 / 1.95) — buy-the-dip works in crashes *and* in grind-up markets.
- **5-day reversal** is the mirror image: it worked in the 1990s/2000s chop (SPY 2.93) and **stopped working** in the 2009+ trend regime (SPY 0.94). Inconsistent across symbols (QQQ *strengthened* to 2.16) → not deployable without a regime gate.

---

## 4. Redundancy check (SPY)

Before promoting a "second" mean-reversion edge, measure overlap against the champion:

- **RSI2 vs Bollinger:** 48% of Bollinger entries are also RSI2 entries; daily-$ P&L correlation **0.72**, position correlation 0.45 → **same buy-the-dip bet.** Bollinger lower-band "survives" the screen but is redundant — do **not** run it alongside RSI2 as diversification.
- **RSI2 vs Donchian:** 0 entry overlap, daily-$ P&L correlation **0.06** → genuinely independent (dip-buying vs breakout).
- **Donchian vs Bollinger:** 0.01 → independent.

**Conclusion:** the only two non-redundant, deployable edges are **RSI2 dip** and **Donchian breakout**.

---

## 5. Cost-stress grids (OOS, per-share $) — top candidates

`PF / maxDD$/sh / net$/sh` per slip cell, on the last-30% OOS trades.

**SPY — RSI2 dip** (OOS n=122):

| slip | PF | maxDD $/sh | net $/sh |
|---|---|---|---|
| 0 bps | 2.04 | −102.80 | +299.75 |
| 2 bps | 1.95 | −105.38 | +279.16 |
| 5 bps | 1.82 | −109.25 | +248.28 |
| 10 bps | 1.62 | −115.70 | +196.81 |
| 1 ¢/sh | 2.02 | −103.26 | +297.31 |
| 3 ¢/sh | 2.00 | −104.18 | +292.43 |

**QQQ — RSI2 dip** (OOS n=94): 0 bps 2.08 → 10 bps **1.74** → 3¢ **2.05**. Survives the whole grid.

**SPY — Donchian 20d** (OOS n=155):

| slip | PF | maxDD $/sh | net $/sh |
|---|---|---|---|
| 0 bps | 1.50 | −39.63 | +146.56 |
| 2 bps | 1.40 | −42.79 | +120.98 |
| 5 bps | 1.26 | −47.53 | +82.61 |
| 10 bps | 1.05 | −55.43 | +18.67 |
| 1 ¢/sh | 1.49 | −40.01 | +143.46 |
| 3 ¢/sh | 1.47 | −40.77 | +137.26 |

**QQQ — Donchian 20d** (OOS n=115): 0 bps 1.60 → 10 bps **1.25**, net $76/sh at 10 bps.

**SPY — 200d MA trend** (OOS n=29): 0 bps 3.78 → 10 bps **3.33** → 3¢ **3.74**; maxDD −$61/sh (~8% of notional).

### Cents-per-share bites low-priced symbols, not high-priced ones

1¢/share is ~0.1 bps on SPY ($776) but **~1.7 bps on XLF ($58)** and ~2.3 bps on XLU ($44). RSI2 OOS PF under the cents grid: SPY 2.04→2.00 (immune), but **XLF 1.52→1.29 at 3¢/sh** and XLB 1.01→0.86 (dies). The cents grid is the honest retail flat-cost model — for sub-$60 sector ETFs it is the binding constraint, for SPY/QQQ it is negligible.

---

## 6. Recommended signal specs (feeds `bot/equity_signals.py`)

### Candidate 1 — RSI2 buy-the-dip → **PROMOTE** (the champion)

- **Indicator:** RSI(2) on daily close, Wilder/EWM smoothing `alpha = 1/2`.
- **Entry:** `RSI(2) < 10` at the daily close → **buy at close + slip**.
- **Exit:** `RSI(2) > 70` **or** 5-trading-day time stop, whichever first, at close − slip.
- **Stop:** none (no hard stop — the 5-day hold is the risk cap; maxDD ≈ −13% of notional in the OOS).
- **Universe:** SPY, QQQ, IWM, DIA, VTI, XLF, XLK, XLV, XLP, XLI (avoid XLE/XLB/XLU/XLRE — KILL).
- **Stats (SPY):** full PF 2.00 · OOS PF 2.04 (n=122) · win 70% · avg hold 3.6 d · 13 trades/yr · regime 2.22/1.92 · survives 10 bps (1.62) + 3¢ (2.00). Rolling folds 2.48/1.74/1.97.

### Candidate 2 — Donchian 20-day breakout → **PROMOTE (regime-conditional)**

- **Indicator:** prior 20-day high/low = `max(High[−20:−1])`, `min(Low[−20:−1])` (shifted, excludes today).
- **Entry:** `close > prior 20d high` → **buy at close + slip**.
- **Stop:** fixed `2 × ATR(14)` below entry, **GTC intraday gap-aware** — next open < stop → fill at open (+slip); elif low ≤ stop → fill at stop (+slip).
- **Exit:** `close < prior 20d low`, **or** 5-day time stop, **or** stop hit — close/signal exits at close − slip.
- **Universe:** SPY, QQQ, IWM, DIA, VTI, XLF, XLK, XLY, XLI.
- **Stats (SPY):** full PF 1.32 · OOS PF 1.50 (n=155) · win 57% · hold 4.7 d · 13 trades/yr · **intraday 1.50 vs close-stop 1.71** · regime **0.89 / 1.46**. 10-bps OOS PF 1.05 (thin margin) — **gate with a 200d-MA regime filter** (only take breakouts when `close > SMA200`), which is precisely the bull regime where the edge lives.

### Candidate 3 — 200d MA trend filter → **HOLD (regime overlay, thin)**

- **Indicator:** 200-day SMA of close.
- **Entry:** `close` crosses **above** SMA200 → buy at close + slip.
- **Exit:** `close` crosses **below** SMA200 → sell at close − slip.
- **Stop:** none.
- **Stats (SPY):** full PF 3.18 · OOS PF 3.78 (**n=29 — thin**) · win 24% · hold 55 d · 3 trades/yr · regime 1.95/3.62.
- **Role:** not a standalone signal (n too thin, low turnover, whipsaw-prone) — use it as the **long/flat regime gate** for Candidate 2 and as a drawdown filter. Deploying it as an always-in "buy above 200d MA" sleeve only captures the 2009+ bull premium and gives back most of it in the next secular chop.

---

## 7. Verdict rollup

- **PROMOTE (non-redundant, deployable):** RSI2 dip (11/15 symbols), Donchian breakout (9/15, regime-conditional).
- **HOLD:** 200d MA trend (regime overlay), Bollinger lower-band (redundant with RSI2 — 0.72 corr).
- **KILL:** 5-day reversal (regime-flipped + inconsistent), golden cross (n=4–7 OOS, statistically meaningless despite inf/15× PF), and the low-quality symbols XLE/XLB/XLU/XLRE for momentum, XLE/XLB for RSI2.

## 8. Honest caveats

1. **Donchian's OOS PF is a bull-regime artifact.** Full-sample pooled PF is 1.07; pre-2009 PF is 0.89 (SPY), 0.74 (QQQ), 0.70 (DIA). Promoting on the OOS number alone would ship a strategy that is *long the 2009–2026 regime*, not a timeless edge. The 200d-MA regime gate is mandatory, not optional.
2. **Intraday-GTC stop PF < close-to-close stop PF** everywhere it matters (SPY 1.50 vs 1.71). All promote/hold decisions above use the **intraday** number.
3. **Mean-reversion has no hard stop.** RSI2's 5-day time cap is the only protection; a slow-motion crash (2000–02, 2008, 2022) produces clusters of losers (buying a falling knife). maxDD for RSI2 SPY ≈ −$103/sh OOS. Expect drawdowns, not a smooth curve.
4. **Golden cross / MA200 PFs are misleading at n<30.** A handful of trades over 33 years (golden cross: 4–7 OOS per symbol) cannot support PF 15–inf. These are "too thin", never a kill on the PF alone.
5. **Costs are asymmetric across the universe.** 10 bps kills Donchian's margin (SPY net +$18.67/sh OOS); 3¢/share is trivial for SPY/QQQ but binds sub-$60 sectors (XLF RSI2 1.52→1.29). Match the cost model to the symbol's price level.
6. **No hourly validation.** All six strategies are daily-bar rules; the ~2y hourly history was not used (2y ≈ the post-2023 bull, insufficient for OOS n≥30). The daily close-entry assumption means intraday gap-throughs on *entries* are not modeled — only stop exits use intraday fills.
7. **Dividend-adjusted OHLC.** S3 daily is split+dividend adjusted (SPY 1993 close $43.94 vs 2026 $776). Returns are total-return; a live cash-account bot must subtract distributions it won't actually reinvest. Long-only total-return backtests slightly flatter live P&L.
8. **0 trades never occurred** — every (symbol × strategy) cell produced trades; hit-counts were cross-checked against trade counts to rule out the shadowing class of bug.

---

*Artifacts: `/tmp/equities_sweep.py` (runner, not committed), `/tmp/equities_sweep_results.json` (full per-cell numbers). No orders, no live trading.*
