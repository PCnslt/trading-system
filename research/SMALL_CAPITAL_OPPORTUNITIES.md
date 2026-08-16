# Small-Capital Opportunity Sweep (<$1,500/position) — drawdown-first ranking

**Date:** 2026-08-16 · **Author:** VPS Hermes (builder) · **Research-only, no orders.**
**Capital:** ~$700 Robinhood (stocks/options, $0 comm, fractional) + ~$500 IBKR
(micros only, no overnight >$750). **Standard (owner 2026-08-16):** CAPITAL
PRESERVATION #1 → rank by **smallest drawdown → consistency → returns** (PF/Sharpe are
tie-breakers, not primary).

Every number is from a backtest with honest fills (entry/exit at signal close/next-open
+ adverse slippage, intraday gap-aware stops) and cost stress. New results this pass:
`research/stock_mr_results.json` (RSI2 on 50 S&P100), `research/smallcap_sweep_results.json`
(gap / momentum / pairs), `research/options_spread_synth_results.json` (credit-spread model).

---

## Ranked opportunity list

| # | Strategy | Where | PF (honest cost) | win | Drawdown profile | Verdict |
|---|---|---|---|---|---|---|
| 1 | **RSI2 buy-the-dip** (large-caps + ETFs, fractional) | Robinhood | 1.47 OOS / 1.36 @5bps (basket); 2.04 OOS (SPY) | 67–70% | worst trade −38%; bear single-years 2008 PF 0.36 / 2022 0.81; compounded maxDD ≈ −58–69% | **PROMOTE — satellite, regime-gated** |
| 2 | **Donchian 20d breakout** (ETFs only, SMA200-gated) | Robinhood | 1.50 OOS (SPY) / 1.05 @10bps | 57% | regime-dependent (0.89 pre-2009) | **HOLD — small diversifier** |
| 3 | **Seasonal commodities** (month-of-year) | IBKR (post-deposit) | 1.20 full / 1.23 OOS (commodity-only) | 52% | cost-stable through 3 ticks; monthly hold | **POST-DEPOSIT — not now** |
| 4 | Pairs / stat-arb (liquid pairs) | IBKR (needs shorting) | 1.29 → 1.14 @10bps | 62% | thin +0.4%/trade; requires short leg | NO-GO for now |
| 5 | Gap fade (2% gap-down, 5d hold) | Robinhood | 1.34 → 1.26 @10bps | 55% | redundant with RSI2 (same buy-dip) | dominated by #1 |
| 6 | Short-term momentum (5d) / single-stock Donchian | Robinhood | 1.20 → 1.07 @10bps | 52% | high turnover, cost-fragile | NO-GO |
| 7 | **Options credit spreads / iron condors** | Robinhood | 1.04 (synthetic, IV=realized) | 57% | worst −87% of margin | **NO-GO** (see §3) |
| — | CSP→CC wheel (prior) | Robinhood | 0.72 | 80% | maxDD −37%, CAGR −2.4% | dead (prior) |

**Bottom line: one deployable edge fits $700 now — the RSI2 buy-the-dip basket.** The
Donchian ETF breakout is a legitimate second, non-redundant sleeve. Everything else is
either too capital-heavy, needs data we don't have, or has no honest edge.

---

## 1. Equities — mean-reversion (the winner)

**RSI2 buy-the-dip** — full spec in `ROBINHOOD_LANE_PLAN.md`. This sweep adds the
individual-large-cap confirmation the ETF sweep didn't have:

- 50 S&P100 names (top-50 by 20d $volume), 2006–2026, `close>SMA200` gate, 2×ATR hard
  stop + 5d cap + revert:
  - thr=2: full PF 1.54 (n=3064), win 67.5%; thr=5: PF 1.42 (n=7955).
  - Walk-forward OOS (threshold from train only): **PF 1.47** (n=1321), **1.36** @5bps,
    **1.26** @10bps. All 5 folds >1.0.
- Trailing stop tested and **rejected** (lowers PF 1.54→1.50; raises stop-outs 17.5→34.8%).
- **Honest drawdown profile (drawdown-first):** the coarse 2–3yr regime buckets are all
  >1.0, but **single bear years are negative** — 2008 PF **0.36** (thr2) / 0.86 (thr5),
  2022 PF **0.81**, plus 2018/2020/2025 ≈ 0.80–0.84. Worst single trade −37.9% (BKNG
  gap-through), an 18-trade losing streak, and **compounded portfolio maxDD ≈ −58–69%**
  if run as an equal-weight compounding book. Strong recovery years (2009 3.37,
  2017 4.78) carry the average.
- **Risk to respect:** the −37.9% worst trade is a gap-through-the-stop; control via
  **max ~5% capital/name (≈ $25–50) + 10–20 names**, never a tighter stop. An
  **index-level `SPX>SMA200` entry gate is recommended to address the bear-year decay —
  not yet validated** (the per-name SMA200 filter was insufficient in 2008/2022).

**Why it's #1:** highest PF, win rate, and average-case consistency of anything
executable at $700, with a clean walk-forward. **But it is not bear-proof** — it is the
best *satellite* available, not a capital-preservation core. Deploy sized-down and
regime-gated, paper-first.

## 2. Equities — momentum (second, thin)

**Donchian 20d breakout (ETFs, SMA200-gated):** OOS PF 1.50 (SPY) but 10bps PF 1.05,
regime-dependent (0.89 pre-2009). Independent of RSI2 (0.06 corr). Deploy only as a
small diversifier on **ETFs** — single-stock breakouts are too noisy (pooled PF 1.18→1.04).

