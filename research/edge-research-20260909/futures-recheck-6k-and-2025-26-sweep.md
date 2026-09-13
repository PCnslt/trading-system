# Futures Edge Re-Check @ ~$6k + Fresh 2025–2026 Literature Sweep

**Date:** 2026-09-09 · **Researcher:** subagent (trading-edge-research)
**Constraint change:** micro futures were CAPITAL-BLOCKED at $700 (all micro margins ≥ $700).
Now ~$6k → every micro is expressible with room for a stop + a 2nd position; full-size futures
(ES ~$12k, NQ ~$20k, GC ~$9k, CL ~$7k) remain blocked.

---

## 0. Micro-futures cost & margin map (futures cost prior = per-tick, no commission on IBKR micros ≈ $0.25–0.85/RT)

| Contract | Underlying | Multiplier | Tick | $/tick | ~CME initial margin |
|---|---|---|---|---|---|
| MES | Micro E-mini S&P500 | $5 × idx | 0.25 | **$1.25** | ~$1,200 |
| MNQ | Micro E-mini Nasdaq100 | $2 × idx | 0.25 | **$0.50** | ~$2,000 |
| MYM | Micro E-mini Dow | $0.50 × idx | 1.0 | **$0.50** | ~$1,000 |
| M2K | Micro E-mini Russell2000 | $5 × idx | 0.10 | **$0.50** | ~$700 |
| MGC | Micro Gold | 10 oz | 0.10 | **$1.00** | ~$1,100 |
| SIL | Micro Silver (SI class) | 1000 oz | 0.005 | **$5.00** | ~$1,800 |
| MCL | Micro WTI Crude | 100 bbl | 0.01 | **$1.00** | ~$800 |
| M6E | Micro EUR/USD | 12,500 € | 0.0001 | **$1.25** | ~$300 |
| MBT | Micro Bitcoin | 0.1 BTC | $5 | **$0.50** | ~dynamic (1.5–2.5k) |

**Margin honesty note:** these are standard CME initial-margin levels (stable, but move with vol).
I could NOT pull live per-account values: the paper gateway (`:4002`, futures entitlement) is
DOWN and the live gateway (`:4001`, equities) timed out on a read-only API handshake (busy
serving the live lane — not disturbed further). Verify exact margin in IBKR Client Portal at
trade time. Crossing the spread on liquid micros ≈ **1 tick**; budget **1–2 ticks round-trip**.

---

## PART 1 — Futures edges re-ranked at ~$6k (futures-first)

### 1. SLOW TSMOM / trend on GOLD via MGC — **ACTUAL EDGE** (strongest evidence in bank; concentration caveat)

- **Rules (system-validated, Lane 3):** Donchian-20d breakout both directions (entry close > 20d
  high / < 20d low, 2×ATR GTC stop, 5d time stop, opposite-breakout exit) **and/or** TSMOM
  (sign of trailing 12m return, rebalance every 21 bars, always-in-market). Trade the micro
  contract **MGC** (10 oz).
- **Magnitude + sample + significance (own backtest, 26y yfinance + ~3–5y IBKR):** Donchian
  **IS PF 1.45 / OOS PF 1.81 (n=114)**; TSMOM **IS 1.37 / OOS 1.73**; IBKR broker-bar confirmation
  **1.31 / 1.99** — BOTH sources agree on direction and both survive 3-tick slippage (≥1.35).
- **Citation:** Moskowitz–Ooi–Pedersen 2012, JFE 104(2):228–250 (12m TSMOM across 58 futures,
  "significant predictability"); system Lane 3 `research/EDGE_SWEEP.md`.
- **Cost prior:** MGC $1.00/tick; 1–2 ticks RT is immaterial vs a multi-$-to-10s-$ trend trade
  (this is WHY it survives 3-tick).
- **Verdict: ACTUAL EDGE** — the single futures edge in the bank with dual-source agreement +
  cost robustness, now capital-unblocked. Caveats: single-market concentration (gold), drawdown-first
  sizing mandatory, and the "always-in-market TSMOM" variant carries 2013-style whipsaw risk.

