# Missing Components — Robust Small-Scale Systematic Equity System

Audit of a live US-equities system (Robinhood execution, IBKR daily + 1-min bars,
long-only, ~$700 flexible capital, 1–20 day holds, one slow 20-day-momentum strategy +
sell-monitor + a market-regime light). The 9 components a serious systematic shop has
that this one lacks, each with: what / why / concrete implementability / cost.

---

## 1. Vol-scaled equal-risk position allocator (portfolio layer)

- **What:** Replace the flat %-of-equity position cap with inverse-volatility (ATR-scaled)
  sizing so every position carries equal, bounded risk: `shares = floor(risk_budget_usd /
  (k × ATR_n))`, rounded down to whole shares (whole shares are required for RH/IBKR stop
  protection). For a multi-position book, use **vol-targeted equal-risk (inverse-vol)
  weighting — NOT mean-variance optimization.**
- **Why:** A flat cap over-risks volatile names and under-risks quiet ones; vol-scaling is
  the first-order risk lever (Kaufman). Mean-variance optimizers are dominated out-of-sample
  by the naive 1/N portfolio once estimation error is accounted for (DeMiguel–Garlappi–Uppal
  2009) — a $700 book with 5 names has far too little covariance data to optimize weights.
- **Implement:** ATR(14) is already computed for the stop. Reuse it: `size = budget/(k·ATR14)`,
  `int()` down, skip `<1` share. ~15 lines of Python on existing IBKR daily bars.
- **Cost:** Free.
- **Sources:** DeMiguel, Garlappi & Uppal (2009), *Optimal Versus Naive Diversification*,
  RFS; Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, JFE (vol-scaled weighting);
  Kaufman, *Trading Systems and Methods* (volatility-adapted sizing).

## 2. Cross-position correlation / "one-bet" concentration test (risk)

- **What:** Before a new entry, compute trailing (60–126d) daily-return correlation of the
  candidate vs each current holding (bars already in S3/parquet); refuse or downsize when
  corr to an existing position exceeds a threshold (e.g. 0.7). Track a portfolio "effective
  N" = number of *distinct* exposures, not positions.
- **Why:** The book's biggest hidden risk is N positions that are all the same trade. Internal
  audit: RSI2 / RSI2PT / REV2 / Bollinger-dip all resolve to *one* exposure (long-only
  buy-the-dip beta) with a shared falling-knife mode and bear-year PFs of 0.36–0.81. A
  Bollinger dip-buy measured 0.69 daily-P&L correlation / 73% signal overlap with RSI2.
  Diversification only exists across *uncorrelated* bets (Moskowitz–Ooi–Pedersen 2012).
- **Implement:** `pandas` `.corr()` over the universe is a one-liner on data already
  collected; add a `max_corr` gate in the entry path; log a monthly correlation matrix.
- **Cost:** Free.
- **Sources:** Moskowitz, Ooi & Pedersen (2012); internal `trading-strategy-audit`
  "N lanes, M distinct exposures" concentration test.

## 3. Factor / risk attribution + benchmark (attribution)

- **What:** Decompose portfolio return into market beta + factor exposures + residual alpha,
  and benchmark against BOTH buy-and-hold SPY and a "buy any dip" (no-filter) baseline.
- **Why:** Long-only momentum/reversal is long-beta. Without attribution you cannot tell skill
  from drift — internal finding: any 2-day drop already returns +0.19–0.25% over 3 days
  (~58% win), so a threshold must beat the no-filter baseline to be called *signal*. The book
  must know when it is merely receiving the equity risk premium.
- **Implement:** Fama–French daily factor returns are **free** (Kenneth French's Dartmouth
  library, CSV). Regress daily live P&L on Mkt-RF (+ SMB/HML/UMD) with `numpy.linalg.lstsq`;
  report alpha, beta, R² monthly. ~30 lines.
- **Cost:** Free.
- **Sources:** Brinson, Hood & Beebower (1986), *Determinants of Portfolio Performance*;
  Fama & French (1993); internal drift-benchmark finding (`trading-backtest-validation`).

