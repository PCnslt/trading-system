# Cross-Lane Edge Sweep — Consolidated Decision Doc

Date: 2026-08-15 · Owner review artifact · Research-only; every promotion below is
**PAPER SIGNAL-ONLY** (no live, nothing flips to real money).

This is the single decision doc the owner reviews. It consolidates the three lane
sweeps — futures (`EDGE_SWEEP.md`), crypto (`CRYPTO_SWEEP.md`), equities
(`EQUITIES_SWEEP.md`) — into one promote/hold/kill table, the cross-lane
convergence, the honest flags, and the final promote list.

## TL;DR

- Two edges converge ACROSS lanes and survive honest fills + cost stress:
  **RSI(2)<10 buy-the-dip** and **Donchian breakout**.
- Single strongest futures edge: **gold momentum (GC, Donchian + TSMOM)** —
  cross-source agreed, survives 3-tick slippage.
- Best crypto edge: **Donchian-20 + 200d-SMA filter** — but it is a **buy-and-hold
  proxy** (LOWEST live-priority).
- Equities Donchian is **regime-conditional**: a **200d-MA gate is mandatory**.
- Every promote below lands as a PAPER SIGNAL-ONLY pipeline. Real money untouched.

## Sweep verdicts (all three lanes)

### Futures — `EDGE_SWEEP.md` (2010→2026 yfinance × IBKR ~3y confirm)

| Family | Verdict | Why |
|---|---|---|
| Momentum (Donchian + TSMOM) | **KILL** (family) | Pooled PF 0.97 / OOS 0.97, net negative. Only gold survives. |
| Mean-reversion (RSI2 + BBand) | HOLD | Breakeven (0.99/1.02); thin OOS n, ~40% cross-source flips. |
| Carry (cross-sectional proxy) | **KILL** | OOS PF 0.85; proxy only (no term structure in S3). |
| Seasonal (commodity-only) | HOLD → promote pending | Best family (1.20/1.23) but needs ≥5y same-month → unconfirmable on ~3y IBKR. |
| **Gold momentum (GC Donchian + TSMOM)** | **PROMOTE** | Donchian 1.45 full / 1.81 OOS / 1.31 IB / 1.42 @3-tick; TSMOM 1.37 / 1.73 / 1.99 / 1.35 @3-tick. |

### Crypto — `CRYPTO_SWEEP.md` (BTC/ETH long-only spot, daily)

| Strategy | Verdict | Why |
|---|---|---|
| DONCHIAN_20 | PROMOTE | OOS PF 1.35 (n=107), fee25/slip25 1.64. |
| **DONCHIAN_20+200d** | **PROMOTE (best)** | OOS PF 1.50 (n=79), maxDD −44%, full cost grid ≥ 1.9. |
| MA_CROSS_50/200 | HOLD | too thin (OOS n=10). |
| TREND_200 | HOLD (buy-and-hold proxy) | OOS 5.0 but −73% maxDD, 25% win — regime artifact. |
| RSI2_DIP / BBAND_LOWER / ST_REVERSAL | **KILL** | mean-reversion dies at 10 bps/side. |
| hourly (all) | **KILL** | per-bar moves smaller than round-trip cost. |

### Equities — `EQUITIES_SWEEP.md` (15 ETFs/sectors, 1993→2026)

| Strategy | Verdict | Why |
|---|---|---|
| **RSI(2)<10 buy-the-dip** | **PROMOTE (champion)** | robust in BOTH regimes (SPY 2.22/1.92), OOS n≥94, survives 10 bps + 3¢/sh. |
| **Donchian 20d breakout** | **PROMOTE (regime-conditional)** | 2009+ PF 1.46 vs pre-2009 0.89 → 200d-MA gate mandatory. |
| 200d MA trend | HOLD | regime overlay, thin (OOS n=29). |
| Bollinger lower-band | HOLD | redundant with RSI2 (corr 0.72). |
| 5-day reversal | **KILL** | regime-flipped (died post-2009). |
| Golden cross | **KILL** | OOS n=4–7, statistically meaningless. |

## Cross-lane convergence

**RSI(2)<10 buy-the-dip** and **Donchian breakout** are the only two edges that
appear and survive across multiple lanes:

| Edge | Futures | Equities | Crypto |
|---|---|---|---|
| RSI2 buy-the-dip | HOLD (breakeven family; pockets CL·PL·SI·LE·ZO·ZM) | **PROMOTE (champion)** | KILL (dies at 10 bps spot cost) |
| Donchian breakout | **PROMOTE on GC** (elsewhere KILL) | **PROMOTE (200d-gated)** | **PROMOTE (best: +200d filter)** |

- **RSI2-dip is an equities edge** — deep, both-regime there; marginal elsewhere.
- **Donchian is the cross-market trend edge** — but every lane needs its own
  filter: futures → only GC survives; equities → 200d-MA regime gate; crypto →
  200d-SMA filter.
- Mean-reversion, carry, seasonal, golden-cross, and reversal families do NOT
  converge — they are lane-specific or dead.

## Honest flags (do not hide these)

1. **Equities Donchian is a bull-regime artifact.** Full-sample pooled PF 1.07;
   pre-2009 it LOSES (SPY 0.89, QQQ 0.74, DIA 0.70). Shipping it without the
   200d-MA gate = "long the 2009–2026 regime". The gate is mandatory, not optional.
2. **Crypto TREND_200 — and the 200d-filtered Donchian — is a buy-and-hold proxy.**
   The 200d SMA is a regime filter; the huge PF (OOS 5.0, 25% win, −73% maxDD) is
   "hold above the 200d SMA", not a repeatable short-term edge. Expect decay in a
   multi-year bear. Crypto stays **LOWEST live-priority** (owner distrusts it).
3. **Futures momentum is gold-only.** Family-level momentum is net-negative pooled;
   only GC agrees across yfinance + IBKR. Do not generalize to other metals/energy.
4. **Seasonal is the best futures family but unconfirmable** on ~3y IBKR bars (needs
   ≥5y same-month). Held, not promoted — revisit with a second long-history source.
5. **No real-time GC (metals) data** — COMEX/NYMEX L1 is DELAYED on paper. Signal-only
   is the correct first step; paper EXECUTION of GC would trade on delayed fills.

## Final promote list (all PAPER SIGNAL-ONLY — no live, no real money)

| Lane | Strategy | Pipeline | Flag |
|---|---|---|---|
| Futures | GC gold momentum (Donchian L/S + TSMOM) | `bot/gc_signals.py` (daily EOD) | none — strongest futures edge |
| Crypto | Donchian-20 + 200d-SMA (BTC/ETH) | `bot/crypto_paper.py` | buy-and-hold proxy; LOWEST live-priority |
| Equities | RSI2-dip + Donchian (200d-gated) | `bot/equity_signals.py` (existing) | Robinhood stays manual (laptop) |

Execution stays **NONE** for all three (`execution='NONE'`, no IBKR, no orders).
Real money is untouched. Paper EXECUTION (IBKR paper fills) remains gated behind
these signals + the index-LONG Gate 5 validation, and — for GC — a live-metals
data decision.
