# BOOK SCAN — CFI "Complete Guide to Trading" candidates

Date: 2026-08-16 · Operator: VPS Hermes (builder) · **Paper-only, never-lose-money, no live.**
Source: laptop Hermes read CFI "Complete Guide to Trading"; 3 new candidates sent for Gate-1.
Script: `research/book_scan.py` → `research/book_scan_results.json`.

Rubric (binding, per INTRADAY_BUILD.md): **capital preservation first** — rank by
**maxDrawdown, worst-case (largest single-trade loss / worst day), consistency
(win rate + longest losing streak)**. PF / net / return are secondary tie-breakers.

Cost/fill (honest, unchanged from validate_edges.py): entry @ signal close + adverse
slippage; GTC stop intraday gap-aware; 1 entry/exit per bar; futures fee 1.3bp
round-trip + slip 0/1/2/3 ticks/side. All figures below at **fee 1.3bp + 1-tick slip**
(the honest baseline). Engine cross-check: Donchian-index intraday-GTC PF 1.51
reproduces the documented 1.51 (close-based 1.86 overstates) — engine is sound.

Data: yfinance daily — ES/NQ/YM/GC 26y (2000→2026), SPY 1993→, QQQ/DIA/IWM 1998→.
Intraday = ES 1h/4h, 2y only (free limit) — directional smoke, not an edge.

---

## VERDICT SUMMARY

| # | Candidate | Verdict | Reason |
|---|---|---|---|
| 1 | ADX(14)>25 regime filter | **NO-GO** (as a maxDD reducer) | Does not lower maxDD on ANY of the 4 existing edges. |
| 2 | Golden/Death cross (50/200 SMA) | **NO-GO** | Deeper maxDD than buy&hold AND lower return; ~1 trade/yr. |
| 3 | 5/8/13 EMA crossover | **NO-GO** | L/S negative; long-only win rate + maxDD worse than existing edges. |

One actionable nugget survives (see Part 1): **RSI2 buy-dip is a TREND dip-buy, not a
range mean-reverter** — its worst drawdowns live in the range regime.

---

## Part 1 — ADX(14)>25 regime filter on existing edges

Q: does gating ENTRIES to ADX>25 (trend) reduce maxDD / improve consistency vs unfiltered?

| Edge | Gate | n | win% | PF | maxDD$ | worstTrd$ | streak | net$ |
|---|---|---|---|---|---|---|---|---|
| Donchian idx (ES/NQ/YM) | baseline | 923 | 59 | 1.51 | −30,112 | −16,946 | 7 | 299,677 |
| | **ADX>25** | 334 | 57 | 1.40 | **−35,277** ⬆ | −16,946 | 6 | 103,802 |
| | ADX≤25 | 638 | 58 | 1.34 | −27,603 | −13,227 | 7 | 139,203 |
| RSI2 idx (ES/NQ/YM) | baseline | 998 | 65 | 1.61 | −23,428 | −22,471 | 7 | 533,730 |
| | **ADX>25** | 414 | **70** ⬆ | **2.12** ⬆ | −26,039 ⬆ | −22,471 | **5** ⬇ | 435,678 |
| | ADX≤25 | 640 | 63 | 1.30 | **−46,510** ⬆⬆ | −19,488 | 5 | 159,629 |
| GC TSMOM | baseline | 126 | 25 | 1.00 | −133,280 | −10,689 | 15 | −960 |
| | ADX>25 | 71 | 21 | 1.11 | −133,280 = | −10,689 | 14 | 17,864 |
| | ADX≤25 | 100 | 27 | 1.11 | −133,280 = | −8,820 | 11 | 21,919 |
| GC Donchian | baseline | 466 | 52 | 1.34 | −48,618 | −33,402 | 7 | 166,202 |
| | ADX>25 | 200 | 48 | 1.27 | **−60,066** ⬆ | −33,402 | 6 | 66,994 |
| | ADX≤25 | 304 | 55 | 1.27 | −36,238 | −13,613 | 4 | 75,542 |

**Findings (drawdown-first):**

- **ADX>25 does NOT reduce maxDD on any edge.** Donchian idx maxDD *rises* (−30.1k → −35.3k),
  GC Donchian rises (−48.6k → −60.1k), GC TSMOM flat (−133.3k), RSI2 slightly worse
  (−23.4k → −26.0k). The filter trades fewer signals for the same or deeper drawdowns.
  **→ NO-GO as the "highest-value" capital-preservation addition the laptop expected.**
- **The genuinely new insight is RSI2's regime identity.** The naive assumption ("buy-dip
  works in ranges") is backwards: RSI2 idx at ADX>25 improves win rate **65→70%**, PF
  **1.61→2.12**, losing streak **7→5** — while the RANGE side (ADX≤25) carries a maxDD of
  **−46.5k (2× baseline)**. So RSI2's worst drawdowns come from *ranges*, not trends.
  Buying RSI2<10 dips is *buying weakness inside an uptrend*; in a range, RSI2<10 means
  the index is genuinely breaking down.
- Why baseline maxDD (−23.4k) beats both RSI2 sub-regimes: maxDD is a path property, and
  mixing trend + range trades diversifies loss timing. Removing a regime does not lower
  the combined maxDD unless the *removed* regime is the drawdown source — and here the
  drawdown source is the regime the filter keeps-out (range), not the one it keeps.
- **Actionable (not this build):** if RSI2 ever needs a regime overlay, filter OUT the
  range (require ADX>25) to trade only the high-consistency trend dips — but that still
  does not beat baseline maxDD, so it is a *consistency* trade, not a *drawdown* trade.

