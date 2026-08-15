# CRYPTO SWEEP — Momentum + Mean-Reversion Families (Lane B)

**Scope:** BTC & ETH, long-only spot. Historical backtest from `yf/crypto/` (daily + hourly),
forward/live context from Binance.US (`crypto-candles/` + `crypto-tick/`).
**Date:** 2026-08-15 · **Repo:** trading-system · **Research only — no orders, no IBKR, no live trading.**

---

## 1. What was tested

Two families, **long-only spot** (shorts require perp/futures — out of scope), swept on
BTC-USD and ETH-USD (pooled) at **daily** (primary) and **hourly** (secondary) bars.

| Family | Strategy | Entry (long) | Exit / stop |
|---|---|---|---|
| Momentum | `DONCHIAN_20` | close > prior 20d high | 2×ATR(14) GTC stop, 5d time stop, close < prior 20d low |
| Momentum | `DONCHIAN_20+200d` | Donchian breakout **and** close > 200d SMA | same as above |
| Momentum | `MA_CROSS_50/200` | 50d SMA crosses above 200d SMA | death cross (close) |
| Momentum | `TREND_200` | close > 200d SMA | close < 200d SMA |
| Mean-reversion | `RSI2_DIP` | RSI(2) < 10 | RSI(2) > 70 or 5d time stop |
| Mean-reversion | `BBAND_LOWER` | close < lower Bollinger(20, 2) | close ≥ 20d mid or 5d time stop |
| Mean-reversion | `ST_REVERSAL` | 3d return < −12% (panic dip) | 2×ATR GTC stop, close ≥ 5d SMA, 10d time stop |

## 2. Methodology — honest fills (Gate-1)

- **Entry** at signal-bar **close + adverse slippage** (long pays up). Bot computes at close, acts immediately.
- **GTC stop is INTRADAY**: next-bar `open < stop` → fill at open(+slip); `elif low ≤ stop` → fill at stop(+slip).
  Reported **alongside** the close-to-close stop model (§4) — the close model overstates the stop edge.
- **Close/time exits** fill at close(+slip). One entry OR exit per bar.
- **Cost model (Binance.US spot, no "tick" — bps):** round-trip **fee** grid 0/5/10/25 bps;
  **slippage** 0/5/10/25 bps **per side** (round-trip slip = 2×). Binance.US spot taker ≈ 10 bps round-trip.
- **PF / winrate are scale-invariant.** `net` and `maxDD` are the **simple sum of per-trade % returns**
  (each trade = 100% notional, un-compounded) — a sweep convention, not a compounded equity curve; a
  negative net or maxDD < −100% means the strategy bleeds capital net of the convention.
- **Walk-forward:** 40/20/40 train/validate/OOS split by entry date **+** 3 expanding-window rolling folds.
  `OOS PF` = pooled test trades; `OOS n` = test trade count.
- **Verdict rules:** promote ⇔ OOS PF ≥ 1.2 **and** realistic-slip PF ≥ 1.0 **and** OOS n ≥ 30;
  kill ⇔ OOS PF < 1.0 **or** 1-step PF < 1.0 **or** (OOS n < 30 with a weak PF);
  otherwise hold. **High PF but n < 30 = "too thin to promote", not kill.**
  - *realistic-slip PF* = PF at fee 10 bps × slip 10 bps/side (Binance.US taker + conservative slip).
  - *1-step PF* (analog of futures "1-tick") = PF at fee 5 bps × slip 5 bps/side.

## 3. Summary table — DAILY (pooled BTC-USD + ETH-USD, long-only)

Cost-PF cells are the **realistic (fee10/slip10)** and **stress (fee25/slip25)** grid corners;
full grid in §5.

| Family | Strategy | n | Win% | PF (0 cost) | maxDD | OOS PF | OOS n | PF @10/10 | PF @25/25 | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| Momentum | DONCHIAN_20 | 275 | 55% | 2.06 | −59% | 1.35 | 107 | 1.88 | 1.64 | **PROMOTE** |
| Momentum | **DONCHIAN_20+200d** | 201 | 60% | **2.35** | **−44%** | **1.50** | 79 | **2.16** | **1.89** | **PROMOTE (best)** |
| Momentum | MA_CROSS_50/200 | 18 | 61% | 22.55 | −70% | 2.03 | **10** | 22.26 | 21.79 | HOLD — too thin (n=10) |
| Momentum | TREND_200 | 59 | 25% | 20.77 | −73% | 5.00 | 32 | 19.53 | 17.93 | PROMOTE¹ |
| Mean-rev | RSI2_DIP | 403 | 63% | 1.08 | −204% | 1.12 | 197 | **0.98** | 0.84 | **KILL** (cost-fragile) |
| Mean-rev | BBAND_LOWER | 145 | 52% | 0.72 | −240% | 0.71 | 74 | 0.66 | 0.58 | **KILL** |
| Mean-rev | ST_REVERSAL | 140 | 59% | 1.00 | −217% | 0.85 | 43 | 0.93 | 0.83 | **KILL** |

