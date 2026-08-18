# LANE 24 — KAMA crossover: DAILY re-test (2-3 day swing horizon)

**Date:** 2026-08-18 · **Operator:** VPS Hermes (builder) · **Validation only — no live/exec.**
**Engine:** `research/lane24_kama_daily.py` (KAMA imported from `intraday_validate.kama`: ER n=10,
fast=2, slow=30 — identical to the 5-min test; only the bar timeframe changes).
**Full results:** `research/lane24_kama_daily_results.json` (mirrored to S3 `research/lane24_kama_daily_results.json`).

Registry verdict was **NO-GO "wrong horizon"** (5-min whipsaw: pooled 0.82 @0t / 0.70 @3t, OOS 0.68).
Per the laptop directive, re-tested on **DAILY bars** with a **2-3 day hold** (owner's 1/2/3-day
swing horizon), walk-forward IS/OOS, **bps cost model @5-10 bps round-trip**, max drawdown.

---

## 1. Method

- Instruments: **index futures continuous** (S3 `yf/futures/`: ES=F 2000→, NQ=F 2000→, YM=F 2002→,
  RTY=F 2017→ — 6.1k–6.5k daily bars) and **index ETFs** (yfinance split+div adjusted: SPY 1993→,
  QQQ 1999→, DIA 1998→, IWM 2000→ — 6.6k–8.4k bars).
- Entry: close crosses KAMA (long above, short below). Exit: opposite crossover OR time stop
  (**hold 2 / 3 trading days**), whichever first; a **pure-crossover** variant (hold until opposite
  cross) reported for reference. Long-only AND both-dir.
- Cost: bps round-trip ∈ {0, 5, 10}, applied as a fractional-return haircut per trade.
- Walk-forward 60/40 by entry date (assign trades, no re-run). P&L = fractional return
  (exit/entry−1)×side; maxDD on a chronological daily equity curve (zero-filled).

## 2. Result — 2-3 day hold (the owner's horizon) is NET-NEGATIVE

**Long-only index ETFs, OOS PF @ 5bps / @ 10bps:**

| Sym | 2d hold @5 / @10 | 3d hold @5 / @10 | pure-cross @5 / @10 |
|---|---|---|---|
| SPY | 0.89 / 0.80 | 1.02 / 0.93 | 1.34 / 1.26 |
| QQQ | 0.95 / 0.88 | 0.93 / 0.87 | 1.36 / 1.30 |
| DIA | **1.16 / 1.05** | **1.10 / 1.01** | 1.55 / 1.46 |
| IWM | 0.92 / 0.86 | 0.91 / 0.86 | 1.03 / 0.99 |

**Index futures both-dir, OOS PF @ 5bps / @ 10bps:**

| Sym | 2d hold | 3d hold | pure-cross |
|---|---|---|---|
| ES=F | 0.86 / 0.77 | 0.75 / 0.69 | 1.42 / 1.34 |
| NQ=F | 0.85 / 0.79 | 0.80 / 0.76 | 1.47 / 1.41 |
| YM=F | **1.11 / 1.01** | 1.01 / 0.93 | 1.69 / 1.59 |
| RTY=F | 1.00 / 0.93 | 0.90 / 0.85 | 0.44 / 0.42 |

At the **2-3 day hold horizon the directive targets**, OOS PF is **0.75–1.16 @5bps** — only DIA
(2d 1.16, 3d 1.10) and YM=F 2d (1.11) clear 1.1, and **every one of those collapses below 1.1 at
10bps** (DIA 3d → 1.01, DIA 2d → 1.05, YM 2d → 1.01). Net cumulative return over the full sample
is ~0 to negative for every 2-3 day variant (e.g. SPY 3d +2.6% over 33 years). **The 2-3 day hold
is not a tradeable edge.**

## 3. The pure-crossover OOS ">1.3" is a bull-market proxy, not an edge

The only positive OOS numbers (pure crossover, OOS PF 1.3–1.7) are **regime-flipped**: in-sample PF
is below 1.0 on every instrument (ES=F 0.82, NQ=F 0.89, YM=F 0.89, SPY 0.97, QQQ 0.95, DIA 1.00),
i.e. the strategy *lost money* 2000→~2015 and only "worked" in the recent 40% window (the 2015–2026
bull). That is KAMA holding you long through a bull market — a buy-and-hold proxy — not a
repeatable crossover edge. And it carries **maxDD −12% to −61%** (cumulative-return) even in this
best case, which fails the owner's capital-preservation bar outright.

## 4. Short leg destroys both-dir (confirms prior finding)

Both-dir OOS PF is 0.43–0.58 on equities (SPY 0.43, DIA 0.58, IWM 0.53) and 0.42–0.44 on RTY=F —
the short side is wrecked by squeezes/bull drift, exactly as seen in the equities xsmom lane.

## 5. VERDICT — NO-GO-WITH-REASON (confirmed on daily; no realistic trigger)

- The re-test **confirms** the NO-GO, but for a *different* reason than "whipsaw": at the owner's
  2-3 day swing horizon, KAMA crossover is **net-negative after costs** (OOS PF ≤1.16 @5bps, <1.1
  @10bps everywhere). It whipsaws *less* on daily bars but captures no edge at that horizon.
- The pure (untimed) crossover shows positive OOS only as a **bull-market buy-and-hold proxy**
  (IS PF < 1.0, OOS > 1.0 regime flip) with **unacceptable drawdown** (−12% to −61% cumulative).

### Re-activation trigger

**None realistic.** KAMA's only positive form needs the multi-week/month trend hold (not the 2-3 day
swing) AND is a bull-regime proxy with 25-60% drawdowns — both contradict the 2026-08-16
capital-preservation directive. Re-open only if the strategy is *redefined* to something this test
did not measure (e.g. long-only + volatility position-sizing + a hard bear-regime filter), which
would be a new strategy, not this lane. **Lane 24 stays NO-GO-WITH-REASON permanently as specified.**
