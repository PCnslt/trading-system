# Robinhood Lane Plan — RSI(2) Buy-the-Dip (fractional-share execution spec)

**Date:** 2026-08-16 · **Author:** VPS Hermes (builder) · **Status:** READY-TO-IMPLEMENT
(paper first) · **Executes on:** LAPTOP Robinhood "Agentic" account (this file is a
spec — the VPS does NOT place Robinhood orders).

**Target capital:** ~$700 Robinhood · **Instrument:** long-only equities via
fractional shares ($0 commission) · **Objective (owner 2026-08-16):** CAPITAL
PRESERVATION first — drawdown-first, validated edges only.

This is the deployable spec for the strategy already validated as the **RSI2 champion**
in `EQUITIES_SWEEP.md` (ETFs/sectors) and re-confirmed on individual large-caps in the
`stock_mr_*` sweep (50 S&P100 names, 2006–2026). Nothing here is untested; every number
below is from a backtest with honest fills + cost stress.

---

## 1. Ticker universe (liquidity rule, NOT past-return cherry-picking)

Two sleeves, both long-only:

| Sleeve | Universe | Count | Selection rule |
|---|---|---|---|
| **A — ETFs** | SPY, QQQ, IWM, DIA, VTI, XLF, XLK, XLV, XLP, XLI | 10 | fixed (already validated; avoid XLE/XLB/XLU/XLRE — KILL) |
| **B — Large-caps** | S&P100 constituents ranked by 20-day avg dollar volume | top-50 | top-50 by `20d avg $volume`; recompute monthly |

- **Selection rule is liquidity, not returns.** The 50-name stock universe = S&P100
  top-50 by 20d average dollar volume (deterministic; see `research/stock_mr_fetch.py`).
- Recompute the liquidity rank **monthly**; drop any name that falls out of the top-50
  or delists (survivorship-aware), add the newcomer. Never add a name because it
  "looks cheap."
- At $700 fractional, sleeve B is the primary workhorse (more signals, more
  diversification than 10 ETFs); sleeve A is the low-maintenance core.

## 2. Entry rule (precise)

- **Indicator:** Wilder RSI(2) on daily close, `EWM alpha = 1/2` (standard Wilder):
  `gain = max(close - prev_close, 0)`, `loss = max(prev_close - close, 0)`,
  `avg_gain = EWM(gain, alpha=1/2)`, `avg_loss = EWM(loss, alpha=1/2)`,
  `RSI2 = 100 - 100/(1 + avg_gain/avg_loss)`.
- **Trend filter (mandatory):** `close > SMA200` (Connors-style). Entry is only valid
  when the 200-day moving average is defined and the close is above it. This removes
  falling-knife entries in bear regimes and materially cuts drawdown (ES/NQ: PF
  1.99→2.15, maxDD −$42.3k→−$22.1k on the 200d-filter adoption).
- **Trigger:** `RSI(2) < threshold`. **Threshold = 5** (primary). The two validated
  alternatives are `RSI(2) < 2` (more selective, higher PF — walk-forward OOS 1.47)
  and `RSI(2) < 10` (loosest; matches the original ETF champion). For a $700 account
  wanting selectivity and fewer concurrent positions, **use `< 5`**; switch to `< 2`
  if you want ~40% fewer, higher-conviction trades.
- **Fill:** compute signal at the daily **close**, enter at the **next session open**
  (conservative; no lookahead). On Robinhood place a market order at the open or a
  marketable limit. Do NOT chase intraday.

## 3. Exit rules (priority order — checked every bar)

1. **Hard stop:** `2 × ATR(14)` below entry, **intraday GTC gap-aware**:
   - if next open gaps **through** the stop → fill at the open;
   - elif low ≤ stop → fill at the stop.
   (Wilder ATR(14) = `EWM(TR, alpha=1/14)`.)
2. **Time stop:** 5 trading days (force-close at the 5th close if nothing else fired).
3. **Revert / overbought:** `close > SMA(5)` **OR** `RSI(2) > 70` → close the position.

- **Max hold = 5 trading days** (hard cap). Avg realized hold ≈ 2.1 days (stocks) /
  3.6 days (SPY).
- **Trailing stop: REJECTED — do not add one.** A tighten-only `1×ATR` ratchet was
  tested: it raised stop-outs 17.5%→34.8%, converted winners into early stops, and
  **lowered** PF (1.54→1.50 full, 1.44→1.39 @5bps). Fixed 2×ATR stop only.
- One open position per symbol (no pyramiding).

## 4. Validated numbers (honest fills + cost stress)

**Cost model = Robinhood reality:** $0 commission, fractional shares. The real cost is
the bid/ask spread → model **bps per side** {2, 5, 10}. (The legacy "cents/share" grid
is **not applicable** to fractional $0-comm trading and is meaningless on split-adjusted
single-stock prices — see `SMALL_CAPITAL_OPPORTUNITIES.md` §cost note.)

### 4a. ETF sleeve (from EQUITIES_SWEEP, RSI2<10, no-hard-stop variant)