**Verdict Part 1: NO-GO** on the stated objective (maxDD reduction). The RSI2 regime
finding is retained as research intel; no live change.

---

## Part 2 — Golden/Death cross (50 SMA vs 200 SMA, always-in L/S)

| Sym | n | win% | PF | maxDD$ | net$ | B&H maxDD$ | B&H return$ | avgHold |
|---|---|---|---|---|---|---|---|---|
| ES=F | 24 | 50 | 2.40 | −81,764 | 187,779 | −59,900 | 316,900 | 263d |
| NQ=F | 32 | 47 | 4.01 | −141,065 | 433,746 | −116,940 | 529,760 | 198d |
| YM=F | 28 | 39 | 1.37 | −96,911 | 54,572 | −55,130 | 217,585 | 211d |
| SPY | 31 | 52 | 2.79 | −174 | 467 | −113 | 752 | 265d |
| QQQ | 33 | 45 | 4.69 | −157 | 604 | −138 | 688 | 202d |
| DIA | 38 | 45 | 1.38 | −180 | 110 | −97 | 493 | 183d |
| IWM | 38 | 39 | 0.93 | −175 | −20 | −73 | 272 | 168d |

(B&H = buy-and-hold over the same window, same units: futures in $ via mult, equities $/share.)

**Findings (drawdown-first):**

- **Golden cross is strictly WORSE than buy-and-hold on the rubric.** On every name the
  maxDD is *deeper* than buy-and-hold (ES −81.8k vs −59.9k; NQ −141.1k vs −116.9k;
  SPY −174 vs −113) while the net is *lower* (ES 187.8k vs 316.9k; SPY 467 vs 752).
  It neither caps drawdown nor adds return — it only reduces time-in-market, and pays for
  that with late entries + short-side squeezes in secular bulls.
- **~1 trade/year** (24–38 trades over 26–33y). Statistically meaningless; a single regime
  makes the difference. Classic slow signal that survives on gross PF but fails the
  capital-preservation bar because the death-cross SHORT leg gets whipsawed and the long
  leg re-enters after the worst of each decline is over.
- IWM already nets negative (PF 0.93) even before the deeper cost grid.

**Verdict Part 2: NO-GO.**

---

## Part 3 — 5/8/13 EMA crossover

| Frame | Mode | n | win% | PF | maxDD$ | net$ | avgHold |
|---|---|---|---|---|---|---|---|
| daily ES | long | 245 | 37 | 1.44 | −42,952 | 132,187 | 16.7d |
| daily ES | L/S | 490 | 30 | 0.92 | −124,967 | −58,653 | 13.3d |
| daily GC | long | 242 | 32 | 1.75 | −69,590 | 264,942 | 15.1d |
| daily GC | L/S | 483 | 28 | 1.15 | −133,853 | 113,586 | 13.4d |
| ES 1h | long | 501 | 32 | 1.01 | −50,673 | 4,018 | 15.5 |
| ES 1h | L/S | 1003 | 28 | 0.85 | −166,839 | −118,127 | 13.6 |
| ES 4h | long | 134 | 33 | 1.16 | −50,352 | 32,367 | 16.9 |
| ES 4h | L/S | 267 | 30 | 0.85 | −102,072 | −60,270 | 13.8 |

**Findings (drawdown-first):**

- **L/S variant is negative everywhere** (PF 0.85–1.15; ES L/S nets −58.7k daily, −118.1k 1h).
  Shorting every EMA cross-down into a secular bull = death by a thousand whipsaws. Dead on arrival.
- **Long-only survives only nominally.** win rate 32–37% is well below the existing edges
  (Donchian 52–59%, RSI2 65%); maxDD is *deeper* than the existing index edges
  (daily ES long −43.0k vs RSI2 −23.4k / Donchian −30.1k). The one nominally strong cell
  (daily GC long PF 1.75) still has win 32% and maxDD −69.6k — worse on both axes than the
  already-live GC Donchian (win 52%, maxDD −48.6k). Same bet, worse risk profile → redundant.
- **Intraday (1h/4h) long** is break-even after cost (PF 1.01–1.16, net ≈ 0) on a 2y sample
  that's too short to trust.

**Verdict Part 3: NO-GO.**

---

## Caveats

- **GC TSMOM honest-fill note (out of scope, flagged):** EDGE_SWEEP.md quoted TSMOM PF 1.37+
  from the original no-stop sweep. Here, WITH the live never-lose-money 3×ATR fixed stop +
  daily re-entry (honest intraday gap-aware fills), TSMOM is **PF 1.00 / net ≈ $0 / maxDD
  −133.3k**. That is the honest number, not a regression — worth a dedicated re-validation
  of the GC TSMOM sleeve against its documented promote figures. Not part of this scan's mandate.
- **Gold 2026 vol is real:** GC maxDD numbers are dominated by a genuine crash (2026-01-30,
  −11.4% / −$604/oz in one session), not a roll artifact (verified against yfinance GC=F).
- Intraday frames = 2y only (yfinance 1h free limit) — smoke, not an edge.

---

## Bottom line

None of the three CFI candidates clears the capital-preservation bar. ADX(14)>25 is **not**
the drawdown filter the laptop expected it to be; the one real takeaway is that RSI2 is a
trend dip-buy (range is its drawdown regime), which is research intel, not a live change.
No code touched live. Never-lose-money intact. Paper-only.