¹ TREND_200 promotes by the letter of the rule (OOS 5.0, n=32, realistic-PF 19.5) **but is a buy-and-hold
proxy** (see §7 caveats) — treat as a regime filter, not a repeatable short-term edge.

**Headline:** momentum survives costs, mean-reversion does not. The 200d trend filter is a genuine
improvement on the Donchian breakout (PF 2.06→2.35, maxDD −59%→−44%, OOS 1.35→1.50), and every
mean-reversion variant is thinner than Binance.US spot round-trip costs.

### Per-asset detail (daily, ideal cost)

| Strategy | BTC-USD | | | | ETH-USD | | | |
|---|---|---|---|---|---|---|---|---|
| | n | PF | Win% | maxDD | n | PF | Win% | maxDD |
| DONCHIAN_20 | 172 | 1.95 | 55% | −49% | 103 | 2.22 | 55% | −42% |
| TREND_200 | 37 | 26.14 | 22% | −46% | 22 | 13.23 | 32% | −53% |
| RSI2_DIP | 235 | 1.26 | 64% | −66% | 168 | **0.93** | 61% | −163% |

RSI2-dip works on BTC (PF 1.26) but **loses on ETH (PF 0.93)** — the pooled 1.08 is entirely BTC-driven
and asset-fragile.

## 4. Stop-model honesty check (5 bps/side slip)

| Strategy (stop) | Intraday-GTC PF | Close-to-close PF |
|---|---|---|
| DONCHIAN_20 (daily) | 2.00 | 1.92 |
| ST_REVERSAL (daily) | 0.98 | 0.97 |
| DONCHIAN_20 (hourly) | 0.88 | 0.82 |

For a **long** crypto breakout the intraday GTC stop is *better* than the close model (fills at the stop
rather than below it on a falling bar), the reverse of the short-side pattern — the delta is small but the
honest number is the intraday one, which is what all headline figures use.

## 5. Cost-stress grid (DAILY, PF — fee ↓ × slippage-per-side →)

**DONCHIAN_20+200d** (best): the entire 16-cell grid holds PF ≥ 1.9.

| fee \ slip | 0 | 5 | 10 | 25 |
|---|---|---|---|---|
| 0 | 2.35 | 2.29 | 2.22 | 2.03 |
| 5 | 2.32 | 2.25 | 2.19 | 2.00 |
| 10 | 2.29 | 2.22 | 2.16 | 1.97 |
| 25 | 2.19 | 2.12 | 2.06 | 1.89 |

**RSI2_DIP** (representative mean-reversion — dies at realistic slip):

| fee \ slip | 0 | 5 | 10 | 25 |
|---|---|---|---|---|
| 0 | 1.08 | 1.05 | 1.01 | 0.92 |
| 5 | 1.06 | 1.03 | 1.00 | 0.90 |
| 10 | 1.05 | 1.01 | **0.98** | 0.88 |
| 25 | 1.00 | 0.96 | 0.93 | 0.84 |

(DONCHIAN_20 unfiltered: fee25/slip25 = 1.64; TREND_200: 17.93; MA_CROSS: 21.79 — all momentum cells ≥ 1.6.)

## 6. Hourly / intraday family (secondary — 2y of hourly bars)

Every hourly strategy is **below PF 1.0 at realistic cost** — per-bar moves are smaller than the 10–20 bps
round-trip, so the taker-fee spot account eats the edge:

| Strategy (hourly) | n | PF 0-cost | PF @5/5 | PF @10/10 | Verdict |
|---|---|---|---|---|---|
| DONCHIAN_20 | 1037 | 1.08 | 0.79 | 0.59 | KILL |
| MA_CROSS_50/200 | 115 | 1.13 | 1.05 | 0.99 | KILL |
| TREND_200 | 625 | 1.01 | 0.81 | 0.67 | KILL |
| RSI2_DIP | 1899 | 1.03 | 0.74 | 0.52 | KILL |
| BBAND_LOWER | 863 | 0.92 | 0.70 | 0.53 | KILL |
| ST_REVERSAL | 1 | 0.00 | — | — | KILL (threshold never fires: −12%/3h too tight) |