## 4. Hierarchical exposure limits (beyond a single position cap)

- **What:** A layered stack, not one cap: (a) per-name max (exists); (b) **portfolio heat
  cap** = Σ |entry−stop|·shares across ALL open positions; (c) per-sector (GICS) concentration
  cap; (d) gross exposure = Σ|notional|/equity; (e) a persistent daily-loss ledger with a
  hard halt.
- **Why:** A single position cap does not stop N correlated positions stacking into one
  oversized bet, or an entire book concentrated in one sector/factor. Heat + sector + gross
  caps bound total at-risk; the daily-loss ledger is the "never lose money" floor.
- **Implement:** `heat_cap_pct` already exists in `bot/risk.py` for the futures index lane —
  port it to the equities entry path. Sector = free GICS sector from yfinance `info` or the
  FMP profile already collected. Persist `open_risk_usd` per cycle.
- **Cost:** Free.
- **Sources:** internal `heat_cap_pct` (`docs/PROJECT-STATE.md`); Kaufman on portfolio heat;
  FINRA margin rules (concentration/forced-liquidation risk).

## 5. Live execution-cost measurement — TCA / implementation shortfall (execution)

- **What:** Measure real fill quality in the live loop instead of assuming a bp: capture the
  **arrival mid** (RH `get_equity_quotes` at decision time), then after fill compute
  implementation shortfall `(fill − arrival)/arrival` per side, log it per fill, roll up
  monthly. Add a **min-notional floor** that SKIPS trades whose measured round-trip cost
  exceeds the expected edge.
- **Why:** Cost is assumed (~5–12bp) but has structure — measured opening-sell leg ≈12bp vs
  closing-buy ≈2bp → ~14bp RTH round-trip, ~51bp extended-hours (3.4×). High-turnover edges
  die at these costs (single-name intraday reversal PF 0.89@5bp → 0.78@15bp). At ~$30
  notional, a $1 order cost ≈ 6.9% round-trip — a flat floor makes small trades structurally
  negative-EV.
- **Implement:** The `session-execution-cost-measurement` skill already runs a continuous L1/L2
  sampler (`rh_session_spread_cron.py`). Wire the arrival-mid + fill-price pair into the
  existing fill-confirm path and write a `TCA#`/cost column. ~20 lines on top of existing code.
- **Cost:** Free.
- **Sources:** Perold (1988), *The Implementation Shortfall: Paper Versus Reality*, JPM;
  Almgren & Chriss (2001), *Optimal Execution of Portfolio Transactions*, J. Risk;
  Novy-Marx & Velikov (2016), *A Taxonomy of Anomalies and Their Trading Costs*, RFS;
  internal measured cost structure.

## 6. Backtest-vs-live drift monitor (monitoring / process)

- **What:** A standing comparison of predicted vs realized: per-trade realized vs simulated
  slippage, and live P&L vs the backtest's expected P&L for the SAME signals. Alert when
  median live slippage exceeds the backtest assumption by a pre-set bp, or live PF diverges
  from simulated over a rolling window.
- **Why:** Every silent divergence (stale quote, venue difference, un-modeled cost,
  survivorship bias) shows up here first as *drift*, before it shows up as a loss. The
  backtest is only trustworthy if live reproduces its fill assumptions.
- **Implement:** The fill-confirm path already records real fill prices; store the backtest's
  per-signal expected fill (signal close + assumed slippage) and diff per trade; emit a monthly
  drift report + threshold alert, reusing the existing trade journal.
- **Cost:** Free.
- **Sources:** Perold (1988); internal `trading-track-record-audit` PAPER-vs-LIVE separation
  and `trading-backtest-validation` "paper must be executable" rule.

## 7. Kill-switch ledger (process)

- **What:** A real, auditable kill-switch: (a) **pre-committed, explicit halt conditions with
  thresholds** (daily-loss $, max consecutive losses, portfolio-heat breach, broker/gateway
  failure, market-wide circuit breaker); (b) a persistent `KILL#` ledger recording every
  halt/override/restart with {timestamp, trigger, action=flatten|halt, operator, reason,
  resume condition}; (c) periodic kill-switch **drills** (dry-run flatten + verify).
