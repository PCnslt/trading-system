# The Missing Algorithmic-Trading Framework (Canonical Books)

Context: ~$700 Robinhood account, single RSI2/RSI14 mean-reversion signal in isolation,
naive backtests. Below is the four-pillar framework the canonical literature says is
missing, with book/chapter citations and concrete actions sized to a small account.

## Meta-diagnosis (why the single-signal backtests fail)
A single mean-reversion indicator is not a trading *system*. The canonical books treat
a live system as: signal → position sizing (vol targeting) → portfolio construction →
risk overlay → execution. The operator has only 20% of the chain (signal), and mean
reversion (RSI2) is the *most cost-sensitive* style — high turnover, small edge per
trade. On $700 the edge dies in costs unless sizing/portfolio/risk/execution are right.

---

## 1. PORTFOLIO CONSTRUCTION — "diversification is the only free lunch"
**Missing:** one signal = one bet = uncompensated idiosyncratic risk and huge drawdown
variance. The books are unanimous: trade a *portfolio* of weakly-correlated systems/assets.

- **Markowitz (1952), "Portfolio Selection," J. Finance** — theoretical basis: combine
  uncorrelated return streams; portfolio vol < weighted avg vol.
- **Carver, *Systematic Trading* (2015) — "portfolio construction" chapter** — a basket of
  10–20 mediocre, uncorrelated systems beats one "good" one. "Handcrafting" = inverse-vol /
  correlation-weighted allocation (a practical risk-parity).
- **López de Prado, *Advances in Financial ML* (2018), Ch 16 (portfolio construction /
  Hierarchical Risk Parity)** — use correlation structure (not raw weights) to avoid
  concentrated clusters.
- **Clenow, *Stocks on the Move* (2015)** — rank a diversified universe (momentum), cap
  per-name and per-sector exposure.

**Actionable ($700):** run RSI2 mean-reversion across **6–10 liquid, uncorrelated names/ETFs
(mix sectors + a bond ETF)**, equal-risk weighted, instead of one ticker. 10 positions × ~$70
fractional shares on Robinhood is feasible. Add at least one *orthogonal* signal family
(e.g., trend/momentum) so you're not 100% short-vol mean-reversion (mean reversion blows up
in trending/crash regimes — see Chan below).

---

## 2. VOL TARGETING / POSITION SIZING — "size, not entry, is the edge"
**Missing:** fixed dollar or fixed share sizing ignores that volatility differs per name and
per regime. Canonical rule: invert position size against volatility so every bet carries
equal risk.

- **Carver, *Systematic Trading* — "position sizing" chapter; *Leveraged Trading* (2019) —
  vol-targeting chapters** — the core formula: position size ∝ (target risk % × equity) /
  instrument volatility. Target a fixed annualized vol per position (e.g., 0.5–1% of equity
  risk per position), and re-size down when realized vol rises above target (vol bands).
- **Clenow, *Following the Trend* (2012) — position-sizing chapter** — ATR-based:
  `shares = (equity × risk%) / (ATR × stop_multiple)`, with risk% ≈ 0.5–1% per trade.
- **Chan, *Algorithmic Trading* (2013) Ch 6 / *Quantitative Trading* (2008) Ch 6 — money &
  risk mgmt** — position size is where leverage/risk is controlled; signal only sets direction.

**Actionable ($700):**
```
shares = ($700 × 0.005) / (2 × ATR14)     # risk $3.50 per position
```
Vol-target the *portfolio*: scale total exposure so realized daily vol ≈ your target
(e.g., 1%/day). Never let a single RSI signal size itself — that's the operator's core bug.

---

## 3. RISK OVERLAY — "survive first, optimize second"
**Missing:** no stop, no drawdown circuit breaker, no correlation limit, no sizing via
expectancy. The overlay is a *separate layer* on top of the signal.

- **Tharp, *Trade Your Way to Financial Freedom* (2nd ed 2006) — position sizing & R-multiples** —
  express every trade in **R** (risk units); manage expectancy and SQN (System Quality Number),
  not win rate.
- **Chan, *Quantitative Trading* Ch 6; *Algorithmic Trading* Ch 6** — Kelly criterion and
  **fractional Kelly**; cap leverage; stop-losses; max drawdown budgets.
- **Kelly (1956) / Thorp–Ziemba** — `f* = (p·b − q)/b`; in practice bet **¼–½ Kelly** because
  inputs are estimates with error (full Kelly ≈ overbetting ≈ ruin).
- **López de Prado, *AFML* Ch 10 (bet sizing)** — dynamic bet size with drawdown constraints;
  **Ch 13 (backtest statistics — PSR, Deflated Sharpe)** — require the strategy to pass
  statistical-significance bars before risking capital.
- **Kestner, *Quantitative Trading Strategies* (2003)** — expectancy, Sharpe, K-ratio;
  drawdown as a first-class risk metric.
