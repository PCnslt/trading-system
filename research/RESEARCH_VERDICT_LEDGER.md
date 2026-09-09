# Research Verdict Ledger — consolidated (as of 2026-09-09)

Single source of truth for "what survives, what's blocked, what's tradeable."
Read this before any live trade. Companion to `docs/STRATEGY_PORTFOLIO.md` (full lane
registry) and the `trading-backtest-validation` / `trading-edge-research` skills.

## TL;DR — what to trade when ready

| Edge | Structure | Verdict | Blockers |
|---|---|---|---|
| **Index VRP** | SPY bull-put spread 30/15Δ, ~30 DTE, monthly | **VALIDATED but REFINED** — VRP statistically real (t=13.9 vs shuffled-VIX placebo, +3.84 vol pts fwd), BUT bull-put spread = ~90% LONG-BETA (placebo +5.48% vs real +6.06%/trade; only +0.58% is VRP alpha); tail severe (maxDD −45..−100%, gamma touch-stop fails on gap-downs). Needs position sizing + tail hedge. | L3 + margin account (user app steps) |
| **Broken Arrow** | buy close of ≥8% drop above rising 40d MA, sell next open | **VALIDATED** +34bp OOS t=3.96, single-name 1-day | already paper-testing |
| **12-1 momentum** | prior-month return, skip last week, long winners, ~20d hold | WEAK +34bp/mo net, t=0.74 | monthly + portfolio, not 1-5d |

## The L3 + capital plan (ready, waiting on user)

1. Upgrade margin acct `5SM57902` → Level 3 (in-app; applink `.../upgrade_options?account_number=5SM57902`).
2. Enable agent access on `5SM57902` (currently `agentic_allowed=false`).
3. Consolidate to ~$6k in one L3 margin account (liquidate $518 Agentic equity — I can do that — + transfer $1,789 cash + margin acct $3,732; leave IRAs).
4. Trade 1× SPY bull-put spread (~$1,400 risk at ~$15 width) → ~$1.5-1.8k/yr net; scale to 2-3 contracts as fills prove clean.
5. Broker confirmed: `place_option_order` does multi-leg spreads on option_level_3 (up to 4 legs, filled together).

## Falsified ledger (each with the cause — do NOT re-propose without new evidence)

- **Same-day directional** (~20 mechanisms): ORB, gap-fade, ITSM (decayed), VWAP reversion, intraday momentum, single-name intraday reversal — all sub-cost/beta. arXiv 2605.04004 (14/14 OHLCV families fail MNQ). **Overnight /ES-SPY basis "mispricing" fade = NO-GO** (basis_delta = timing+ETF-premium artifact; DAILY 6469d: fade @|z|>1.5 = +0.08bp t=0.02 PF 1.00, fails placebo; EXACT 1-min 09:31→10:00 [42 real ES days]: 1 signal −42.8bp, corr(basis_delta→fwd 30m)=+0.27 t=1.77 = WRONG SIGN/insignificant momentum — research/atomics/futures_basis_1min_test.py + futures_basis_mispricing_test.py).
- **Mean-reversion** (RSI2/RSI14/STOCH/Bollinger): long-beta "buy the dip"; RSI14 flat-by-close dead OOS (date-clustered t); RSI2 cross-sectional dead OOS. Full-universe re-audit 2026-09-09: NO bug, verdicts robust.
- **Momentum**: STMOM = beta (buy-winners +270bp, buy-LOSERS +302bp, random +168bp); sector rotation = reversal not momentum (reverse placebo +64bp); cross-asset TSMOM Sharpe 0.23 post-2012; 1-month reversal INVERTED (full universe); **residual z-score reversal @15min/1h also INVERTED** (long-short −5.8bp PF 0.87, fails placebo — research/atomics/xs_residual_reversal_test.py); **ORB+VWAP+MACD intraday (combined) NO-GO** — LONG −8.4bp/trade PF 0.79 t=−15.7, LONG+SHORT PF 0.77 (research/atomics/orb_vwap_macd_test.py).
- **Options single-name**: sub-$30 CSP/wheel/spreads LOSE (idiosyncratic crash); **CSP/wheel = long-beta** (overlay −2.1%/cycle vs buy-and-hold, t=−8.14); gold TSMOM = beta (Sharpe 0.30 vs B&H 0.69). **Intraday GEX/0DTE dealer-gamma "mean-reversion" = DATA-BLOCKED + reduced-form falsified** — no SPY/QQQ bars or point-in-time OI in lake (options/ = futures chain metadata only, no OI/greeks), and "dealer gamma" is unobservable from OI (total, not dealer-only; SpotGamma GEX is an estimate); stripped of GEX conditioning the two triggers are just downside-breakout-momentum + 2.5σ-extreme-reversion, both already dead above.
- **Fundamental/event (tested 2026-09-09)**: short-interest avoidance HURTS (RSI2 1.069→1.030); Lazy Prices no alpha on large caps (sign reversed); opportunistic insider +82bp/mo ≈ 4bp/day < 6bp cost; analyst-dispersion INSUFFICIENT DATA (FMP snapshot-only, IBES paywalled); index-reconstitution add-drift NO-GO (post-announcement −117/−168bp, pre-add +4bp); buyback drift decayed (liquid −39.8bp/20d, PF 0.878). Monthly/event-driven → sub-cost or decayed at 1-5d horizon.
- **Crypto**: momentum = beta, daily mean-reverts; news/sentiment/events = no tradeable edge (funding-rate folklore, liquidation = continuation, BTC rises on both pos+neg news).
- **Calendar/macro**: pre-FOMC drift decayed post-2016; turn-of-month = drift; low-vol anomaly inverted 2006-26.
- **PEAD**: dead (missers drift up); analyst-surprise-magnitude gradient = positive but AV-quota-bound, preliminary.

## Recurring CAUSE (the meta-lesson)

Every "edge" that survives a naive backtest resolves to one of: **market beta (long drift),
liquidity premium (illiquid losers), survivorship (current index constituents), or look-ahead
(full-period stat qualifying mid-period event).** The null model to run first: benchmark vs
buy-and-hold/drift + reverse/random placebo + liquidity filter + date-clustered t-stat +
chronological OOS. See `trading-backtest-validation` skill (14 bug classes).

## Account + broker facts (verified 2026-09-08/09)

- 7 RH accounts; total ~$6,460. Agent-tradeable: Agentic cash `515821577` (L2, $1,789 bp).
- Margin default `5SM57902` ($3,732) = agentic_allowed=false, L2. IRAs ~$418 (leave alone).
- RH MCP: `get_accounts`(plural)/`get_portfolio`; `get_option_orders→orders`, `get_option_positions→positions`;
  `place_option_order` dedupes by ref_id (persist BEFORE place); multi-leg only on L3.
- Cost: ~6bp RT regular hours (pre-market ~51bp, evening ~71bp). RH stops whole-share only.
- Futures: capital-blocked below ~$1.2k/micro; even at $6k only MGC gold trend "unlocks" and that's beta.

## Research tooling state

- Serper OUT OF CREDITS → use ddgs (installed, free), OpenAlex, jina.ai, Wikipedia REST, NewsAPI (key in .env).
- Fallback ladder + memory-compression procedure: skill `agent-self-maintenance`.

## Pending queue (work in flight)

- analyst-dispersion screen (untested — same "avoidance screen" family as the short-interest screen that failed).
- candidate ideas to add: index reconstitution drift, buyback-announcement drift, 13F/institutional ownership.
