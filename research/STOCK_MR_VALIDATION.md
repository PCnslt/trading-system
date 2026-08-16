# Stock Mean-Reversion Validation — Connors RSI(2) on Liquid Large-Caps

**Date:** 2026-08-16 · **Owner:** Robinhood lane (~$700, fractional, $0 commission)
**Scope:** validation only — NO live orders wired.

## TL;DR (honest verdict)

| Question | Answer |
|---|---|
| Is the edge real? | **Yes.** PF 1.54 full-sample / 1.47 OOS at thr=2, 67.5% win rate, 2-day holds. |
| Survives costs? | **Yes.** PF 1.44 @5bps, 1.35 @10bps (full); 1.36 @5bps OOS. |
| Data-mined? | **No.** Walk-forward threshold selection (train-only) is stable → always thr=2; OOS decay only −4.7% relative. |
| Concentrated in 2023–25 bull? | **No.** Edge positive across 1963–2026; **weakest in bear markets** (2008 PF 0.36, 2022 0.81). |
| Concentrated in a few mega-caps? | **No.** 40–42 of 50 names profitable (PF>1). |
| Fits "never lose money" directive? | **Not standalone.** Deep bear drawdowns, 9/11-style gap-through tail risk (−37.9% single trade), 18-trade losing streak. |

**Recommendation:** legitimate small-ticket candidate, but deploy as a **sized-down satellite** with a market-regime guard — not as a capital-preservation core. Use **thr=2 + fixed 2×ATR stop** (trailing hurts). Keep costs ≤5bps.

---

## 1. Method (anti-data-mining)

- **Fixed universe:** S&P 100 constituents (Wikipedia) ranked by **avg dollar volume
  (20d)** from the data engine's daily metrics; top 50, dropping `GOOG` (Alphabet
  dual-class, keep `GOOGL`) → 50 names. Selection is a liquidity rule, **not** past returns.
- **Data:** yfinance daily, **split+dividend adjusted** (total return), 1962→2026
  (name-dependent). Primary source per the equities-lane convention.
- **Strategy (Connors classic, long-only):**
  - Entry: `RSI(2) < thr` AND `close > SMA200`, thr ∈ {2,5,10}; **fill at next bar's
    OPEN** (no lookahead — signal is computed at close, you cannot buy at that close).
  - Exit priority: **hard stop 2×ATR (intraday GTC, gap-aware)** → **5-day time stop**
    → **revert (close > SMA5) or RSI(2) > 70**.
  - Variant: **trailing** tighten-only ratchet (`highest_close − 1×ATR`) vs fixed stop.
- **Cost model:** $0 commission + spread, applied **per side** in bps {0, 5, 10}.
  Entry pays up, exit pays down; stop fill pays the adverse direction.
- **Walk-forward:** 5 expanding folds (2006–10, 2010–14, 2014–18, 2018–22, 2022–26).
  Threshold chosen **from the train window only** (no-feedback rule), then applied to
  the untouched test window. Trades bucketed by entry date (run once, no re-slicing).

## 2. Full-sample threshold sweep (fixed stop)

| thr | PF @0bps | PF @5bps | PF @10bps | win% (5bps) | trades | avg hold |
|----:|---------:|---------:|----------:|------------:|-------:|---------:|
| 2  | 1.543    | 1.441    | 1.345     | 66.3%       | 3,064  | 2.05 d   |
| 5  | 1.418    | 1.319    | 1.226     | 65.6%       | 7,955  | 2.10 d   |
| 10 | 1.305    | 1.211    | 1.122     | 64.7%       | 15,074 | 2.13 d   |

Monotone: **thr=2 is strictly best**; the edge survives 10 bps at every threshold
(PF stays > 1.0). The laptop's sanity number (PF 1.29 IS / 1.17 OOS) is the same
direction — the rigorous run is stronger (1.54 / 1.47 at thr=2), so the laptop
backtest was conservative, not inflated.

## 3. Walk-forward OOS (threshold selected from train only)

Train PF ranked **thr=2 > 5 > 10 in every fold** (stable, not noise), so thr=2 was
selected 5/5 times.

| Fold (test) | OOS PF @0bps | OOS PF @5bps | OOS n |
|---|---:|---:|---:|
| 2006–10 | 1.211 | 1.125 | 208 |
| 2010–14 | 1.144 | 1.052 | 248 |
| 2014–18 | 3.040 | 2.777 | 270 |
| 2018–22 | 1.267 | 1.182 | 291 |
| 2022–26 | 1.484 | 1.382 | 304 |
| **Pooled** | **1.471** | **1.364** | **1,321** |

- **Pooled OOS @10bps = 1.262**, win 69.3%, avg hold 2.08 d.
- **OOS decay** vs full-sample: 1.543 → 1.471 (0bps) = **−4.7% relative**; at 5 bps
  1.441 → 1.364. Minimal decay — the edge is not an in-sample artifact.