- **Carver, *Leveraged Trading* — risk-overlay chapter** — pre-committed drawdown thresholds
  that *mechanically de-lever* the book (e.g., cut positions 50% at −10%, flat at −20%).

**Actionable ($700) — hard limits, computed up front:**
- Per-trade stop: 2–3 × ATR14 (mean reversion needs a stop or it becomes "catching knives").
- Position risk: ≤ 0.5–1% equity/trade ($3.50–$7.00).
- Gross exposure: ≤ 50% (rest cash as the implicit short-vol buffer).
- Daily loss limit: −2%/day → stop trading the day.
- Circuit breaker: −20% equity → halt, revalidate (no revenge trading).
- Sector cap: ≤ 20% per sector.
- Bet ¼–½ Kelly from *measured* expectancy, not backtest-optimized expectancy.

---

## 4. EXECUTION — "the backtest number isn't the real number"
**Missing:** backtests that ignore spread, slippage, and market impact overstate mean-
reversion edges by exactly the amount that kills them live. Measure the gap explicitly.

- **Perold (1988), "The Implementation Shortfall: Paper Versus Reality," J. Portfolio Mgmt** —
  canonical benchmark: implementation shortfall = paper return − real return (the sum of
  explicit costs + slippage + opportunity cost).
- **Johnson, *Algorithmic Trading and DMA* (2010)** — order types (limit vs market), market
  impact, VWAP/TWAP schedules, liquidity.
- **López de Prado, *AFML* Ch 19 (market microstructure) & Ch 20 (execution strategies)** —
  urgency, participation rate, impact models; don't trade size > ~1% of ADV.
- **Chan, *Quantitative Trading* Ch 5 (execution systems)** — use **limit orders**, automate
  order management, avoid market orders at the open/close; respect bid-ask and slippage.
- **Kissell, *The Science of Algorithmic Trading & Portfolio Mgmt* (2013)** — execution algos.

**Actionable ($700):**
- Trade only names/ETFs with **ADV ≥ $20M and spread ≤ ~5 bps**; pass your trade size through
  a `size < 1% of ADV` filter.
- **Limit orders only** for mean reversion (you're paid to provide liquidity — a market order
  hands the edge to the counterparty). Post at/near the bid on entry, take profit at limit.
- Backtest with **realistic costs included**: spread + slippage + (any fees) ≥ 5–10 bps/side.
  If the net edge doesn't survive that, the strategy is dead before it starts.
- Track implementation shortfall every fill vs. the mid at signal time.

---

## Backtest integrity (fix this BEFORE trusting any of the above)
The operator's "backtests just revealed..." is the tell: naive backtests on one indicator are
almost always overfit. Canonical guardrails:

- **Chan, *Quantitative Trading* Ch 3 (backtesting)** — out-of-sample, walk-forward, paper
  trading before capital; transaction costs in the loop.
- **López de Prado, *AFML* Ch 7 (purged / combinatorial CV)** — prevent leakage; **Ch 12
  (backtesting through simulation) & Ch 13 (PSR / Deflated Sharpe)** — require significance,
  penalize multiple testing.

**Actionable:** walk-forward the RSI2 params (don't optimize on the full history); split
in-sample / out-of-sample; report Deflated Sharpe + max drawdown + turnover; then paper-trade
the exact overlay above for ≥ 20–30 trades before going live.

---

## Priority order for a $700 account
1. **Risk overlay** (Tharp/Chan) — stops + position cap + drawdown breaker; survival first.
2. **Execution model** (Perold/Johnson) — limit orders + ADV/spread filter + costs in backtest.
3. **Vol targeting** (Carver/Clenow) — equal-risk sizing; stop fixed-dollar sizing.
4. **Portfolio construction** (Markowitz/Carver/López de Prado) — 6–10 uncorrelated names,
   add a non-mean-reversion sleeve.

### Books (canonical editions)
- Carver, *Systematic Trading* (2015) & *Leveraged Trading* (2019), Harriman House.
- Clenow, *Following the Trend* (2012) & *Stocks on the Move* (2015), Wiley.
- Chan, *Quantitative Trading* (2008; 2nd ed 2021) & *Algorithmic Trading* (2013), Wiley.
- López de Prado, *Advances in Financial Machine Learning* (2018), Wiley.
- Johnson, *Algorithmic Trading and DMA* (2010).
- Kissell, *The Science of Algorithmic Trading and Portfolio Management* (2013).
- Tharp, *Trade Your Way to Financial Freedom* (2nd ed 2006).
- Kestner, *Quantitative Trading Strategies* (2003).
- Kaufman, *Trading Systems and Methods* (6th ed) — reference for stops/sizing.
- Papers: Markowitz (1952); Kelly (1956); Perold (1988).