### 2. Commodity seasonality (month-of-year) — **INSUFFICIENT DATA** (unconfirmable + micro slice thin)

- **Rules:** expanding month-of-year mean return; long if historically positive, short if negative;
  hold the full calendar month. `min_years=5` warmup.
- **Magnitude + sample (own backtest):** pooled **IS 1.18 / OOS 1.19**; commodity-only **1.20 / 1.23
  (n=1360)**, cost-stable @3t. Held as PARKED-PENDING (Lane 4) because it needed **$5–10k for
  FULL-SIZE margins**.
- **What $6k changes:** only **MGC (gold)** and **MCL (crude)** are micro-expressible; the seasonal
  edge is concentrated in ags/energy (ZC/ZS/HE/LE) which are full-size-only.
- **Verdict: INSUFFICIENT DATA** — the pooled edge is real but (a) structurally unconfirmable on the
  ~3y IBKR bars (5y warmup → 0 trades) and (b) the $6k-expressible micro subset (gold/oil) is a thin
  2-market slice of the effect. Needs a ≥5y second source AND a decision on whether the gold/oil
  seasonal alone carries the edge.

### 3. Cross-sectional futures CARRY — **EVIDENCE OF NO EDGE** on the expressible subset (proxy KILL)

- **Rules (literature):** Koijen–Moskowitz–Pedersen–Vrugt 2018 JFE 128(2):234–253 — sort ~25–29
  global futures/FX/equity/bond contracts by carry (near-vs-far slope), long high-carry / short
  low-carry, monthly. Gross Sharpe ~1.1 in-sample.
- **Why it does NOT transfer to $6k:** needs ~20+ contracts across asset classes. Micro futures
  cover ~10 markets, and 4 of them are equity-index (MES/MNQ/MYM/M2K) with thin/near-zero carry
  dispersion. True term-structure carry also needs **2 contracts per market** (front+back = 2× margin).
- **Own test (Lane 15 + `edge_sweep2`):** the carry PROXY (12m momentum as carry/contango proxy,
  cross-sectional) = **OOS PF 0.85 → KILL**; the fixed-calendar-spread proxy (2 current-chain
  contracts) = **PF 1.01, dies at 1-tick, train-PF 0.60** → NO edge.
- **Verdict: EVIDENCE OF NO EDGE** on the micro-expressible subset (two independent proxies negative).
  The academic carry premium is real at the full ~25-contract cross-asset scale, but that is NOT
  expressible at $6k with micros → the honest split is "no edge on what we can trade; un-expressible
  at full scale."

### 4. VWAP 2σ intraday reversion (equity-index sleeve) — **INSUFFICIENT DATA** (thin real edge, forward-test open)

- **Rules (Lane 10, validated):** fade 2σ deviations from session VWAP, equity-index futures only
  (MES/MNQ/MYM). Volume filter gates the sleeve.
- **Magnitude (own backtest):** equity-index group **OOS PF 1.11–1.38 @1t**, stable across VWAP_K
  1.5–2.5. **Cross-asset NO-GO**: metals 0.94 / energy 0.97 fail → the edge is index-only.
- **Verdict: INSUFFICIENT DATA** — real but below/at the 1.3 OOS bar on the weakest cells, requires
  intraday 1–5min execution, and is already running LIVE-PAPER (`live_vwap.py`). 1-min 24-month
  re-validation is BLOCKED (IBKR paper 1m ≈ 30d cap). Forward-test before any real capital.

### 5. Market intraday momentum (first-half → last-half) — **EVIDENCE OF NO EDGE** (reinforced by new 2026 falsification)

- **Rules:** signal = return prev-close → 10:00 ET (Gao–Han–Li–Zhou 2018) or prev-close → 15:30
  (Baltussen 2021 `r_ROD`); trade the last half-hour.
