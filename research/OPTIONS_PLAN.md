# OPTIONS LANE — Phaseable Plan (Lane D) · CSP→CC wheel + covered calls

> **Status: PLAN / SCAFFOLD — NOT a backtest, NOT a recommendation.**
> Research only. No orders, no IBKR, no live trading. This lane is for the
> **Robinhood "Agentic" account (laptop side, ~$700 real, OPTIONS LEVEL 2)**.
> The VPS builds/backtests; the laptop places Robinhood orders manually.
> Last updated: **2026-08-15**.

---

## 0. Executive verdict (read first)

**The options lane is NOT viable at $700. It is not "marginally small" — it is
structurally too small to run even ONE quality wheel.** Do not deploy capital.

- One equity/ETF option = **100 shares**. A cash-secured put needs collateral
  ≈ `100 × strike`, held in full at Robinhood Level 2.
- Live prices (yfinance, 2026-08-15): **SPY $776 → $77.6k collateral; QQQ $731 →
  $73.1k; F $14.37 → $1,437; SOFI $18.29 → $1,829; T $24.89 → $2,489;
  AAL $14.83 → $1,483.**
- At **$700** the *only* affordable CSPs are sub-$7 names — SNAP ($541),
  NIO ($452), PLUG ($232) — which are exactly the meme names that
  `bot/wheel_backtest.py` shows **lose money** (assignment drag). The "safe"
  names (F, SOFI, T) each need **2×–3.5× the entire account** for a single
  contract.
- The existing backtest is the decisive prior: **pooled PF 0.72, win 80%,
  CAGR −2.4%/yr, maxDD −37%, assignment 40%** — on a *sub-$25* universe that
  is already cheaper than what $700 can reach. The lane fails at its first
  gate and should be **shelved** until capital (and data) materially change.

**What would change the verdict:** see §6.

---

## 1. Capital & sizing math

### 1.1 The 100-share contract granularity floor

Every equity/ETF option contract controls **100 shares**. This is the core
constraint — it makes the *minimum* capital to express a view far larger than
the account:

| Underlying | last close | 1 contract notional | CSP collateral | affordable at $700? |
|---|---|---|---|---|
| SPY | $776.34 | $77,634 | ~$77.6k | ❌ (110× account) |
| QQQ | $731.07 | $73,107 | ~$73.1k | ❌ (104× account) |
| T | $24.89 | $2,489 | ~$2.5k | ❌ (3.6× account) |
| SOFI | $18.29 | $1,829 | ~$1.8k | ❌ (2.6× account) |
| AAL | $14.83 | $1,483 | ~$1.5k | ❌ (2.1× account) |
| F | $14.37 | $1,437 | ~$1.4k | ❌ (2.1× account) |
| SNAP | $5.41 | $541 | ~$541 | ⚠️ yes, but 77% of account + meme |
| NIO | $4.52 | $452 | ~$452 | ⚠️ yes, but 65% + meme |
| PLUG | $2.32 | $232 | ~$232 | ⚠️ yes, but meme (backtest loser) |

*(Prices = yfinance last close 2026-08-15; re-verify at the live chain before
any decision. Collateral ≈ 100 × strike; a slightly OTM 0.30Δ put reduces it a
little but never below ~90% of notional.)*

### 1.2 Max-loss ≤ 2% rule — unsatisfiable at $700

House rule: **max loss per position ≤ 2% of account = $14.00.**

- A CSP's max loss (underlying → $0) = `100 × strike − premium received`.
  To keep that ≤ $14 you would need strike ≤ ~$0.14. **No listed equity trades
  there.** The cheapest realistic CSP (PLUG @ ~$2.3) has ~$232 of max loss —
  **16× the rule.**
- The rule *cannot* be applied to a naked CSP at this capital. The 100-share
  granularity forces a minimum risk of **~$200–$1,800 per contract** even on
  the cheapest names — a single assignment is a **>65% account event**, not a
  2% event.
- The only way to satisfy the 2% rule with options is a **defined-risk spread**
  (buy a protective wing), which needs **Level 3** — this account is **Level 2**
  (long options, covered calls/puts, cash-secured puts). No spreads available.

**Conclusion: at $700, any options position is a 65–100% single bet. That is
gambling-scale sizing, not strategy.** The 2% rule is the hard gate that kills
the lane outright, independent of any edge analysis.

---

## 2. Ranked strategy menu (with capital math)

Ranked by (fit to capital) × (backtest evidence). **All are currently
blocked**; the ranking is what to revisit if capital grows.

