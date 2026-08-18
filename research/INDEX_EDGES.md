# Index edge — consolidated robustness verdict (RSI2 + Donchian)

Long-sample (2000-09 → 2026-08) drawdown-first assessment of the two sleeves
`bot/live.py` runs. Per-symbol batteries: `rsi2_robustness.py`,
`donchian_robustness.py`; portfolio: `index_portfolio.py`. All $ per ES full
contract ($50/pt); ÷10 for MES. Cost: 1.3bp fee + 1 tick/side slip baseline.

## The two edges are complementary, not redundant

| ES (26y) | RSI2 long | Donchian long | **Combined (1+1)** |
|---|---|---|---|
| PF @1tick | **1.92** | 1.34 | 1.66 |
| win rate | 70.5% | 58.5% | — |
| payoff | 0.80 | 0.95 | — |
| skew / kurt | −0.89 / 7.2 | +0.11 / 4.7 | — |
| maxDD (chronological) | −$42.9k | −$20.0k | **−$33.9k** |
| worst single trade | −$16.6k | −$8.1k | — |
| worst MAE (open loss) | −$30k (no stop) | −$10.5k (stop) | — |
| daily P&L corr | | **−0.001** | |

They are **independent** (corr ≈ 0) and, more importantly, **complementary across regimes**:

| year | RSI2 | Donchian | Combined |
|---|---|---|---|
| 2008 (crash + V-bounce) | 1.73 ✅ | 0.11 ❌ | 1.41 ✅ |
| 2011 | 0.87 ❌ | 2.38 ✅ | 1.07 ✅ |
| 2018 (grinding sell-off) | 0.33 ❌ | 4.76 ✅ | 0.60 ⚠️ |
| 2020 (COVID) | 0.89 ❌ | 1.78 ✅ | 1.22 ✅ |
| 2022 (bear) | 1.13 | 1.14 | 1.13 |

RSI2 is a *dip-buyer* (wins V-bounces, loses grinding declines). Donchian is a
*breakout* (wins trends, loses choppy/ranging years — 11 losing years alone).
Combined, the only losing years left are **2007 (0.96)** and **2018 (0.60)**.

## Donchian-specific findings

- **Has a stop → bounded tail.** Worst MAE −$10.5k vs RSI2's −$30k; worst trade −$8.1k vs −$16.6k. maxDD −$20k is less than half RSI2's.
- **Weaker PF, regime-dependent.** PF 1.34 (ES) / 1.56 (NQ). Loses ~half of all years (2001-09 whipsaw, 2021, 2025). Trend-only: needs a trending year to pay for the chop.
- **Default 2×ATR stop is NOT optimal.** stop_atr sweep: 1.5→1.28, 2.0→1.34, 2.5→1.47, 3.0→1.48, **4.0→1.59**. Wider stops let breakouts run. (Tuning note, not a change — 2×ATR remains the safe default.)
- **Cost-robust but thinner margin than RSI2.** 5-tick PF: ES 1.16 (vs RSI2 1.74). Entry 1-bar-late barely changes (1.35); 2-bar-late degrades (1.20).
- **NQ is the better Donchian** (PF 1.56, positive skew +1.88, payoff 1.14 — NQ breakouts run; ES/YM chop).

## Verdict (drawdown-first)

1. **Run BOTH sleeves — they are a portfolio, not a menu.** The combined sleeve
   cuts the worst drawdown ~21% (ES −$42.9k → −$33.9k), eliminates 9 of 11 Donchian
   losing years and 1 of 3 RSI2 losing years, and lowers the OOS/regime fragility of
   each. This is the single most valuable structural property of the index edge.
2. **The residual tail is 2018 (combined 0.60).** A grinding, no-bounce sell-off is
   the one regime neither sleeve covers. Size the index sleeve so a 2018 repeat is
   tolerable (−$2.1k MES RSI2 leg + Donchian offset).
3. **Neither sleeve alone is a capital-preservation core.** RSI2 = high PF, fat left
   tail, no stop. Donchian = low PF, bounded tail, regime-dependent. Together they
   are a *defensible satellite* — small sizing, no leverage, accept the 2018 tail.
