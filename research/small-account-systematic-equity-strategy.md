# Small-Account Systematic Equity Strategy — Architecture Diagnosis & Correct Design

**Subject:** ~$700 account, long-only, fractional, 1-min + daily bars, ~5–12 bp/side cost,
ONE signal (RSI(2) < 5 oversold reversal), 2×ATR stop, 5-day exit, 1% risk / 15% position cap.

---

## 1. What the operator is doing WRONG (architecture, not code)

The single root defect: **this is not a strategy, it is one bet repeated.** Every layer of
"system" collapses into a single exposure — long-only buy-the-dip beta. It has no breadth,
no regime defense, no second leg, no honest validation, and an expectation that arithmetic
cannot support.

### 1.1 One signal = one correlated bet (no breadth)
- A single RSI(2)<5 condition is one trade, re-executed. Mean-reversion variants are highly
  correlated with each other. Internal audit: RSI2 / RSI2PT / REV2 / Bollinger-dip all resolve
  to *"one trade: long-only buy-the-dip beta"* with a shared falling-knife failure mode and
  bear-year PFs of **0.36 (2008) / 0.48–0.81 (2022)**. A Bollinger dip-buy measured
  **0.69 daily-P&L correlation / 73% signal overlap** with RSI2 — "same bet, not independent."
- Diversification is the only free lunch in portfolio construction (Moskowitz–Ooi–Pedersen
  2012: the Sharpe ratio comes from many *uncorrelated* signals/markets, not from one signal).

### 1.2 Long-only = long beta, not alpha (no second leg / no benchmark)
- Long-only mean reversion is **drift-inflated**. On 26y ES/NQ, *any* 2-day drop already
  returns +0.19–0.25% over 3 days (~58% win); the RSI/ATR threshold adds only ~+0.1%. The
  threshold must beat a **"buy any dip" (no-filter) baseline** to be called signal, or it is
  just the equity risk premium. The naive system has no such benchmark.
- No short leg, no market-neutral construction, no cash/defensive mode → full beta through
  every bear. "Buy the dip needs a bounce; it does not survive a slow bleed" (2018 PF 0.33).

### 1.3 No regime layer
- The system buys dips in *all* regimes, including grinding declines where long-only reversal
  loses (2022 PF ~0.5). The canonical Connors RSI(2) itself only bought dips **above the
  200-day MA** (Connors & Alvarez 2009) — the naive system dropped that filter.
- Caveat (empirical): a *lagging index-level* SMA200 gate FAILED on equities (made 2022 worse);
  the validated mitigation is **per-name close>SMA200 + satellite sizing + a bear-year warning
  flag**. "Regime filter" is not a one-line SMA — it must be tested as an A/B against no-gate.

### 1.4 RSI(2)<5 is an ultra-rare trigger → structurally un-validatable
- RSI(2)<5 fires very infrequently and clusters in crash events. A signal firing ~1×/month
  cannot reach n≥30 out-of-sample trades in reasonable time, and its P&L variance is enormous.
  The account cannot statistically distinguish skill from luck, and forward-testing is
  structurally impossible (a 10-session gate on a 1-signal/month edge is meaningless).

### 1.5 Cost is *assumed*, not *measured*
- 5–12 bp/side is a guess, and cost has **structure**: measured opening-sell leg ≈ 12 bp vs
  closing-buy leg ≈ 2 bp → **~14 bp RTH round-trip**, **51 bp extended-hours (3.4×)**.
  High-turnover mean reversion is cost-sensitive: single-name intraday reversal is NEGATIVE at
  these costs (PF 0.89 @5bp → 0.78 @15bp). At $700, any flat commission floor makes small
  positions structurally negative-EV (a ~$30 notional paying $1/order ≈ 6.9% round-trip).

### 1.6 No honest validation layer (the backtest, if any, is not evidence)
Documented defects that silently inflate results: **survivorship bias** (universe built from
*current* constituents back-applied 20y — worst for buy-the-dip, the names that fell to zero
are absent); **t-stat inflation** (per-trade t over correlated same-day trades); **OOS split
by symbol, not time**; ATR/look-ahead; no walk-forward; no deflated-Sharpe correction.
Worked example: RSI(14)<25 flat-by-close printed per-trade t≈8.7 → re-measured with
date-clustered t + honest 10bp cost + chronological OOS → **PF 0.75, t=−1.66 (NO-GO)**.

### 1.7 No benchmark, no drawdown/ruin analysis, no kill-switch
No comparison vs buy-and-hold SPY or "buy any dip"; no max-drawdown-first selection; no
live-vs-backtest drift monitor; no day-loss cap / kill-switch.

### 1.8 Expectation mismatch (the real error)
$700 × even a heroic 20% net = $140/yr ≈ $11.7/mo. The system is built to make money when the
only realistic deliverable at this size is a **verified track record** that could later justify
capital. Base rates: 97% of persistent day traders lose money (Chague–De-Losso–Giovannetti);
<1% of day traders persistently earn abnormal returns (Barber–Lee–Liu–Odean).

---

## 2. The CORRECT design — the layers

0. **Capital reality / expectation** — decide the goal is a *track record*, not income.
1. **Data** — survivorship-bias-free, point-in-time universe (CRSP/Compustat or reconstructed
   index membership) with delisting returns; split+dividend adjusted; broker data primary,
   free feeds break-glass only.