- Fold fragility: 2010–14 is the weak spot (PF 1.05 @5bps — shallow-dip bull gave
  mean-reversion little to exploit), but every fold is >1.0.

## 4. Regime / concentration honesty

**Regime split (thr=5, fixed, pooled):**

| Regime | PF @0bps | PF @5bps | n |
|---|---:|---:|---:|
| pre-GFC 2000–07 | 1.65 | 1.55 | 1,077 |
| GFC 2008–09 | 1.40 | 1.31 | 224 |
| bull-grind 2010–19 | 1.40 | 1.28 | 1,827 |
| COVID + bear 2020–22 | 1.14 | **1.06** | 541 |
| bull 2023–25 | 1.33 | 1.23 | 618 |

**The edge is NOT a 2023–25 bull artifact — it is weakest in bear/choppy regimes.**
Per-year PF (thr=2) confirms: worst years are 1966 (0.29), 2008 (0.36), 1977–79
(≤0.71), 2018 (0.80), 2022 (0.81). 2023 is merely 1.07. This matches the known
RSI2-dip pattern: dips **inside an uptrend** mean-revert; dips in a breakdown keep
falling.

**Concentration:** thr=2 → 40/50 symbols profitable (PF>1); thr=5 → 42/50. The edge
is **broad**, not a few mega-caps. (The very highest per-symbol PF — GEV, UBER, PLTR,
META — are short-history names measured only inside the 2023–25 bull; treat those as
regime-inflated, not as the source of the edge. Long-history names like XOM 2.21,
PG 2.21, IBM 2.37, KO 1.30, JNJ 1.32 are the durable core.)

## 5. Trailing stop: **fails** — use fixed

| thr | fixed PF (5bps) | trail PF (5bps) | fixed win% | trail win% | stop-out rate |
|----:|---:|---:|---:|---:|---:|
| 2 | 1.441 | 1.389 | 66.3% | 59.3% | 17.5% → 34.8% |
| 5 | 1.319 | 1.269 | 65.6% | 59.0% | 17.7% → 34.7% |
| 10 | 1.211 | 1.174 | 64.7% | 58.4% | 17.7% → 34.9% |

The 1×ATR ratchet **doubles stop-outs and cuts winners before the ~2-day reversion
completes** (avg hold 2.05 → 1.62 d). It is *not* an inert trail — it changes exits —
and it changes them for the worse. Ship the fixed 2×ATR stop.

## 6. Drawdown-first (capital-preservation lens)

| Metric (thr=2, fixed) | Value |
|---|---|
| Worst single trade | **−37.9%** (BKNG/Priceline, 9/11 gap through stop) |
| Other tail gaps | HD 1984 −22.9%, AMZN 1998 −18.9%, ORCL 1987 −17.5% (Black Monday), CRM 2024 −16.7% |
| Longest losing streak | **18** (thr=2) / **29** (thr=5) |
| Portfolio maxDD (compounded, equal-weight) | −57.9% @0bps / −59.3% @5bps / −69.4% @10bps |
| Portfolio maxDD, thr=5 | −58.8% / −71.7% / −83.3% |

The worst trade is a **real gap-through** (9/11), not a data glitch: the 2×ATR stop
cannot protect against an overnight gap, and this is the single biggest tail risk for
a "never-lose-money" mandate. Compounded maxDD is deep because signals **cluster
during crashes** (many simultaneous dip-buys all lose together). thr=2 is markedly
safer than thr=5/10 on every drawdown metric.

## 7. Conclusion & next steps

**Verdict: PROMOTE thr=2 as a small, sized-down satellite — not a core, and not
without a regime guard.**

1. **Confirmed:** real, cost-surviving, non-data-mined, broad-based edge. thr=2 +
   fixed 2×ATR stop is the spec.
2. **Reject:** trailing 1×ATR ratchet (harms PF/win-rate), thr=5/10 (higher maxDD,
   longer losing streaks, thinner cost margin).
3. **Blockers for the capital-preservation directive:**
   - Bear-market decay (2008/2022 negative). Evaluate an **index-level regime gate**
     (e.g. SPX > SMA200) before entry — note prior work shows regime filters don't
     reliably cut maxDD, so this must be *measured*, not assumed.
   - Gap-through tail risk → **cap position size** ($25–50/trade on ~$700) and accept
     the −37.9% worst-case is possible.
4. **Cost discipline:** 10 bps roughly halves the 60-year edge vs 0 bps. Fractional
   shares + liquid names keep effective spread ≤5bps — avoid wide-spread names.

*Files:* `research/stock_mr_engine.py`, `stock_mr_validate.py`, `stock_mr_report.py`,
`stock_mr_fetch.py`, `stock_mr_results.json`.