| sym | full PF | OOS PF (n) | win | hold | 10bps PF | verdict |
|---|---|---|---|---|---|---|
| SPY | 2.00 | 2.04 (122) | 70% | 3.6d | 1.62 | PROMOTE |
| QQQ | 1.84 | 2.08 (94) | — | — | 1.74 | PROMOTE |
| VTI | 1.91 | 2.82 (95) | — | — | — | PROMOTE |
| XLF | 1.61 | 1.52 (108) | — | — | 1.29 @3¢ | PROMOTE |
| pooled (15) | 1.40 | 1.36 (1505) | — | — | — | PROMOTE |

- SPY regime split: **2.22** (1993–2008) / **1.92** (2009–2026) — robust in BOTH regimes.
- SPY maxDD ≈ −$103/sh OOS (≈ −13% of notional), rolling folds 2.48/1.74/1.97.

### 4b. Large-cap sleeve (stock_mr sweep, 50 S&P100, 2×ATR hard stop + SMA200 gate)

| threshold | full PF (n) | win | avg hold | 5bps PF | 10bps PF |
|---|---|---|---|---|---|
| RSI2 < 2 | 1.54 (3064) | 67.5% | 2.1d | 1.44 | 1.36 |
| RSI2 < 5 | 1.42 (7955) | 67.1% | 2.1d | 1.32 | 1.24 |
| RSI2 < 10 | 1.31 (15074) | 66.2% | 2.1d | 1.21 | 1.14 |

- **Walk-forward (threshold chosen from train only, expanding folds):** pooled OOS
  **PF 1.47** (n=1321) @0bps, **1.36** @5bps, **1.26** @10bps. All 5 folds positive
  (1.21 / 1.14 / 3.04 / 1.27 / 1.48 @0bps).
- **Regime (thr=5):** pre-GFC 1.65 · GFC 1.40 · bull-grind 1.40 · COVID+bear 1.14 ·
  bull-2023-25 1.33 — **positive in every regime, including 2008 and 2020-22.**
- **Worst single trade −37.9%** (a gap-through-the-stop event on a single name). This
  is why per-name position sizing (below) is the actual risk control, not the stop.

## 5. Position sizing (capital-preservation control)

- **Max 5% of account per name** (≈ $35 at $700), regardless of stop distance.
- **Target 10–20 concurrent names.** With ~20 names, the −37.9% worst-case single-name
  gap becomes a ≤ −1.9% portfolio event.
- Per-trade risk ≈ 1% (owner spec): choose $ per name = `0.01 × capital / stop_pct`
  **capped** at 5% of capital. A 2×ATR stop is typically 4–8% away, so the cap binds.
- This is a **basket** strategy, not a single-bet strategy. Its edge is the 67–70%
  win rate across many independent dip events.

## 6. Donchian(200d) variant (secondary, regime-gated)

Same universe. Deploy **only after** the RSI2 sleeve, and only as a diversifier
(0.06 daily-$ correlation with RSI2 — genuinely independent).

- **Indicator:** prior 20-day high = `max(High[-20:-1])` (shifted, excludes today).
- **Entry:** `close > prior 20d high` **AND** `close > SMA200` (the gate is mandatory —
  the raw breakout lost money 1993–2008).
- **Stop:** fixed `2 × ATR(14)` GTC, intraday gap-aware.
- **Exit:** `close < prior 20d low` **OR** 5-day time stop **OR** stop hit.
- **Numbers (SPY ETF):** full PF 1.32 · OOS PF 1.50 (n=155) · win 57% · 10bps PF 1.05
  (thin margin) · regime 0.89 (pre-2009) / 1.46 (post-2009).
- **Use ETFs only for Donchian.** Individual-stock 20d breakouts are weak
  (PF 1.18 → 1.04 @10bps pooled — too noisy); the edge lives in the index-level trend.

## 7. What NOT to deploy (from this sweep)

- **5-day reversal** — regime-flipped (2.93 → 0.94 post-2009). KILL.
- **Golden cross / 200d-MA as a standalone signal** — n=4–7 OOS, meaningless. HOLD as
  filter only.
- **Bollinger lower-band** — 0.72 corr with RSI2, redundant. Do not co-deploy.
- **Trailing stop** — tested, lowers PF. See §3.

## 8. Implementation checklist (laptop side)

1. Signal cron: at market close compute RSI2 + SMA200 + ATR14 for the 50-name +
   10-ETF universe (or pull from `bot/equity_signals.py` on the VPS).
2. For each name where `RSI2<5 and close>SMA200` and no open position: place a
   fractional market order at next open, $ = min(5% capital, 1%/stop_pct).
3. Attach the stop/exit logic: check daily for 2×ATR stop / 5-day cap / revert exit.
4. **Paper-trade ≥ 30 days first** (owner standard: no live orders until an edge is
   trusted). Track drawdown-first (maxDD → worst trade → losing streak).
5. Do not co-deploy Bollinger or 5-day reversal with RSI2.

*No orders placed by the VPS. No live trading. This is a spec + validation summary.*