2. **Universe & liquidity** — liquid + executable *at the venue*; whole-share/fractional and
   overnight-tradability constraints applied to paper too; exclude names with earnings inside
   the hold window.
3. **Regime / trend filter** — empirically tested (per-name close>SMA200 + satellite sizing is
   the validated form); benchmark any gate against no-gate.
4. **Signal layer** — *multiple uncorrelated* signals (e.g. RSI2 dip-buy + short-term reversal
   REV2 + a breakout/TSMOM family — dip-buy and Donchian breakout are complementary, daily
   P&L corr ≈ 0); plus a pre-buy catalyst/news gate.
5. **Risk & portfolio** — ATR/vol-scaled sizing, correlation-aware position cap, portfolio heat
   limit, max-drawdown-first ranking; overnight risk = position SIZE (not stop tightness).
6. **Cost & execution** — measured time-of-day cost; minimum-notional floor that SKIPS
   negative-EV trades; enter in the venue's fillable window; whole-share vs fractional routing.
7. **Validation** — walk-forward 40/20/40 + rolling folds; date-clustered t-stats; deflated
   Sharpe (Bailey–López de Prado 2014); chronological OOS; cost-stress in bp/ticks; benchmark
   vs "buy any dip" and buy-and-hold; Monte Carlo/bootstrap for drawdown (bootstrap
   *understates* clustered drawdowns — report chronological maxDD too).
8. **Execution integrity & monitoring** — broker-truth reconciliation, never-naked guarantee,
   orphan-order sweep, live-vs-backtest drift, day-loss cap/kill-switch, accessible journal.

---

## 3. Realistic profit expectation

- **Arithmetic:** $700 × 20% net = **$140/year**. A realistic *good* systematic equity edge is
  ~5–15% annualized gross; on high-turnover long-only mean reversion, **net after real
  (measured) costs is typically breakeven to low single digits %**, with a negative tail in
  bear years. Internal live numbers: PF 1.36 @ 68% win on ~$105 positions ≈ **tens of dollars
  per month**.
- **Base rates:** 97% of persistent day traders lose money; 1.1% beat minimum wage
  (Chague et al.); individual investors underperform from turnover (Barber & Odean 2000);
  <1% of day traders persistently profitable (Barber–Lee–Liu–Odean 2014).
- **Honest framing:** do not expect to grow $700 meaningfully. Expect to (a) not lose it, and
  (b) build a verified, executable track record that justifies external capital later.

---

## 4. What to build FIRST (strict order)

1. **The honest backtest validator** — survivorship-free data + bar-by-bar fill model +
   cost-stress + walk-forward OOS + date-clustered t + "buy any dip" & buy-and-hold benchmark.
   This decides whether the edge exists at all. Nearly every naive edge dies here when honestly
   re-measured (VWAP 2σ → PF 0.82–1.08; single-name intraday reversal → negative; RSI14
   flat-by-close → NO-GO).
2. **Regime/trend filter** — tested as an A/B, not assumed.
3. **Second uncorrelated signal** (breadth) — only if it survives the same validator.
4. **Paper forward-test** with live-identical executability constraints.
5. **Tiny live size** — the first real fill is the project's first genuine information.

Order is validation → regime → breadth → paper → live. **Not** signal → live.

---

## 5. Sources

**External (public, verifiable):**
- Chague, F., De-Losso, R., & Giovannetti, B. (2020). "Day Trading for a Living?" SSRN WP
  (confirmed: 97% of day traders persisting >300 days lost money; 1.1% of 1,551 beat the
  Brazilian minimum wage).
- Barber, B. M., & Odean, T. (2000). "Trading Is Hazardous to Your Wealth…." *J. Finance*
  55(2), 773–806.
- Barber, B. M., Lee, Y.-T., Liu, Y.-J., & Odean, T. (2014). "The Cross-Section of Speculator
  Skill: Evidence from Day Trading." *J. Financial Markets* 18, 1–24.
- Connors, L., & Alvarez, C. (2009). *Short Term Trading Strategies That Work*. TradingMarkets
  (RSI(2) long above the 200-day MA, exit on close > 5-day MA).
- Jegadeesh, N. (1990). *J. Finance* 45(3), 881–898; Lehmann, B. (1990). *QJE* 105(1), 1–28;
  Lo, A., & MacKinlay, A. C. (1990). *Rev. Fin. Studies* 3(2), 175–205 (short-term reversal).
- Bailey, D. H., & López de Prado, M. (2014). "The Deflated Sharpe Ratio…." *J. Portfolio
  Mgmt* 40(5), 94–107.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- Chan, E. (2009). *Quantitative Trading*; (2013) *Algorithmic Trading*. Wiley.
- Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). "Time Series Momentum."
  *J. Financial Economics* 104(2), 228–250.

**Internal (verified 2026-08, cite the skill/repo artifacts):**
- `trading-strategy-audit` (+ `docs/STRATEGY_PORTFOLIO.md`): "N lanes, M distinct exposures"
  concentration test; bear-year PF table.
- `trading-backtest-validation`: survivorship-bias audit, t-stat inflation, measured cost
  structure (14 bp RTH / 51 bp ext), RSI14 flat-by-close NO-GO re-measurement, "buy any dip"
  drift benchmark, "buy the dip needs a bounce".
- `live-execution-integrity`: whole-share vs fractional, commission floors, sizing off real
  equity, never-naked, orphan-order sweep.