- **Prior decay (own):** SPY 2024–26 re-test ≈ **0 bp, t<0** (banked `factor-economics-and-same-day-decay.md`).
- **NEW independent falsification:** arXiv 2605.04004 (May 2026) — **14 intraday OHLCV signal
  families on MNQ, 947 trading days (2021–2025), 5-min**: ALL fail net of a fixed 2-point friction;
  max gross 0.07–1.50 pts/trade vs the 2-pt cost. Two proprietary positive controls (RTH Confluence
  T=5.83; London Session B T=5.15) prove the methodology can detect real edge — the 14 standard
  families just don't have any.
- **Verdict: EVIDENCE OF NO EDGE** for standard OHLCV intraday momentum on micro index futures.

### 6. Cross-asset 1-month TSMOM — **EVIDENCE OF NO EDGE** (already falsified; NEW causal mechanism)

- **Already falsified (Lane 35):** 29-contract 1-month TSMOM = **Sharpe 0.23, CAGR +2.2%, maxDD −62%**,
  flat/negative 2013–2026, all profit pre-2012 commodity supercycle.
- **NEW explanation (arXiv 2607.01550, Jul 2026):** short-term trend-following died ~2009 specifically
  on **small-tick** contracts (HFT-dominated books withdraw liquidity in front of predictable flow);
  it remains intact on **large-tick** contracts. MES/MNQ are small-tick → predicts exactly the
  degradation the system measured. This is a *mechanism*, not a new trade: it says "don't trend-follow
  small-tick micro index futures short-term," and hints that large-tick (e.g. gold) slow trend survives
  — consistent with candidate #1.
- **Verdict: EVIDENCE OF NO EDGE** (short-horizon TSMOM on micro index; do not re-hash).

### 7. Basis / mispricing — **NO EVIDENCE** (no retail-expressible rule)

- **What exists:** index cash-futures basis predictability and ETF-vs-futures arb are real but are
  HFT/market-maker infrastructure (simultaneous futures + cash/ETF legs, colocation). Ag "basis
  trading" (post-harvest) is an elevator/grain-infrastructure business. NEW: ML calendar-spread
  stat-arb (arXiv 2606.25811, Jun 2026) shows learning-based calendar spreads beat long-only — but it
  is an ML method needing full-size commodity contracts + maturity-linked graph features, not a
  discrete retail rule; "Profitability of Basis Trading Strategies in Futures Markets" (J. Arkansas
  Academy of Science 2026) is an ag-economics thesis, no extractable net-of-cost rule.
- **Verdict: NO EVIDENCE** of a simple, $6k-expressible basis/mispricing edge.

---

## PART 2 — Fresh 2025–2026 literature (NEW anomalies NOT in the bank)

### NEW anomaly candidates (bank these)

**A. Factor Momentum in Commodity Futures Markets** — J. Futures Markets 2025, doi `10.1002/fut.70022`
- **Rule:** commodity FACTOR returns (not asset returns) predict their own future; strongest at
  **1-month** horizon; explained by mispricing. US + UK data 1985–2022.
- **Magnitude:** factor-momentum predictability significant; (table-level Sharpe NOT-EXTRACTED — paywalled).
- **Verdict: INSUFFICIENT DATA** for this account — genuine new documented anomaly, but needs commodity
  factor construction + full-size contracts; NOT micro-expressible. Bank it for a future funded-account book.

**B. Cross-market overnight time-series momentum** — J. Int. Fin. Markets, Institutions & Money 2025,
doi `10.1016/j.intfin.2025.102239`
- **Rule:** overnight TSMOM signals propagated across international markets.
- **Magnitude:** NOT-EXTRACTED (abstract unavailable via OpenAlex/S2/jina — paywalled).
- **Verdict: INSUFFICIENT DATA.**

