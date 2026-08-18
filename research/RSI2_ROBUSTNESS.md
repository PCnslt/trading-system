# RSI2-LONG robustness pass (review follow-up)

Answers the review's "statistically thin" questions for **ES RSI2<10 long / RSI2>70 or 5-day exit / no stop** — the same sleeve `bot/live.py` runs. Reuses the honest fill model + 1.3bp fee from `validate_edges.py`, but on the **LONG sample (2000-09 → 2026-08, ~26y)** so the 2000-02 dotcom, 2008 GFC and 2022 bear are in-sample. The prior "OOS PF 2.57" was computed on 2010-2026 only (excludes the dotcom and 2008).

Source: `research/rsi2_robustness.py` → `rsi2_robustness_results.json`. All $ are per ES **full** contract ($50/pt, tick 0.25 = $12.50); divide by 10 for MES.

## Headline (ES, 329 trades, 26y)

| metric | value |
|---|---|
| PF @ 1 tick/side | **1.92** (2.02 @0tick → 1.74 @5tick) |
| win rate | 70.5% |
| **payoff (avg win / avg loss)** | **0.80** ⚠️ |
| return skew / kurtosis | **−0.89 / 7.18** ⚠️ (left, heavy tails) |
| worst single trade | −$16.6k |
| worst intra-trade MAE | −601 pts (−$30k, **no price stop**) |
| full-sample maxDD (chronological) | **−$42.9k** |
| OOS (last 40%) PF / maxDD | 1.93 / −$42.9k (worst streak 2) |

## What's robust (good news)

1. **Slippage** — PF 1.97 / 1.92 / 1.87 / 1.83 / 1.78 / 1.74 at 0/1/2/3/4/5 ticks per side. Survives 5× the live 1-tick assumption. Not a thin edge (avg trade +$620 vs ~$125 round-trip at 5 ticks).
2. **Entry timing** — fill one bar later: PF 1.76, maxDD *improves* to −$38k. Two bars later: 1.73 / −$21k. The edge does **not** depend on catching the exact signal close (NQ even improves to 2.29 on 1-bar-late).
3. **RSI threshold** — stable across lo 8–12 (PF 1.67–2.14, maxDD −$39k–50k). Not knife-edge. Degrades only at lo 15 (1.43–1.45). lo 10 is a reasonable choice.
4. **Regime** — works in trend (1.98) *and* range (1.99); best mid-vol (3.55), weak high-vol (1.64) / low-vol (1.46).

## What's the real risk (drawdown-first)

1. **Left-tail, not the win rate.** 70% win rate with 0.80 payoff = "many small wins, occasional big loss". The skew (−0.89) and kurtosis (7.18) say the loss tail is fat.
2. **2018 is the drawdown source.** Per-year PF: **2018 = 0.33, net −$21.3k** (Q4 grind), 2011 = 0.87, 2020 = 0.89. 2008 (+1.73) and 2022 (+1.13) were *positive* — V-shaped bounces are capturable; the grinding 2018 sell-off is not.
3. **No price stop → −$30k worst MAE.** The 5-day time stop caps *time*, not *price*. A single trade can be −601 pts underwater before exit.
4. **Bootstrap understates the drawdown.** iid/block-10 bootstrap median maxDD ≈ −$24.7k, but the *realized* chronological maxDD is −$42.9k — because resampling breaks the 2018 loss clustering. Plan for −$25k…−$45k, not the bootstrap median.

## Cross-symbol agreement

| | PF@1t | win% | payoff | skew | 5-tick PF |
|---|---|---|---|---|---|
| ES | 1.92 | 70.5% | 0.80 | −0.89 | 1.74 |
| NQ | 1.79 | 64.6% | 0.98 | −0.34 | 1.74 |
| YM | 1.55 | 66.3% | 0.79 | −1.37 | 1.48 |

All three agree on direction (positive PF, cost-robust). YM is weakest + most skewed; NQ is the best-balanced (payoff 0.98, least skew, most timing-robust).

## Verdict (drawdown-first)

**The edge is real and cost/timing robust — but it is NOT a capital-preservation core.** It is a left-tailed dip-buyer whose entire risk is a 2018-style grinding sell-off. For live: keep it as a **satellite with small sizing** (a 2018-type year on ES full = −$21k → −$2.1k on MES), and treat the 70% win rate as the *reason it feels safe*, not as safety. The review was right: the "2.57 OOS" was flattered by the 2010 start date and bull-year concentration.