| Rank | Strategy | What it is | Capital needed | Verdict at $700 |
|---|---|---|---|---|
| 1 | **CSP on liquid sub-$15 names (F / SOFI / AAL)** | Sell 0.30Δ 30-DTE put, take assignment → wheel CC. The *only* strategy the backtest shows even mildly positive (F/T). | 1 contract = **$1.4k–$1.8k** + ≥50% buffer → **~$2.5k minimum**, **$5k realistic** | ❌ 2.6× account for one SOFI put |
| 2 | **CSP on cheap-but-liquid ETFs** (e.g. sub-$20 broad/quality ETF) | Same wheel, but ETF = no single-name blowup → lower assignment drag. | Same 100-share math: a $15 ETF needs **$1.5k**/contract | ❌ still >$700 |
| 3 | **Covered call on existing DCA shares** | Sell CC against 100 shares already held. | **100 shares of the underlying.** DCA base = $25/wk fractional SPY:QQQ → **~$1.3k/yr.** 100 SPY = **$77.6k**; even 100 F = **$1,437.** | ❌ years away from 100 shares of anything |
| 4 | **CSP on sub-$7 names (SNAP/NIO/PLUG)** | The *only* thing $700 can actually buy. | $232–$541/contract (65–77% of account). | ❌ backtest shows these **lose** — assignment drag kills them; see §3 |