**C. "Dark side of the day: Overnight price jumps and short-term return predictability"** —
J. Behavioral & Experimental Finance 2026, doi `10.1016/j.jbef.2026.101220`
- **Rule:** overnight (close→open) price jumps predict short-horizon returns.
- **Magnitude:** NOT-EXTRACTED (abstract not retrievable; PII guess 404'd).
- **Verdict: INSUFFICIENT DATA.** Mechanism is a cousin of the already-banked overnight/weak-close
  cluster — worth one targeted fetch before queueing.

**D. Intraday Momentum in Spot FX and Currency Futures (JPY amplification)** — SSRN 7008318 (2026)
- **Rule:** intraday momentum in FX/currency futures with a JPY amplification mechanism.
- **Magnitude:** NOT-EXTRACTED (SSRN CAPTCHA-walled).
- **Verdict: INSUFFICIENT DATA** (and FX futures are NOT entitled on the paper account — see ibkr-data-access).

**E. Insider (Form 4) purchase signals in microcaps** — arXiv 2602.06198 (Feb 2026)
- **Rule:** gradient-boosting on SEC Form 4 open-market insider purchases (17,237 purchases, 1,343
  issuers, $30–500M cap, 2018–2024); AUC 0.70 OOS 2024; distance-from-52wk-high = 36% of signal.
- **Verdict: NO EVIDENCE** for this system — equities (not futures), needs microcap universe +
  point-in-time Form 4 feed we don't hold; also overlaps the documented "insiders buy at 52-wk-lows
  = reversal" already covered by RSI2/REV2.

### Negative-evidence papers (2025–2026) that CONFIRM the system's prior conclusions

**F. Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures** — arXiv 2605.04004 (May 2026).
14 families, 947 days, 2021–25 → all fail net of 2-pt friction. → reinforces Part-1 #5 **EVIDENCE OF NO EDGE**.

**G. Is Trend Still Your Friend? (demise of short-term trend-following)** — arXiv 2607.01550 (Jul 2026).
~100 liquid futures, 1995–2025; tick-size is the discriminator; small-tick trend dead post-2009. →
mechanism behind Part-1 #6.

**H. Retail Trader's Ruin** — arXiv 2607.20093 (Jul 2026). 5 retail signal families; 4/6 REFUTED,
momentum INCONCLUSIVE, none SUPPORTED net-of-cost. → independent confirmation of the null.

**I. Speculators and TSMOM in commodity futures** — Review of Financial Economics 2025, doi `10.1002/rfe.1228`.
Speculators trade TSMOM; higher speculator↔TSMOM alignment → **lower** realized TSMOM performance.
→ crowding/decay evidence for TSMOM (supports Part-1 #3/#6 caution).

**J. Option-implied smirk decay** — arXiv 2608.26115 (Aug 2026). Xing-et-al smirk coefficient decayed
−0.023 (t=−5.5, 2015–19) → −0.006 (t=−1.5, 2023–26). → another post-publication decay data point.

---

## Ranked candidate list (futures-first) — summary table

| Rank | Candidate | Instrument | Verdict | Key evidence |
|---|---|---|---|---|
| 1 | Slow TSMOM / Donchian on gold | MGC | **ACTUAL EDGE** | OOS PF 1.73–1.81, dual-source agree, 3-tick-stable; MOP 2012 |
| 2 | Commodity seasonality | MGC/MCL (thin) | INSUFFICIENT DATA | pooled OOS 1.19 but micro slice thin + unconfirmable |
| 3 | VWAP 2σ index reversion | MES/MNQ/MYM | INSUFFICIENT DATA | OOS 1.11–1.38 @1t, index-only, fwd-test open |
| 4 | Cross-sectional carry | (micro subset) | EVIDENCE OF NO EDGE | proxy OOS 0.85 + spread proxy PF 1.01 |
| 5 | Market intraday momentum | MES/MNQ | EVIDENCE OF NO EDGE | 0bp re-test + arXiv 2605.04004 (14/14 fail) |
| 6 | 1-month cross-asset TSMOM | micro index | EVIDENCE OF NO EDGE | Sharpe 0.23, −62% DD + tick-size mechanism |
| 7 | Basis/mispricing | n/a | NO EVIDENCE | HFT/MM infra or ML-only; no retail rule |

**Bottom line:** the $6k unlock converts exactly ONE previously-blocked lane into a tradeable edge
(gold momentum via MGC), and the fresh 2025–26 literature does **not** hand us a new micro-tradeable
anomaly — it mostly re-confirms the null and supplies a causal mechanism (tick size) for *why* the
short-horizon futures momentum edges are dead. The single genuinely-new documented anomaly (commodity
factor momentum) is not micro-expressible.