**12m cross-sectional momentum (long-only)** — flagged in `EDGE_SWEEP2.md` (PF 1.80,
Sharpe 0.78) but **not a small-capital strategy**: it needs a 50-name long book,
rebalanced monthly, so it's a future funded-account idea, not a $700 lane.

**5-day time-series momentum:** PF 1.20 → 1.07 @10bps, 53k trades, high turnover,
cost-fragile. NO-GO.

## 3. Options — defined-risk spreads / iron condors (NO-GO, data-gapped)

**Data reality:** S3 has **no historical options bars and no equity options** — only
futures-options chain *metadata* (expirations + strikes, no prices/greeks). A real
credit-spread backtest needs paid historical options data (IV surface per strike/expiry).
So I built a **synthetic Black-Scholes model** (IV = realized vol) on the 50 large-caps,
monthly 30DTE iron condors, 5%-wide wings, held to expiry:

| Vol premium (IV/realized) | PF | win | maxDD | worst trade | read |
|---|---|---|---|---|---|
| 1.00 (no premium) | **1.04** | 57% | −38.4 | **−87% of margin** | breakeven + fat tail → NO edge |
| 1.15 (15% premium) | 1.48 | 63% | −7.9 | −85% | edge exists only WITH a vol premium |

**Conclusion:** mechanical short-premium on single large-caps, priced at fair vol, is
**breakeven (PF 1.04)** with a brutal tail (one condor can lose ~87% of margin ≈ wipes
out ~15–20 winning credits). The premium-selling edge is real **only** when IV >
realized by ~15% — and that premium historically lives in **index** options (SPY/QQQ),
not single names. Two blockers, either of which is fatal at $700–1200:

1. **Capital floor:** a SPY/QQQ credit spread needs ~$1,500+ margin (SPY $776 × 100-share
   contract); a $700 account can only reach sub-$25 meme names, where the short-premium
   edge is already **proven dead** (wheel PF 0.72, −37% maxDD).
2. **Data gap:** we cannot verify any vol-premium edge without paid options bars.

**Verdict: NO-GO for small capital.** Revisit only after (a) a paid options-archive
backtest confirms an index-vol-premium edge, and (b) capital ≥ ~$5k so one SPY/QQQ
spread is ≤5% of the account.

## 4. Futures — seasonal commodities (post-deposit candidate, confirmed)

Confirmed from `EDGE_SWEEP.md`: commodity-only month-of-year seasonality **full PF 1.20,
OOS PF 1.23** (n=1360), cost-stable through 3-tick slippage (low-frequency, monthly
rebalance). Best names: HE, GC, PL, ZC, ZS (PF 1.6–2.1).

**Capital requirement (the blocker):** seasonal = **month-long overnight hold**. The
validated names are **full-size contracts**: GC ~$8–12k margin, PL ~$3–5k, ZC/ZS ~$2–3k,
HE ~$1.5–2k. Micro equivalents are limited (MGC gold ~$2–2.5k, no micro hogs/platinum)
and still **2–3× the $750 overnight cap**, let alone the $500 balance.

**Action:** post-deposit. Fund IBKR to **~$5–10k** (so a 2–4 micro/contract book can be
held overnight at ~1% risk), then paper-trade the seasonal sleeve. Not executable today.

## 5. Pairs / stat-arb — NO-GO for now

Z-score(2) mean-reversion on 10 liquid pairs (MA/V, CVX/XOM, JPM/BAC, BAC/C, JPM/GS,
NVDA/AMD, MSFT/ORCL, QCOM/TXN, AMAT/LRCX, AVGO/AMD): **PF 1.29 → 1.14 @10bps**, win 62%,
~+0.4%/trade after cost. Two blockers: (1) it is **market-neutral → requires a short leg**
(Robinhood cash account can't short; IBKR paper can, but that's not live), and (2) the
edge is thin and the universe is only ~10 pairs. Shelve until IBKR live + more capital.

## 6. Gap strategies — real but dominated

Gap-down fade (buy 2%+ gap-down, hold 5d): PF 1.34 → 1.26 @10bps, win 55%. Same-day
fade dies at cost (0.99 @10bps). This is the **same buy-the-dip exposure as RSI2-dip**
(which is stronger: PF 1.54 and fully walk-forward/regime-validated) — deploying both
double-bets weakness without adding diversification. Gap-up continuation (1.27 @0) is
largely long-equity drift, not a gap edge. **Not a separate deployment.**

---

## Cost-model note (why "cents/share" was dropped for single stocks)

Robinhood fractional trading is $0 commission; the honest cost is the spread → **bps per
side**. The legacy "cents/share" flat-cost grid is meaningless for individual stocks on
**split-adjusted** prices (a 20:1-split name shows 2008 prices in pennies, making 3¢/sh
look like 0.6–1.2% when the real 2008 cost was ~0.03%). bps is scale-invariant and is
the only cost dimension used for single-stock verdicts above. (For non-splitting ETFs
the cents grid remains valid — see `EQUITIES_SWEEP.md`.)

---

## Data gaps that block further validation (be explicit)

| Need | Status | What it unblocks |
|---|---|---|
| Historical **equity options bars** (IV surface) | **NOT in S3** (only futures chain metadata) | any honest credit-spread / condor verdict |
| Historical **near+far futures** term structure | expired contracts = Error 200 (paper) | true carry/term-structure test |
| **>5y IBKR futures bars** | index ~3y, rates ~16mo | cross-validating seasonal on a 2nd source |

All three require paid data or broker entitlements — none is fixable by the pending
backfill.

*No orders placed. No live trading. Paper-first per owner standard.*