**Reading:** the affordable strategy (#4) is the one the backtest falsified;
the backtest-supported strategy (#1) is unaffordable by 2×+. The menu has **no
non-empty intersection** between "fits $700" and "has a positive edge." That is
the honest core finding.

---

## 3. What the existing backtest already tells us

`bot/wheel_backtest.py` (CSP ~0.30Δ / 30-DTE → CC until called, sub-$25
universe, 2019→now, Black-Scholes @ realized-vol proxy, $0.65/contract, 0.5%
slippage):

- **Pooled PF 0.72**, win rate 80%, mean CAGR **−2.4%/yr**, mean maxDD **−37%**,
  assignment rate **40%.**
- **Assignment drag is the killer:** cycles that end in assignment lose on
  average; premium collection does *not* cover the gap-down on meme names
  (SNAP/PLUG/NIO/RIVN).
- Only stable names **F / T are mildly positive**; everything else loses.
- Caveats baked into the script (and to be treated as such): realized-vol
  pricing **omits the IV risk premium** (understates premium — so the income
  side is conservative), dividends ignored, no early assignment.

**Implication for the plan:** the only names worth testing further are F/T
(and possibly SOFI/AAL), and **each needs $1.4k–$2.5k per contract** — none of
which $700 can touch. The backtest does *not* need to be re-run to make the
capital decision; it needs a **different universe (quality sub-$15 names)** and
a **capital-constrained variant** — but only after capital ≥ ~$2.5k makes that
question relevant.

---

## 4. Gate-style validation ladder

Aligned with the repo's gate discipline (Gate 1 backtest → … → Gate 5 paper →
Gate 7 micro-live). The options lane uses its own **O-gates**. **Current
position: Gate O-1, FAILING → lane shelved.**

### Gate O-1 — BS-approx backtest (research, on VPS)
- **Bar:** pooled PF ≥ 1.0 **and** OOS PF ≥ 1.0 **and** assignment drag does
  not dominate, on a *quality* universe (F / SOFI / AAL / T + cheap quality
  ETFs), at realistic slippage + $0.65 fee.
- **Status: FAIL (PF 0.72 on the sub-$25 universe).** The prior is negative
  even before the IV-risk-premium caveat. **Do not advance.**
- Re-run is conditional on a capital ≥ $2.5k funding event (§6) — otherwise the
  universe you could actually trade (sub-$7 memes) is the one already falsified.

### Gate O-2 — Paper (manual log/notes, on laptop)
- **Prerequisite:** Gate O-1 PASS **and** capital ≥ ~$2.5k.
- Manual paper wheel on the Robinhood chain (real live chains + IV from the
  RH MCP). **No money.** Log every cycle in a plain ledger/notes file:
  date, symbol, strike, DTE, Δ, premium, assignment y/n, cycle P&L, notes.
- **Bar:** ≥ 20 cycles (or ≥ 6 months) with tracked, *honest* fills
  (use the live bid/ask, not mid) and assignment outcomes consistent with the
  backtest's 40% rate, and **no "I'd have gotten out here" hindsight edits.**

### Gate O-3 — Micro-live (1 contract, on laptop, manual RH order)
- **Prerequisite:** Gate O-2 PASS **and** capital ≥ ~$2.5k **and** a written
  risk contract (below).
- **Exactly 1 contract**, cheapest viable quality name (F or SOFI), hard rules:
  - Max **1 open CSP** at any time (no stacking).
  - Collateral per position **≤ 50% of account** (never the ~100% it would be
    at $700).
  - **No averaging down on assignment** — either wheel (CC at/above cost basis)
    or take assignment-and-hold; **never** add a second put to "rescue."
  - Kill-switch: **stop adding** after 2 consecutive losing cycles; review.
- **Bar:** N clean cycles (define N at O-2 exit, ~10–20) with zero rule breaks.

### Gate O-4 — Scale
- Only after O-3 passes: add a 2nd uncorrelated underlying; still cap total
  option collateral at a fixed % of account. Never scale into the meme names.

**Ladder discipline:** each gate is a hard promotion/kill decision. The lane
does **not** jump from backtest to live — the whole point is that O-1 already
fails, so the lane stays **shelved** with its code + findings preserved.

---

## 5. Data & entitlement gaps (flag, do not substitute)

Per the standing data-integrity rule — **never silently substitute free/stale
data for critical paid data; flag the gap and ask the owner.**

| Need | Have? | Source | Flag |
|---|---|---|---|
| Current options chains + IV (bid/ask, OI, greeks) | ✅ for *live/paper* pricing | **Robinhood MCP (laptop)** exposes live chains + IV | Laptop-side only; the VPS has no RH access |
| Current chains (for backtest *today* pricing only) | ⚠️ partial | yfinance exposes **current** chain only | No history |
| **Historical options bars (multi-year)** — required for an *honest* wheel backtest | ❌ **NONE** | — | **PAID-ONLY.** IBKR paper = chain *metadata* (expiries+strikes) only; yfinance = current chain only; `docs/DATA-CATALOG.md` §5.3 already lists "Options on futures BARS — separate subscription" |
| Historical stock prices (for BS proxy) | ✅ | yfinance daily | The *only* free input — and it's the reason the backtest is an **approximation**, not a real options backtest |

**Explicit integrity statement:** `wheel_backtest.py` prices options with a
Black-Scholes approximation at realized 30-day vol (clamped 15–150%), *not*
real historical option prices. It is labeled as such and its absolute $ numbers
are approximate. **This plan does not and must not treat the BS-approx
backtest as a substitute for a real historical options backtest.** If the lane
is ever to be promoted on evidence, a **paid historical options dataset** (e.g.
ORATS, CBOE DataShop, or a broker with historical option prices) is required —
**purchase decision pending owner**, not something this plan paper-over with
free data.

---

## 6. Honest verdict + what changes it

### Verdict
**Do not trade the options lane at $700.** It is a capital-granularity problem,
not an edge problem:

1. **Max-loss ≤ 2% ($14) is unsatisfiable** — 100-share granularity forces
   $200+ minimum risk per contract; no defined-risk spreads at Level 2.
2. **The affordable strategies are the falsified ones** — sub-$7 meme CSPs
   (SNAP/NIO/PLUG) are the losers in the backtest (assignment drag, PF < 1).
3. **The backtest-positive strategies are unaffordable** — F/SOFI/T/AAL each
   need $1.4k–$2.5k for one contract (2–3.6× the account).
4. **Covered calls are moot** — DCA base ($25/wk fractional) is years from 100
   shares of anything.
5. **No free historical options data exists** to even re-validate honestly.

**Recommendation:** keep the $25/wk SPY:QQQ DCA running (it is the correct
$700-class vehicle — fractional, diversified, no granularity floor). Shelve
the options lane; revisit only on a funding or data event.

### What would change the verdict (revisit triggers)
- **Capital ≥ ~$2.5k (realistically $5k).** Then ONE quality CSP (F/SOFI) fits
  with a ≤50% collateral buffer, and the O-1 backtest on a quality universe
  becomes worth re-running. $2k is the *minimum* to clear the granularity floor
  with a buffer; below it, no.
- **A paid historical options dataset.** Then we can measure whether the IV
  risk premium actually rescues the wheel (the BS-approx omits it) — and the
  assignment-drag finding can be re-tested against *real* premium, not a proxy.
- **Robinhood Level 3 (spreads).** A defined-risk put credit spread would let
  the 2% max-loss rule actually bind on small capital — but spreads change the
  strategy (no assignment/wheel mechanic), so that's a *different* lane, not a
  rescue of this one.
- **A cheap, liquid, non-meme sub-$7 underlying with real option liquidity.**
  None currently qualifies; if one appears it would be the single exception
  worth a micro-live probe at $700.

Until one of those triggers fires: **shelved, code preserved, no capital.**
