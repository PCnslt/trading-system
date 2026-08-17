# Strategy Portfolio Registry

> **Single living registry of EVERY strategy lane in the system.** Additive, not
> winner-takes-all: nothing is ever deleted, every NO-GO stays here with its
> reason **and** the precise trigger that would re-activate it. If a lane exists
> in a backtest, a bot file, a gate report, or a plan doc, it appears here.
> Last updated: **2026-08-16**.

---

## Status vocabulary

| Status | Meaning |
|---|---|
| **LIVE-PAPER** | Running on paper (paper-EXEC on IBKR DUR193467, or signal-only `exec=NONE`). Not real money. |
| **LIVE-READY** | Edge validated + deploy spec complete; blocked only by a paper-forward / regime-gate step before real money. |
| **PARKED-PENDING** | Edge survives costs but is blocked on a *funding / data / entitlement* event; scheduled to return. |
| **NO-GO-WITH-REASON** | Killed/retired for a recorded reason. **Stays here** with the exact re-activation trigger. |
| **RESEARCHING** | Active research; no promote/kill verdict yet. |

## Status counts (2026-08-16)

| Status | Count |
|---|---|
| LIVE-PAPER | 3 |
| LIVE-READY | 1 |
| PARKED-PENDING | 1 |
| NO-GO-WITH-REASON | 21 |
| RESEARCHING | 5 |
| **Total lanes** | **31** |

---

## Primary portfolio (the 10 headline lanes)