**Diagnosis (0-trade case):** hourly ST_REVERSAL fired 1 trade because a −12% move over 3 hourly bars is
extremely rare on BTC/ETH — the panic-dip entry needs a daily timeframe or a much looser threshold.
The intraday mean-reversion family is only viable on a **maker-rebate / zero-fee venue**, not Binance.US spot.

## 7. Verdicts per family

- **Momentum → PROMOTE.** The trend-following edge is real and cost-robust. `DONCHIAN_20+200d` is the
  best risk-adjusted candidate; the unfiltered Donchian is a close second (more trades, deeper drawdown).
  `TREND_200` and `MA_CROSS` confirm the direction (huge PF) but are slow, buy-and-hold-shaped, and
  `MA_CROSS` is too thin (n=10 OOS) to promote.
- **Mean-reversion → KILL.** RSI2-dip is marginal at 0 cost (PF 1.08, OOS 1.12) and falls below 1.0 at
  realistic 10 bps/side slippage; it only works on BTC (ETH PF 0.93). Bollinger-lower-band and
  short-term-reversal lose outright. Crypto MR per-trade moves are smaller than spot round-trip costs.

## 8. Top candidates (long-only spot)

1. **DONCHIAN 20d breakout + 200d-SMA trend filter** — full PF 2.35, OOS PF **1.50 (n=79)**, maxDD −44%,
   holds PF ≥ 1.9 across the full fee/slip grid. *Promote.*
2. **DONCHIAN 20d breakout (unfiltered)** — full PF 2.06, OOS PF 1.35 (n=107), maxDD −59%, fee25/slip25 PF 1.64. *Promote.*
3. **TREND_200 (200d regime)** — OOS PF 5.0 (n=32), but −73% maxDD, 25% win rate; a buy-and-hold proxy. *Promote with sizing caveats.*

## 9. Honest caveats

- **24/7 regime shifts.** The sample (BTC 2014→, ETH 2017→) contains three secular bulls (2017, 2020–21,
  2024–25). Momentum PF is inflated by regime; `TREND_200` is essentially "hold above the 200d SMA" and its
  5.0 OOS PF is a regime artifact, not a repeatable short-term signal. Expect decay in a multi-year bear.
- **Spot-only / long-only constraint.** All results are long-only. Shorts require perp/futures (out of scope),
  so the symmetry of the edge (does Donchian-SHORT also work?) is untested. A long-only spot book cannot
  monetize the short side of a mean-reversion dip.
- **Costs dominate crypto.** 10–20 bps round-trip is large relative to crypto per-bar moves — this is exactly
  why the hourly family and all of mean-reversion die. Any edge here is a *gross* PF ≥ ~1.2 before costs.
- **`net`/`maxDD` convention.** Reported as the sum of per-trade % returns (100% notional, un-compounded);
  not a compounded equity curve. Negative maxDD < −100% (mean-reversion rows) = cumulative losses exceed one
  full notional over the sample.
- **Pooled maxDD is sequential** (BTC then ETH trades ordered by date), not a concurrent two-leg book — the
  concurrent drawdown would differ slightly given BTC/ETH ~0.7–0.9 correlation.
- **SOL / XRP = no history / thin.** No `yf/crypto/` file exists for SOL or XRP; Binance.US has only ~2 days
  of candles (~$75.4 SOL, ~$1.00 XRP) and ~19 ticks each. **Cannot backtest — forward-only.** Any SOL/XRP edge
  claim would be untested.
- **Forward/live data is thin.** Binance.US `crypto-candles` holds 2 days, `crypto-tick` ~19 ticks/symbol —
  enough only to confirm price continuity with yfinance (BTC ~$63.0k, ETH ~$1.88k, matching the 2026-08-14
  yf daily close within ~0.1%), not to run a live validation.

## 10. Data sources

- `yf/crypto/BTC-USD.json` — daily 4350 bars (2014-09-17 → 2026-08-14), hourly 17487 bars (~2y).
- `yf/crypto/ETH-USD.json` — daily 3201 bars (2017-11-09 → 2026-08-14), hourly 17484 bars (~2y).
- `crypto-candles/{BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT}/2026-08-{14,15}.json` — Binance.US daily, 2 days.
- `crypto-tick/<sym>/2026/08/{14,15}/<ts>.json` — Binance.US spot ticks (~19/symbol).

*Generated by `/tmp/crypto_sweep.py` (sweep) + `/tmp/crypto_analysis.py` (variant + forward context); not committed.*