- **Why:** A kill-switch that isn't pre-committed, persisted, and drilled gets rationalized
  away in the moment. A `KILLED` control state exists, but there is no ledger of who halted,
  why, and when it is safe to resume — that ledger is the missing piece. Also: an env-var-only
  switch silently fails because systemd `Environment=` overrides `.env` (verified trap).
- **Implement:** A DynamoDB `KILLSWITCH#` table + a `killswitch.py` every bot/lane checks
  before entering; write a halt row on any trigger; monthly dry-run. ~40 lines.
- **Cost:** Free (DynamoDB already in use).
- **Sources:** Google SRE Book (runbooks + alerting); SEC/FINRA market-wide circuit breakers;
  internal `KILLED` control-state note (`docs/PROJECT-STATE.md`).

## 8. External dead-man's switch (monitoring)

- **What:** An **off-host** watchdog that alarms on the ABSENCE of the bot's heartbeat,
  independent of the bot's own success signals (ping healthchecks.io or a second host every N
  min; alert if no ping for X min). Heartbeat must be emitted from the critical trading path,
  not a helper thread.
- **Why:** Local watchdogs (systemd `WatchdogSec`, cron, the bot's own heartbeat) die with the
  host/scheduler. A VPS outage, partition, or deadlocked main loop produces SILENCE — no error
  — and silence reads as "ran flat, healthy" while positions sit unmanaged. Highest-leverage
  single monitoring gap.
- **Implement:** `curl -fsS -m 10 https://hc-ping.com/<uuid>` at the end of every bot cycle,
  plus a failure branch pinging an "unhealthy" URL. healthchecks.io free tier (20 checks).
  ~5 lines + a free account.
- **Cost:** Free.
- **Sources:** Google SRE Book, *Monitoring Distributed Systems* (alert on absence of signal);
  healthchecks.io.

## 9. Survivorship-bias-free universe + corporate-actions handling (data / process)

- **What:** Build the tradable universe from point-in-time membership (or at minimum FLAG that
  today's constituents back-applied through history silently excludes every delisted/bankrupt
  name), and handle splits, dividends, ticker changes, halts, and delistings.
- **Why:** The dominant defect across the research codebase: universe built from CURRENT
  S&P/Nasdaq listings back-applied 20y → delisted names are absent → all backtest numbers are
  UPPER bounds, worst for buy-the-dip (the names that fell to zero ARE the biggest losses).
  Splits/dividends on unadjusted data fire false signals; a held position force-liquidated by
  a merger leaves a phantom book row.
- **Implement:** For live, detect "sudden large gap" as a corporate-action trigger and
  re-derive entry/stop/qty on the ex-date; resolve symbols to CUSIP/FIGI and refresh daily.
  For backtests, label every result "survivorship-biased upper bound" until a point-in-time
  source is added.
- **Cost:** Free to flag + handle; the only **paid** item is a point-in-time data source
  (CRSP/Compustat, or a cheap vendor like Norgate/Sharadar).
- **Sources:** internal survivorship-bias audit (`trading-backtest-validation`); Alpaca
  Corporate Actions docs; McLean & Pontiff (2016) on the same bias in published anomalies.

---

## Priority order (account-size-aware)

At ~$700 the deliverable is a *verified track record*, not income ($700 × 20% = $140/yr).
Rank by leverage ÷ cost:

1. **#7 kill-switch ledger + #8 dead-man's switch** — process, near-zero cost, prevent the one
   catastrophic outcome (unmanaged positions).
2. **#1 vol-scaled sizing + #4 exposure limits + #2 correlation gate** — all free on existing
   data, bound total at-risk immediately.
3. **#5 TCA + #6 drift monitor** — execution/monitoring; convert assumed cost into measured cost.
4. **#3 factor attribution** — free data, tells you if the edge is beta.
5. **#9 survivorship-free data** — the only component that costs money; flag-and-caveat now,
   buy later if the edge survives the free fixes.