| # | Lane | Asset class | Status | IS PF / OOS PF | Capital | Blocks activation / re-activation trigger |
|---|---|---|---|---|---|---|
| 1 | **RSI2 buy-the-dip** (Robinhood) | Equities (10 ETFs + top-50 S&P100 large-caps) | **LIVE-READY** | IS 1.42 (thr5) / OOS 1.47 walk-fwd (all 5 folds >1.0); 1.36 @5bps, 1.26 @10bps · SPY IS 2.00 / OOS 2.04 | ~$700 Robinhood **whole-share small-ticket** (VPS `rh_client` single-writer; `live_equities.py` feeds signals, gated `exec=LIVE`) | **Paper-trade ≥30 days on a small-ticket liquid sub-universe.** Index regime gate already validated-**REJECTED** (do not re-add); bear-year warning (2008 PF 0.36 / 2022 0.81) stays on signals. Whole-share sizing at $700 = sub-$35 names, ~5–15 concurrent, 5%/name satellite cap. See `docs/SMALL-CAPITAL-LIVE-PLAN.md`. |
| 2 | **Index Donchian + RSI2-LONG** (MES/MNQ) | Index futures | **LIVE-PAPER** | Donchian IS 1.56 / OOS 1.52 (1.43 @3t) · RSI2-LONG IS 1.99 / OOS 2.57 (1.88 @3t) | $50k paper fwd-test sleeve @1% risk (`live.py`, IBKR paper, Gate 5 0/10 sessions) | **Gate 5 (10 RTH sessions) → Gate 6 shadow → Gate 7 micro-live.** Also: 1% risk sizing flips full-size MES/MNQ to size=0 → need MES-micro or sleeve decision. |
| 3 | **Gold Donchian + TSMOM** (GC/MGC) | Gold futures | **LIVE-PAPER** | Donchian IS 1.45 / OOS 1.81 (1.42 @3t) · TSMOM IS 1.37 / OOS 1.73 (1.35 @3t) | $1.5M paper fwd-test sleeve (`live_gc.py`, paper-EXEC clientId 78); MGC micro = realistic live (~$900 margin, $2.3k/stop) | **Real-time metals L1** (GC delayed-on-paper → signal-only until subscribed) **+ MGC micro sizing** (full GC = ~$23k risk/contract). |
| 4 | **Seasonal commodities** (month-of-year) | Commodity futures | **PARKED-PENDING** | IS 1.20 / OOS 1.23 (n=1360), cost-stable @3t | Needs **$5–10k IBKR** (full-size margins: GC $8–12k, PL $3–5k, ZC/ZS $2–3k, HE $1.5–2k); currently ~$500 | **Fund IBKR to $5–10k** (full-size futures margin) **+ ≥5y same-month 2nd source** to cross-confirm (unconfirmable on ~3y IBKR bars). |
| 5 | **5-day momentum** (short-term TSMOM) | Equities | **NO-GO-WITH-REASON** | IS 1.20 → 1.07 @10bps (53k trades, high turnover) | Robinhood (equities) | Cost-fragile at any realistic slippage — dies to ~breakeven at 10bps on 53k trades. **Re-activate only under near-zero-friction execution** (no realistic trigger). |
| 6 | **Single-name Donchian** (20d breakout) | Equities (single stocks) | **NO-GO-WITH-REASON** | pooled IS 1.18 → 1.04 @10bps | Robinhood (equities) | Too noisy on individual names (edge lives in index-level trend). **Re-activate only with a quality+volume-gated universe or materially lower cost.** (ETF variant = LIVE-READY small diversifier, see lane 1 note.) |
| 7 | **Pairs / stat-arb** (Z-score MR) | Equities (market-neutral, 10 liquid pairs) | **NO-GO-WITH-REASON** | IS 1.29 → 1.14 @10bps (win 62%, ~+0.4%/trade) | IBKR (needs short leg) | Requires a short leg: Robinhood cash acct can't short; IBKR paper can but isn't live. **Re-activate = shorting enabled (IBKR live margin) + more capital + wider than 10 pairs.** |
| 8 | **Options credit spreads / iron condors** | Options (defined-risk short premium) | **NO-GO-WITH-REASON** | IS 1.04 synthetic (IV=realized, no premium) / 1.48 @15% vol premium · OOS n/a | Robinhood (needs Level 3 + $5k) | Two blockers: **paid historical options archive** (verify the index vol-premium edge) **+ capital ≥$5k** (SPY/QQQ spread ≤5% acct) **+ Robinhood Level 3** (spreads). |
| 9 | **Gap fade** (2% gap-down, 5d hold) | Equities | **NO-GO-WITH-REASON** | IS 1.34 → 1.26 @10bps (win 55%); same-day fade 0.99 @10bps; futures GAP_FADE OOS 0.94 | Robinhood (equities) | Redundant with RSI2-dip (same buy-the-dip exposure, RSI2 stronger + fully validated). **Re-activate only if shown non-redundant** (a regime the RSI2 lane doesn't cover). |
| 10 | **Intraday VWAP** (2σ reversion) | Index futures (MES/MNQ) | **RESEARCHING** (HOLD) | IS 1.12 @0t / 1.00 @3t / OOS 1.03; **1.08 @1t realistic** (Sharpe 1.04) | $25k paper intraday sleeve (`live_intraday.py`, `exec=NONE`) | **Param sweep (VWAP_K 1.5/2/2.5 + high-volume filter) + deeper 1-min archive.** Per-symbol inconsistent (Nasdaq micros/minis +, S&P/energy −). |

---

## Additional lanes (retired / shelved / research — NOTHING removed)

| # | Lane | Asset | Status | IS PF / OOS PF | Reason / re-activation trigger |
|---|---|---|---|---|---|
| 11 | Bonds fade-SHORT (ZB/ZN) | Rates futures | **NO-GO-WITH-REASON** (KILLed, `live_bondsfx.py` disarmed) | RSI2SHORT IS 1.05 / OOS 1.31 → 0.94 @1t, 0.85 @2t · BBANDSHORT 0.99 / 1.01 | Dies at 1-tick slip (avg trade ~$28 on $1000/pt). **Re-activate only if cost/rate-regime materially changes.** |
| 12 | BBAND_INDEX_LONG | Index futures | **NO-GO-WITH-REASON** (TABLED) | IS 1.84 / OOS 1.71 | Redundant with RSI2-LONG (corr 0.69, 73% overlap). **Re-activate if RSI2-LONG underperforms live.** |
| 13 | Crypto Donchian-20 + 200d (BTC/ETH) | Crypto | **LIVE-PAPER** (signal-only, `crypto_paper.py`) | OOS 1.50 (n=79), maxDD −44% | Buy-and-hold proxy (200d filter). LOWEST live-priority (owner distrusts crypto). |
| 14 | CSP→CC wheel | Options/equities | **NO-GO-WITH-REASON** | pooled IS 0.72 (win 80%, assignment 40%) | Assignment drag is the killer; meme names lose. **Re-activate = capital ≥$2.5k + paid options data** (quality sub-$15 universe). |
| 15 | Carry / term-structure | Futures | **NO-GO-WITH-REASON** (data gap) | IS 1.01 / OOS 1.13 (n=24) | Permanent data gap: expired contracts = Error 200 on paper. **Re-activate = paid multi-decade term-structure archive** (Pinnacle/CSI/Bloomberg). |
| 16 | XSMOM futures (12m cross-section) | Futures | **NO-GO-WITH-REASON** | IS 0.94 / OOS 0.90 (n=120) | Negative on 26y yf read, dies @1t. Genuine no-edge. |
| 17 | XSMOM equities (L/S) | Equities | **NO-GO-WITH-REASON** | IS 0.47 mean / 1.27 median / OOS 1.09 (L/S) | Short leg destroyed by squeezes + survivorship + borrow costs. (Long-only leg = real, see lane 29.) |
| 18 | Value / 5y reversal | Futures | **NO-GO-WITH-REASON** | IS 0.90 / OOS 0.79 (n=102) | Negative both constructions; dies @1t. Genuine no-edge in 14-name universe. |
| 19 | Vol-targeting overlay | Overlay (futures) | **NO-GO-WITH-REASON** (HOLD as de-risker) | n/a (overlay) | Not a Sharpe lift; only a de-levered risk dial. Keep as a tool, not a promotion. |
| 20 | ORB (30-min range break) | Index futures (intraday) | **NO-GO-WITH-REASON** | IS 1.04 @0t / 0.97 @3t / OOS 0.86 | Dies at 3-tick; pooled OOS 0.86. |
| 21 | MOM intraday (10-bar ROC) | Index futures (intraday) | **NO-GO-WITH-REASON** | IS 0.95 @0t / 0.80 @3t / OOS 0.78 | Dead even at 1-tick. |
| 22 | DONCH15 (15m Donchian/ATR) | Index futures (intraday) | **NO-GO-WITH-REASON** | IS 1.05 @0t / 0.99 @3t / OOS 0.87 | Breakeven+ at 1-tick, dies @3t. |
| 23 | FADESHORT intraday (RSI2+Boll short) | Index futures (intraday) | **NO-GO-WITH-REASON** (signal-only collecting) | IS 1.07 @0t / 0.95 @3t / OOS 1.16 (regime-dependent) | Lowest-drawdown intraday but still net-negative. Keep collecting signals, no execution. |
| 24 | KAMA crossover (intraday 5-min) | Index futures (intraday) | **NO-GO-WITH-REASON** (wrong horizon) | IS 0.82 @0t / 0.70 @3t / OOS 0.68 | Whipsaws at 5-min granularity. **Re-test on daily / 2–3-day swing horizon** (where KAMA is designed to run). |
| 25 | 5-day reversal | Equities | **NO-GO-WITH-REASON** | IS 1.46 pooled / OOS 1.31 (regime-flipped: SPY 2.93 → 0.94 post-2009) | Regime-flipped + inconsistent across symbols. |
| 26 | Golden cross (50/200) | Equities | **NO-GO-WITH-REASON** | IS 3.57 / OOS 3.20 (n=88) | Statistically meaningless (n=4–7 OOS/symbol despite inf PF). |
| 27 | Bollinger lower-band | Equities | **NO-GO-WITH-REASON** | IS 1.42 / OOS 1.11 | 0.72 corr with RSI2 — redundant, do not co-deploy. |
| 28 | 200d MA trend | Equities | **RESEARCHING** (HOLD) | IS 1.99 pooled / OOS 2.42 (n=538) | Regime overlay, thin standalone (SPY OOS n=29). Use as a filter, not a signal. |
| 29 | 12m XSMOM long-only (equities) | Equities | **RESEARCHING** (candidate) | IS 1.80 / Sharpe 0.78, ann +14.4% | Side-finding from lane 17 — real long-only edge, needs a 50-name monthly-rebalanced book (future funded-account idea). |
| 30 | Forex spot (28 pairs) | FX | **RESEARCHING** (data-only) | n/a | No edge/broker yet. Daily + 1h → `yf/fx/` for future research. Schwab API on hold. |
| 31 | Futures-options chain scaffold | Options on futures | **RESEARCHING** (scaffold) | n/a | Chain metadata for 12 underlyings only; vol-surface/greeks need paid bars (not requested). |

---

## Not a strategy lane (listed for capital completeness)

- **DCA base layer** — $25/wk, 50/50 SPY:QQQ fractional (Robinhood, laptop). Passive buy-and-hold, not an evaluated strategy lane; no PF metric.

---

## Maintenance rule (binding)

- **This file is updated in the SAME commit as every future sweep / gate decision.**
  A promote, kill, park, or new-backtest verdict that changes any row here must land
  together with its code/script/report change — never separately, never later.
- **Additive only.** Retire a lane by flipping its Status to `NO-GO-WITH-REASON`
  (or `PARKED-PENDING`) and recording the re-activation trigger — never by deleting
  its row. The total-lane count only ever grows or stays flat.
- Author all commits `PCnslt <info@pcnslt.com>`; targeted `git add docs/STRATEGY_PORTFOLIO.md …`.

## Grounding (where the numbers come from)

- Lanes 1, 6, 9, 25–28: `research/EQUITIES_SWEEP.md`, `research/ROBINHOOD_LANE_PLAN.md`, `research/SMALL_CAPITAL_OPPORTUNITIES.md`.
- Lanes 2, 11, 12: `research/GATE1_REPORT.md`.
- Lane 3, 13: `research/EDGE_SWEEP.md`, `research/CROSS_LANE.md`.
- Lane 4, 15–19, 29: `research/EDGE_SWEEP.md`, `research/EDGE_SWEEP2.md`.
- Lanes 5, 7, 8: `research/SMALL_CAPITAL_OPPORTUNITIES.md`, `research/options_spread_synth.py`.
- Lane 10, 20–24: `research/INTRADAY_GATE1_VALIDATION.md`, `research/INTRADAY_BUILD.md`.
- Lane 14: `bot/wheel_backtest.py`, `research/OPTIONS_PLAN.md`.
