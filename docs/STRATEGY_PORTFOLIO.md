# Strategy Portfolio Registry

> **Single living registry of EVERY strategy lane in the system.** Additive, not
> winner-takes-all: nothing is ever deleted, every NO-GO stays here with its
> reason **and** the precise trigger that would re-activate it. If a lane exists
> exists in a backtest, a bot file, a gate report, or a plan doc, it appears here.
> Last updated: **2026-08-31**.

---

## Status vocabulary

| Status | Meaning |
|---|---|
| **LIVE-PAPER** | Running on paper (paper-EXEC on IBKR DUR193467, or signal-only `exec=NONE`). Not real money. |
| **LIVE-READY** | Edge validated + deploy spec complete; blocked only by a paper-forward / regime-gate step before real money. |
| **PARKED-PENDING** | Edge survives costs but is blocked on a *funding / data / entitlement* event; scheduled to return. |
| **NO-GO-WITH-REASON** | Killed/retired for a recorded reason. **Stays here** with the exact re-activation trigger. |
| **RESEARCHING** | Active research; no promote/kill verdict yet. |

## Status counts (2026-08-18 — STALE: the table below enumerates lanes 1-46, not 31)

| Status | Count |
|---|---|
| LIVE-PAPER | 3 |
| LIVE-READY | 1 |
| PARKED-PENDING | 1 |
| NO-GO-WITH-REASON | 24 |
| RESEARCHING | 4 |
| **Total lanes** | **46** (rows 1-46 below; this summary table has not been recounted since 08-18) |

### Execution verdicts (evidence-based, added 2026-08-24)

| Decision | Evidence | Outcome |
|---|---|---|
| **Trailing stop vs fixed 2xATR stop** on the RSI2 family | `research/stock_mr_results.json` → `trailing_vs_fixed`, walk-forward: @0bps fixed PF 1.543 / trail 1.499 · @5bps fixed **1.319** win 65.6% hold 2.10d / trail **1.269** win 59.0% hold 1.66d · @10bps fixed 1.211 / trail 1.174. **RE-CONFIRMED 2026-08-25** on IBKR broker bars, 383 syms / 11.7k trades / 5bps (`research/TRAILING_STOP_VERDICT.md`): fixed PF **1.110** +18.1bp t=+3.30 · naive trail PF 1.004 +0.6bp · "smart" armed-ratchet PF **0.927 −11.8bp t=−2.64**. | **FIXED WINS at every cost level, and every trailing variant tested loses.** Mechanism: gap-through exits 357→888 — a tighter stop sits inside the overnight gap and RH stops are RTH-only, so gaps fill at the open, not the stop. Trailing also steals trades from the revert rule (8531→7563) before mean reversion completes. `bot/rh_trailing.py` DELETED 2026-08-25 (broken RH stop detection + rejected twice). `bot/rh_trailing_smart.py` kept but DISABLED, no cron. Risk control on this lane is **position SIZE**, not stop tightness. Re-enable only with a backtest showing trail >= fixed. |
| **Live fills to date** | DynamoDB: 7 TRADE#/RHTRADE# rows total; 2 are strategy round trips (AMZN +$0.6703, AVGO -$0.3603 = **+$0.31**); 25 RISK# rows all show `daily_trades=0` | **The RSI2 lane has never filled a live trade.** Only lifetime live fills are the retired DCA fractions (SPY/QQQ, 2026-08-14, ~$25). No lane in this registry has a live track record. |
| **Entry-timing lag** (RSI2 backtest fills 09:30 open; live filled ~10:21 on 2026-08-25) | `research/entry_timing_backtest.py` → `entry_timing_results.json`. 203 mega-cap RSI2 entries (only names with 1-min bars; 2024-09..2026-08): open→+60m drift **mean +11.8bp / median −3.0bp** (+5m +3.5/−6.8, +15m +4.3/−2.7, +30m +3.0/−3.7, +45m +2.6/−4.5); implied ~51-min live lag **+6.3bp mean**, statistically indistinguishable from zero. IQR ±50–100bp, fat right tail (p95 +350bp, max +12.6% on a single bounce day). Full-trade PF flat across timing (0m 2.27/+164bp vs 60m 2.39/+162bp @5bp — mega-cap bull-inflated, used only for the timing comparison). Sub-$50 sanity check (RH 5-min, n=8, Aug 2026) runs the OTHER way (d60 mean −194bp / median −22bp; late entry bought lower) but is tiny-n. | **No reliable systematic cost — the lag is per-trade entry-price VARIANCE (±50–100bp, ~1–2× the sub-$50 lane's per-trade edge) plus a fat bounce-day tail.** Recommend pre-computing the RSI2 signal at ~09:20 ET (the signal is fully computable from the prior close — needs no current-session data) so market orders fire at 09:30:05. Cheap hygiene, matches the backtest's next-open assumption exactly; **LOW priority** (mean cost ns). Recommendation only — not implemented here. |

---

## Primary portfolio (the 10 headline lanes)

| # | Lane | Asset class | Status | IS PF / OOS PF | Capital | Blocks activation / re-activation trigger |
|---|---|---|---|---|---|---|
| 1 | **RSI2 buy-the-dip** (Robinhood) | Equities (10 ETFs + top-50 S&P100 large-caps) | **LIVE-READY (ACTIVE — enabled, not blocked)** | IS 1.42 (thr5) / OOS 1.47 walk-fwd (all 5 folds >1.0); 1.36 @5bps, 1.26 @10bps · SPY IS 2.00 / OOS 2.04 | ~$700 Robinhood **whole-share small-ticket** (VPS `rh_client` single-writer; `live_equities.py` feeds signals, gated `exec=LIVE`; **$675 buying power live**) | **Paper-trade ≥30 days on a small-ticket liquid sub-universe** (enabled, not blocked — 20-pos hard ceiling / 5–15 recommended). Index regime gate already validated-**REJECTED** (do not re-add); bear-year warning (2008 PF 0.36 / 2022 0.81) stays on signals. Whole-share sizing at $700 = sub-$35 names, ~5–15 concurrent, 5%/name satellite cap. Plan: `docs/ROBINHOOD-LIVE-PLAN.md`; sizing: `docs/SMALL-CAPITAL-LIVE-PLAN.md`. |
| 2 | **Index Donchian + RSI2-LONG + RSI2PT + REV2** (MES/MNQ/MYM) | Index futures | **LIVE-PAPER** | Donchian IS 1.56 / OOS 1.52 (1.43 @3t) · RSI2-LONG IS 1.99 / OOS 2.57 (1.88 @3t) · RSI2PT (0.5% take-profit) 26y: 89% win, PF 1.92, maxDD mixed vs baseline · REV2 (2-day reversal) @1t: ES 1.54 / NQ 1.62 / YM 1.26, OOS 1.19-1.70, corr vs RSI2 +0.07-0.14 | $350k paper fwd-test sleeve (`live.py`, IBKR paper, **Gate 5 session 1/10 starts Mon 2026-08-17**) · MYM (micro-Dow) added 2026-08-20 — RSI2/RSI2PT/REV2/Donchian all validated on YM, adds a 3rd non-redundant contract (Dow dips when ES/NQ flat) | **Gate 5 (10 RTH sessions) → Gate 6 shadow → Gate 7 micro-live.** RSI2PT = A/B variant (same RSI2<10 entry, +0.5% broker-side limit exit). REV2 = 2-day reversal (drop >1×ATR, revert/3d exit) — validated 2026-08-19, independent of RSI2. |
| 3 | **Gold Donchian + TSMOM** (GC/MGC) | Gold futures | **LIVE-PAPER** | Donchian IS 1.45 / OOS 1.81 (1.42 @3t) · TSMOM IS 1.37 / OOS 1.73 (1.35 @3t) | $1.5M paper fwd-test sleeve (`live_gc.py`, paper-EXEC clientId 78); MGC micro = realistic live (~$900 margin, $2.3k/stop) | **Real-time metals L1** (GC delayed-on-paper → signal-only until subscribed) **+ MGC micro sizing** (full GC = ~$23k risk/contract). |
| 4 | **Seasonal commodities** (month-of-year) | Commodity futures | **PARKED-PENDING** | IS 1.20 / OOS 1.23 (n=1360), cost-stable @3t | Needs **$5–10k IBKR** (full-size margins: GC $8–12k, PL $3–5k, ZC/ZS $2–3k, HE $1.5–2k); currently ~$500 | **Fund IBKR to $5–10k** (full-size futures margin) **+ ≥5y same-month 2nd source** to cross-confirm (unconfirmable on ~3y IBKR bars). |
| 5 | **5-day momentum** (short-term TSMOM) | Equities | **NO-GO-WITH-REASON** | IS 1.20 → 1.07 @10bps (53k trades, high turnover) | Robinhood (equities) | Cost-fragile at any realistic slippage — dies to ~breakeven at 10bps on 53k trades. **Re-activate only under near-zero-friction execution** (no realistic trigger). |
| 6 | **Single-name Donchian** (20d breakout) | Equities (single stocks) | **NO-GO-WITH-REASON** | pooled IS 1.18 → 1.04 @10bps | Robinhood (equities) | Too noisy on individual names (edge lives in index-level trend). **Re-activate only with a quality+volume-gated universe or materially lower cost.** (ETF variant = LIVE-READY small diversifier, see lane 1 note.) |
| 7 | **Pairs / stat-arb** (Z-score MR) | Equities (market-neutral, 10 liquid pairs) | **NO-GO-WITH-REASON** | IS 1.29 → 1.14 @10bps (win 62%, ~+0.4%/trade) | IBKR (needs short leg) | Requires a short leg: Robinhood cash acct can't short; IBKR paper can but isn't live. **Re-activate = shorting enabled (IBKR live margin) + more capital + wider than 10 pairs.** |
| 8 | **Options credit spreads / iron condors** | Options (defined-risk short premium) | **NO-GO-WITH-REASON** | IS 1.04 synthetic (IV=realized, no premium) / 1.48 @15% vol premium · OOS n/a | Robinhood (needs Level 3 + $5k) | Two blockers: **paid historical options archive** (verify the index vol-premium edge) **+ capital ≥$5k** (SPY/QQQ spread ≤5% acct) **+ Robinhood Level 3** (spreads). |
| 9 | **Gap fade** (2% gap-down, 5d hold) | Equities | **NO-GO-WITH-REASON** | IS 1.34 → 1.26 @10bps (win 55%); same-day fade 0.99 @10bps; futures GAP_FADE OOS 0.94 | Robinhood (equities) | Redundant with RSI2-dip (same buy-the-dip exposure, RSI2 stronger + fully validated). **Re-activate only if shown non-redundant** (a regime the RSI2 lane doesn't cover). |
| 10 | **Intraday VWAP** (2σ reversion) | Index futures (MES/MNQ) | **LIVE-PAPER** (scoped equity-index sleeve, paper-EXEC) | Volume filter unlocks equity-index sleeve: group OOS 1.11–1.38 @1t (S&P/Nasdaq/Dow/Russell, stable across VWAP_K 1.5–2.5); Metals 0.94 / Energy 0.97 fail → cross-asset NO-GO (metals/energy stay excluded) | $25k paper intraday sleeve (`live_vwap.py`, clientId 79, `VWAP_EXECUTION=PAPER` real fills, MES/MNQ) | **Re-activated 2026-08-18 per laptop directive as the scoped sleeve.** 1-min 24mo re-validation BLOCKED (IBKR paper 1m ≈30d cap — no 24mo source). Forward-testing on the validated 5-min timeframe. `research/LANE10_VWAP_SWEEP.md`, `research/LANE10_VWAP_SLEEVE.md`. |

---

## Additional lanes (retired / shelved / research — NOTHING removed)

| # | Lane | Asset | Status | IS PF / OOS PF | Reason / re-activation trigger |
|---|---|---|---|---|---|
| 11 | Bonds fade-SHORT (ZB/ZN) | Rates futures | **NO-GO-WITH-REASON** (KILLed, `live_bondsfx.py` disarmed) | RSI2SHORT IS 1.05 / OOS 1.31 → 0.94 @1t, 0.85 @2t · BBANDSHORT 0.99 / 1.01 | Dies at 1-tick slip (avg trade ~$28 on $1000/pt). **Re-activate only if cost/rate-regime materially changes.** |
| 12 | BBAND_INDEX_LONG | Index futures | **NO-GO-WITH-REASON** (TABLED) | IS 1.84 / OOS 1.71 | Redundant with RSI2-LONG (corr 0.69, 73% overlap). **Re-activate if RSI2-LONG underperforms live.** |
| 13 | Crypto momentum — Donchian-20 (`MOM20`) | Crypto | **LIVE-PAPER** (`crypto_exec.py` paper-EXEC) | BTC 1.17 / ETH 1.35 / SOL 2.30 / XRP 3.23 OOS PF | Pure Donchian-20 channel (entry close>20d-high, exit close<20d-low or 2×ATR stop), **NO 200d-SMA** (that filter was the buy-and-hold proxy). Universe BTC/ETH/SOL/XRP. Marginal on BTC/ETH; edge lives in alts (SOL/XRP forward-collecting candles). LOWEST live-priority (owner distrusts crypto). |
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
| 24 | KAMA crossover (daily re-test) | Index futures / index ETFs | **NO-GO-WITH-REASON** (confirmed on daily) | 2-3d hold OOS 0.75–1.16 @5bps (<1.1 @10bps everywhere); pure-cross OOS 1.3–1.7 is bull-regime proxy (IS<1.0) w/ maxDD −12..−61% | 2-3 day hold (owner's swing horizon) net-negative after costs; untimed cross = buy-and-hold bull proxy + unacceptable DD. **No realistic re-activation** (contradicts capital-preservation directive). `research/LANE24_KAMA_DAILY.md`. |
| 25 | 5-day reversal | Equities | **NO-GO-WITH-REASON** | IS 1.46 pooled / OOS 1.31 (regime-flipped: SPY 2.93 → 0.94 post-2009) | Regime-flipped + inconsistent across symbols. |
| 26 | Golden cross (50/200) | Equities | **NO-GO-WITH-REASON** | IS 3.57 / OOS 3.20 (n=88) | Statistically meaningless (n=4–7 OOS/symbol despite inf PF). |
| 27 | Bollinger lower-band | Equities | **NO-GO-WITH-REASON** | IS 1.42 / OOS 1.11 | 0.72 corr with RSI2 — redundant, do not co-deploy. |
| 28 | 200d MA trend | Equities | **RESEARCHING** (HOLD) | IS 1.99 pooled / OOS 2.42 (n=538) | Regime overlay, thin standalone (SPY OOS n=29). Use as a filter, not a signal. |
| 29 | 12m XSMOM long-only (equities) | Equities | **RESEARCHING** (candidate) | IS 1.80 / Sharpe 0.78, ann +14.4% | Side-finding from lane 17 — real long-only edge, needs a 50-name monthly-rebalanced book (future funded-account idea). |
| 30 | Forex spot (28 pairs) | FX | **RESEARCHING** (data-only) | n/a | No edge/broker yet. Daily + 1h → `yf/fx/` for future research. Schwab API on hold. |
| 31 | Futures-options chain scaffold | Options on futures | **RESEARCHING** (scaffold) | n/a | Chain metadata for 12 underlyings only; vol-surface/greeks need paid bars (not requested). |
| 32 | **Order-flow / microstructure** (Creamer 4-step auction) | Index futures (MNQ 5-min) + small-ticket equities | **RESEARCHING** (data + signal-only, exec=NONE) | n/a (no backtest yet) | Collecting orderbook depth (IBKR L1-only — L2 not entitled; RH L2 price book for 15 names) + ticks (`kind`-tagged) + 1-min bars; footprint features (delta/absorption/value-area/imbalance/spread) → `MICRO#`; Creamer auction generator → `AUCTION#MNQ`. **Scheduled 2026-08-20** (cron 19:30/19:35 ET: `microstructure_engine.py` + `auction_signals.py`; were unscheduled → MICRO# went stale, AUCTION# never ran). **Calibration finding 2026-08-20:** fixed the `golden_pocket_outside_value` gate (dead code — never fires on same-session data); but the 6-condition AND-gate (participation + env + in-pocket + discount/premium + shift-of-dominance + absorption) has ~0 joint hit-rate → **0 setups**. Next = score/threshold re-approach or footprint-quality (bid/ask-at-price) data, NOT further hard-gate loosening. `docs/ORDERFLOW-LANE.md`. |
| 33 | **2-3 day short-term reversal (LONG-only)** | Index futures (ES/NQ/YM) | **LIVE-PAPER** (deployed 2026-08-19) | N=2 @1t: ES PF 1.54 / NQ 1.62 / YM 1.26, OOS 1.19-1.70 · **+200d-SMA filter: ES PF 2.07 maxDD -$14k / NQ 2.04 -$26k (halved)** · win 75-79% · hold 3.4d · survives 3-tick | Buy an N-day drop >1×ATR (N=2), **close > 200d SMA** (Connors filter, same as RSI2), 2×ATR stop, revert-to-entry or 3d exit. **Independent from RSI2** (corr +0.07-0.14, 19-21% overlap). ⚠️ **Long-beta caveat:** whole family (RSI2/RSI2PT/REV2) is "buy the dip in a bull market" — drift-inflated PFs, loses in bears (2022 PF 0.48); the SMA filter is the mitigation (skips falling knives). RTY fails. |
| 34 | **Donchian L-day breakout (L=2/3/5)** | Index futures | **NO-GO-WITH-REASON** (2026-08-19) | LONG-only PF 0.87–1.29 (mostly ~1.0, breakeven) · LONG+SHORT 0.77–1.03 (clearly losing) | Short-horizon breakout/momentum has no edge — confirms Lou-Polk-Skouras (momentum alpha is overnight, not intraday/short). Long-only breakeven, long-short loses net on every index. Dies at cost. **No reactivation.** |
| 35 | **Cross-asset 1-month TSMOM** (Zaremba "short-term momentum almost everywhere") | Futures (29-contract: index/rates/energy/metals/ags) | **NO-GO-WITH-REASON** (2026-08-20) | Vol-scaled equal-risk portfolio: **Sharpe 0.23, CAGR +2.2%, maxDD −62%**, flat/negative 2013–2026 · naive pooled PF 1.01–1.10, OOS 1.01 (train 1.40 → validate 0.94) | The academic 1-month momentum premium is statistically significant but **economically dead on our universe**: Sharpe 0.23 is noise, −62% maxDD fails drawdown-first instantly, and ALL the profit is pre-2012 commodity-supercycle (post-2012 flat/negative). Cost-fragile (12.6x annual turnover). Consistent w/ every short-horizon momentum test we've run. **No reactivation.** `research/cross_asset_momentum.py` + `cross_asset_momentum_volscale.py`. |
| 36 | **Cross-sectional short-term reversal** (large-cap losers, de Groot/Huij/Zhou + FIM) | Equities (38 S&P100 large-caps) | **NO-GO-WITH-REASON** (2026-08-20) | Gross (L=5d/H=5d) Sharpe 1.07–1.13, CAGR +29–31% · **@5bps Sharpe 0.83–0.90, @10bps 0.58–0.67** · maxDD **−54% to −69%** | Confirms the literature (reversal survives GROSS in large caps) but weekly rebalance (~52×/yr bucket turnover) kills it at cost, and a long-only "buy-losers" bucket catches falling knives (2008 −42%, 2022 −21%, 2011 −34%) → drawdown-fatal, and redundant with live RSI2/REV2 (same buy-the-dip-in-large-caps exposure, but those carry a 200d-SMA filter + stops). **No reactivation.** `research/cross_sectional_reversal.py`. |
| 37 | **"9AM/8AM CR Model"** (Candle-Range liquidity-sweep fade, Massimo/ICT-SMC turtle-soup) | Index futures (MES/MNQ/ES/NQ 5-min, 1y) | **NO-GO-WITH-REASON** (2026-08-21) | Opening-range sweep fade: win **15–25%** (NOT the claimed 60–70%), gross R **−39.8 to +21.1** (symbol-inconsistent), dies at **1 tick** RT cost · top-5 outlier trades = all apparent edge | Research-first backtest of the influencer "9am CR model": mark a reference range, wait for a liquidity sweep ("turtle soup") of one extreme, fade to the opposing end. Tested the mechanically-identical opening-range variant (08:00–09:00 pre-open hour not in our RTH-only bar store) across range 15/30/60m × buffer × opposing/EQ target. **No robust edge**: high-ish win-rate reading was a sign bug (corrected), true win rate ~15–25%, gross expectancy ~0/negative, MES (+39.8R) and ES (−21.1R) diverge on the SAME setup (same index → noise), and every positive is ~5 outlier trades. Same family as our Creamer auction + VWAP reversion — but the mechanical sweep-fade framing adds nothing. **No reactivation.** `research/cr_model_backtest.py`. |
| 38 | **VWAP 2σ reversion on SPY/QQQ fractional** (the "trade more often" intraday candidate) | Equities (fractional ETFs, RH) | **NO-GO-WITH-REASON** (2026-08-24) | SPY OOS PF **0.84–1.06** · QQQ full-year OOS **0.82–1.08** (a 6-month window flattered at 1.16–1.47) · ~1–4 trades/day | Tested whether the validated *futures* VWAP 2σ edge (OOS PF 1.11–1.38 on ES/NQ) transfers to SPY/QQQ fractional (what $700 can actually trade). Real IBKR 5-min RTH bars, $0-comm + 1-cent tick cost. **It does NOT survive**: full-year OOS is breakeven on both, matching the original futures verdict (Nasdaq marginally positive, S&P negative → cross-asset NO-GO). The 6-month QQQ read was a favorable window, not a robust edge. Confirms the recurring pattern: intraday reversal edges die at cost / are breakeven. **No reactivation.** `research/vwap_spy_backtest.py`. |
| 39 | **Turn-of-month (calendar) seasonal** | Equities (SPY/QQQ/DIA/IWM/VTI ETFs) | **NO-GO-WITH-REASON** (2026-08-24) | TOM_LONG (last-day + first-3-days, 4d hold) @5bps PF 1.27 / OOS 1.28, win 56%, n=1690 — but that's long-beta drift (4-day drift benchmark alone +15.9bps / 60% win). TOM_LS (market-neutral: long-TOM short-mid-month, strips drift) PF **0.96**, win 46%, **−5.5bps/trade**, OOS 0.96 → loses after cost. @10bps the L/S is negative at every level. | Real-but-tiny (~5–10bps) drift-inflated seasonal: the TOM-minus-mid-month spread is entirely eaten by 2-leg round-trip cost. **No reactivation.** `research/turn_of_month_backtest.py`. |
| 40 | **Intraday single-name reversal** (mega-caps, 1-min) | Equities (16 liquid names) | **NO-GO-WITH-REASON** (2026-08-24) | Entry on return-from-open ≤ −1.0/−1.5/−2.0%, 2% stop, EOD flatten, next-bar fill + 1¢ slip: win 43–45%, PF 0.89–0.93 @5bps (0.78–0.82 @15bps), OOS 0.87–0.92, expectancy **−6 to −10bps/trade**. | Intraday dips in single mega-caps *continue* (momentum), they don't revert — consistent with the killed index/ETF fades and the "premium is overnight, not intraday" structural finding. First intraday test on single equities (vs prior index-futures/ETF fades). **No reactivation.** `research/intraday_reversal_single_name_backtest.py`. |
| 41 | **Post-earnings announcement drift (PEAD)** | Equities (190 liquid, 2018–2026) | **NO-GO-WITH-REASON** (2026-08-24) | 6,193 events ~8.5y (via backward-paged `get_earnings_calendar`). Short-miss PF **0.76 / OOS 0.65** (missers drift UP, not down). Long-beat PF 1.49 / OOS 1.74 but = beta (unconditional drift +99.0bp ≈ beater +104.8bp → beating adds only +5.8bp). Beat−miss spread +13.6/+32.3/+12.2/+26.4bp @+1/+3/+5/+10d, t-stats 1.17/1.70/0.53/0.85 (none significant); @20bp cost the +1d/+5d spreads flip negative. | PEAD's core mechanism is absent — missers gap down −198bp then *bounce* +78bp/10d (reversal, not continuation), already covered by the mean-reversion sleeves. Long-beat = beta not signal. Data caveat: 82% beat rate → Robinhood's estimate is systematically low, biasing surprise sign. **No reactivation.** `research/pead_backtest.py`. |
| 42 | **Relative volume (RVOL) high-volume premium** (Gervais-Kaniel-Mingelgrin 2001, JF) | Equities (SPY 33y + 187 liquid names 20y) | **NO-GO-WITH-REASON** (2026-08-24) | Cross-sectional top-vs-bottom-decile RVOL spread **+0.06%** gross @1d / +0.07% @3d / +0.06% @5d, hit-diff ≈0 → **dies at 5bps** (net −0.04% to −0.14%). Time-series (SPY): high-vol days (RVOL≥2) fwd1d **+0.19%** vs low-vol **+0.04%** vs all **+0.04%** — real but LONG-only market-timing overlay, rare (281 signals / 33y). | GKM effect peaks at 1–3 weeks; the 1–5d front-end is too weak to survive cost cross-sectionally. Time-series is a genuine but rare long-only volume-timing overlay, not a breadth/“trade-more-often” edge. **No reactivation as cross-sectional; time-series = weak overlay (deferred).** `research/rvol_backtest.py`. |
| 43 | **Alt-data signal engine** (news/sentiment/fundamentals/screener → 1–5d edge) | Equities (189 liquid, 20y) | **NO-GO-WITH-REASON** (2026-08-24) | 8 signal ideas × 4 horizons. Alt-data feeds too thin to backtest point-in-time (newsapi 4 objs / news-archive 4d / fmp 3d / rh-research 1 snapshot). OHLCV reconstruction of screener fields: relative-volume spread ≈0bps PF ~1.0 (zero signal); DAILY_GAINERS underperform −4 to −22bps (reverses); losers/52wk-low outperform (5d PF 1.51) = RSI2 already live; 52wk-high/5d-momentum = no alpha. Critical honesty: every "GO-looking" bucket is beta (equal-weight benchmark OOS 5d PF 1.45); alpha ≈0 for every feed. | Alt-data is already-priced at 1–5d; the only edge is reversal (already deployed). Survivorship-bias caveat makes all effects upper bounds. **No engine build — redirect to VIX term-structure + overnight structure instead.** `research/signal_engine_sweep.py`. |
| 44 | **VIX term-structure slope** (Fassas & Hourvouliades 2019) | Equities (SPY index) | **NO-GO-WITH-REASON** (2026-08-24) | VIX/VXV 2-point slope proxy (VXVCLS 2007–2026, n=4708): backwardation (VIX>VXV, ratio>1) does NOT predict higher fwd returns — ratio>1.05 (n=187) 5d +0.07% vs baseline +0.21%; extreme ratio>1.20 (n=43) 5d **−1.24%** / 10d **−2.57%** (crisis momentum, not bounce). Contrast spot-VIX *level* (Simon-Wiggins 2001): VIX z≥2.0 → SPY 5d **+0.78%** vs +0.20% baseline (n=594). | Term-structure slope does not replicate on 2007–2026 data (2-point proxy; Fassas used full VX curve 2004–2018 — likely decayed like other post-publication anomalies). Robust signal = spot-VIX **level** (fear), not slope. **No VX futures collector. Spot-VIX contrarian = candidate long-only timing lane.** `research/vix_term_structure_backtest.py`. |
| 45 | **Spot-VIX level contrarian** (Simon-Wiggins "fear premium", VIX z-score) | Equities (SPY/QQQ + lev SSO/UPRO/TQQQ) | **NO-GO-WITH-REASON** (2026-08-24) | Tradeable lane (dedup, 5d hold, z≥2): SPY 1y-window **IS PF 1.55 / OOS PF 0.95** @5bps (n=182); 2y-window IS 1.72 / OOS 1.09; @10bps OOS **0.80–0.92**. QQQ OOS 1.00–1.16. Leveraged OOS **0.80–1.03** (dedup). Every construction OOS < 1.3. 2×ATR stop *hurts* (SPY close+stop OOS 0.95–0.97, leveraged ≤0.96). | The upstream "+0.78%/5d, n=594" was IS-dominated (1993–2019 PF 1.55–1.72) and gross/overlapping. The 2020–2026 OOS is breakeven-to-negative after cost: the 2022 bear = repeated falling knives (buy-the-VIX-spike fails when the dip keeps dipping). 2×ATR stop cuts the bounce short, not a fix. **Redundant with live RSI2 buy-the-dip (lane 1)** — same fear-dip long-beta exposure, and RSI2 already carries the SMA200 filter that would be needed here. **Re-activate only if OOS PF ≥1.3 is sustained on fresh data or a non-redundant regime filter emerges.** `research/vix_level_backtest.py`. |
| 46 | **MOC entry refinement** (RSI2 family: close/MOC entry vs deployed next-open entry) | Equities (189 liquid names) | **NO-GO-WITH-REASON** (2026-08-24) | Overnight gap (close−open entry) = mean **+11.0bp / median +9.5bp**, skew +0.65, 55% of gaps >0, **stable IS→OOS (+9.7→+12.8bp)** — the close-entry edge is real and median-driven, not outlier-driven. But MOC slippage eats it: @5bp slip MOC wins 52.8% (+6.0bp net), @10bp 49.7% (+1.0bp), @15bp 46.9% (−4.0bp). | (a) Robinhood — where the $700 RSI2 sleeve runs — has **no MOC order type**, so it is not actionable on the primary venue. (b) On IBKR, MOC fills at the closing auction: liquid large-caps (half-spread 1–6bp < 9.5bp gap) → +5.5–9bp net, but the sub-$35 small-ticket names the sleeve trades (half-spread 5–20bp ≥ gap) → **net −1.5 to −3bp**. Deployed next-open entry unchanged. **Re-activate only if the sleeve moves to IBKR with a liquid large-cap sub-universe (not sub-$35), where MOC adds ~+5–9bp/trade.** `research/moc_entry_validate.py` + `research/overnight_structure_backtest.py`. |

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
- Lane 10 (definitive sweep): `research/LANE10_VWAP_SWEEP.md`.
- Lane 24 (daily re-test): `research/LANE24_KAMA_DAILY.md`.
- Lane 14: `bot/wheel_backtest.py`, `research/OPTIONS_PLAN.md`.
- Lanes 39–41 (subagent edge-hunts 2026-08-24): `research/turn_of_month_backtest.py`, `research/intraday_reversal_single_name_backtest.py`, `research/pead_backtest.py`.

---

## Lane 47 — BROKEN ARROW (buy the big-down close, sell the next open) — RESEARCHING, strongest candidate

Source: Alvarez, via `research/edge-research-20260825/PRACTITIONER_CODE_CANDIDATES.md` #2.
Backtest: `research/candidate_backtest.py` → `research/candidate_backtest_results.json`.
375 symbols, 2006-2026, sub-$50 only, dollar-vol > $5M, LONG-ONLY, 6 bp round-trip, OOS from 2022.

Rules: setup = prev close > 40-day MA AND 40-day MA rising. Trigger = today closes down ≥ X%.
Entry = that day's CLOSE (~15:55). Exit = the NEXT OPEN. No stop needed (1 overnight hold).

| drop | trades | PF | win% | net/trade | t | OOS n | OOS net | **OOS t** |
|---|---|---|---|---|---|---|---|---|
| −5% | 13,306 | 1.151 | 52.8% | +14.8 bp | 4.67 | 6,976 | +9.4 bp | 2.25 |
| **−8%** | **4,174** | **1.423** | **56.2%** | **+49.6 bp** | **6.41** | **2,386** | **+34.4 bp** | **3.96** |
| **−10%** | **2,144** | **1.552** | **56.7%** | **+73.6 bp** | **5.56** | **1,231** | **+54.0 bp** | **3.85** |
| −15% | 621 | 1.887 | 58.0% | +135.6 bp | 3.88 | 359 | +73.2 bp | 2.20 |
| −20% | 232 | 2.337 | 57.3% | +225.7 bp | 2.85 | 142 | +103.6 bp | 1.72 |

**INDEPENDENT REPLICATION:** Alvarez reports +0.77%/trade, 56% winners at −15% on top-1000.
We get **+1.36%/trade, 58.0% winners** full-sample and **+0.73% OOS** on a sub-$50 universe —
i.e. his headline number reproduces almost exactly out-of-sample on different data. That is the
strongest external corroboration any lane in this registry has.

**−8%/−10% is a better operating point than his published −15%:** 7× and 3.5× the trade count
with the highest OOS t-stats on the table (3.96 / 3.85).

Why it fits this account: buys at the CLOSE, which is the CHEAPEST window we measured
(1.9 bp buy half-spread at 15:45-16:00 on 2026-08-25, vs 3.6 bp mid-session and 18.1 bp in the
16:00-16:05 auction). Long-only, whole-share, no stop required, both legs inside regular hours.
Corroborates the same overnight-drift mechanism that made `close_to_open_backtest.py` NEARLOW
(+3.94 bp OOS) work and that killed the pre-close exit (Lane 46 revert).

**BLOCKER before any capital — one honest gap:** the 1.9 bp buy half-spread was measured on
NORMAL names. This strategy deliberately buys names that just fell 8-15% in a day, whose closing
spread will be materially wider. Cron `478789a67115` samples 15:50-16:00 and 09:30-09:40 at
1-minute resolution; the specific test needed is **the closing spread on names down ≥8% that
day**. Edge is +34 bp OOS, so it tolerates far more cost than the 8 bp close-to-open trade —
but it must be measured, not assumed. NO capital until then.

## Lane 48 — MIND THE GAP (buy gap-down open above 200SMA, sell next open) — RESEARCHING, weaker

Source: Quantitativo, ibid. #1 (author withheld his gap threshold; we swept it).
Same script/data. Cap 7 names/day, least-volatile first, both legs at the open.

| gap ≤ | trades | PF | net/trade | t | portfolio bp/day | OOS PF | OOS net | OOS t |
|---|---|---|---|---|---|---|---|---|
| −1% | 21,672 | 1.140 | +13.1 bp | 6.24 | +13.5 | 1.092 | +6.8 bp | 1.04 |
| −3% | 6,358 | 1.167 | +29.0 bp | 4.14 | +20.7 | 1.098 | +16.0 bp | 0.96 |
| −4% | 3,620 | 1.301 | +59.8 bp | 5.28 | +30.2 | 1.111 | +22.7 bp | 0.98 |
| −7% | 1,040 | 1.472 | +126.5 bp | 4.36 | +55.3 | 1.026 | +7.9 bp | 0.16 |

Cost-robust at −3% (PF 1.167 @6bp → 1.083 @20bp, t still 2.14). BUT every OOS day-level
t-stat is ≈1.0 or below — the post-2022 evidence does not clear significance, consistent with
the author's own admission that he excluded pre-2010 because it was "significantly better"
(i.e. documented decay). **Ranked BELOW Broken Arrow. Do not build yet.**

## Lane 49 — Unconditional close-to-open — NO-GO (confirmed twice)

`research/close_to_open_backtest.py`: buying every sub-$50 name at the close and selling the
next open returns +1.55 bp/trade at 6 bp with a MEDIAN of −6.00 bp, and is negative from 10 bp.
Independently confirmed by Basdekidou (2017), open-access, SPY 1993-2011, 4,624 trades: 9.23%/yr
gross, Sharpe 0.89 — but the author states $0.02/share commission makes total net profit
NEGATIVE, and $0.01/share destroys 57% of gross. **The overnight premium is not harvestable
unconditionally.** The edge requires the weak-close / big-drop conditioning of Lanes 47/49-adjacent
variants (NEARLOW +3.94 bp OOS t=5.30, DOWN3 +4.24 bp OOS t=3.06).

## Lane 50 — Extended-session (24h/overnight) execution — NO-GO-WITH-REASON

`research/overnight_24h_gonogo.py`: does ANY overnight-hold edge in this repo clear the
**51.5 bp** measured extended-session round-trip (vs **14.4 bp** RTH, `overnight_cost_floor.json`,
3.42×)? Sub-$50 universe, 383 symbols, 2006–2026, LONG-only, OOS from 2022, per-trade net PF.

| candidate | IS PF @51.5bp | OOS PF @51.5bp | OOS avg bp |
|---|---|---|---|
| Gap-fade −7% | 1.641 | **1.193** | +61.2 |
| Gap-fade −4% | 1.287 | 1.136 | +32.7 |
| Broken Arrow −10% | 1.399 | 1.062 | +9.1 |
| Gap-fade −3% | 1.125 | 1.039 | +8.7 |
| Broken Arrow −8% | 1.210 | 0.921 | −10.9 |
| ALL close-to-open variants (incl. RSI2) | 0.44–0.59 | 0.49–0.53 | −34 to −44 |

**Nothing clears PF ≥ 1.3 OOS at the extended-session floor** (best OOS PF 1.193, gap-fade −7%).
The same edges DO survive RTH cost: at 14.4 bp, Broken Arrow −10% OOS PF **1.362** and gap-fade
−7% **1.328** — and even at 2× RTH (28.8 bp) −10% OOS 1.236 / −7% OOS 1.274. So the overnight-hold
*edge* is real but must be traded **regular-hours close → regular-hours open**, which Lanes 47
(Broken Arrow) and 48 (Mind the Gap) already do. There is no additional edge worth paying 3.42× to
trade *inside* the 16:05–20:00 evening or pre-market sessions (evening = 0.73–0.88% of daily volume,
RH stops RTH-ONLY ⇒ any such position is an unstopped gap; no sizing rule makes an unstopped −10 bp
expectancy worth it).

**Re-activate only if** a candidate shows median gross edge ≫ 51.5 bp OOS, or the measured
evening/overnight cost falls below the edge (not expected — 51.5 bp is already a *floor*, sampled
at peak extended-hours liquidity).

## Lane 51 — RH RSI2 position-sizing & concurrency validation (15%×5) — NO-GO-WITH-REASON

`research/position_sizing_backtest.py`: validates the 2026-08-25 RH sizing change
(`RH_MAX_POS_PCT` 0.05→0.15, `RH_MAX_POSITIONS`=5) on the DEPLOYED sub-$50 universe
(488 usable symbols, 2006–2026, 13,869 RSI2<5 trades, next-open entry, 2×ATR stop,
5d/revert exits, $700 whole-share + cash-constrained, IS/OOS split at 2022).

**Per-trade edge (equal-weight, registry convention):** @5bps/side **PF 1.097 (IS 1.120 / OOS 1.068)**, win 63.1%; @10bps **1.034 (IS 1.048 / OOS 1.016)**. The sub-$50 RSI2
edge is real but THIN — well below the large-cap walk-forward OOS 1.36 @5bps this lane was
promoted on (Lane 1 / `stock_mr_validate.py`), i.e. the validated edge lives in large caps, not
the sub-$50 names whole-share reality forces.

**Portfolio grid @5bps/side — PF / IS / OOS / maxDD** (whole-share $700, cash-constrained):

| config | PF | IS | OOS | maxDD |
|---|---|---|---|---|
| 3 × 15% | 0.984 | 1.02 | 0.91 | −20.5% |
| **5 × 15% (LIVE)** | **0.968** | 0.99 | **0.91** | **−43.1%** |
| 5 × 5% | 1.003 | 1.02 | 0.97 | −17.4% |
| 10 × 5% | 1.034 | 1.04 | 1.02 | −28.5% |
| **20 × 5% (best)** | **1.069** | 1.05 | **1.09** | **−30.9%** |

- The deployed **15% × 5 is near the WORST cell**: PF 0.97, OOS 0.91, maxDD −43%, net −$200.
  Best is **5% × 10–20 concurrent** (PF 1.03–1.07, OOS ~1.0–1.09, maxDD −17..−31%). Higher
  pos_pct → monotonically worse PF and much deeper maxDD at every concurrency level.
- @10bps stress the live cell falls to **PF 0.915 / OOS 0.83 / maxDD −62.8%**.
- Clustering is structural: **67.8% of entries occur on days with ≥5 simultaneous signals**
  (median 3/day, p90 10/day, max 63/day) — so 5 concurrent = one correlated long-beta dip bet,
  and 15% sizing amplifies it.

**Answers:** (a) NO — 15%/5 over-concentrates; use ~5%/name with ≥10 concurrent (or fractional
shares). (b) The 9-vs-5 fill was a code bug, not a backtest question: the book (`RHPOS#`) stayed
empty when the LIVE confirm path failed → `committed` started 0 → the cap never bit. FIXED
2026-08-26 in `bot/live_equities.py` with a broker-authoritative count (`committed =
max(committed, len(broker_positions))`, fail-closed to `pos_cap` on read error). (c) Optimal
concurrency ≈ 10–20 at 5%, NOT 5 at 15%.

**Re-activate trigger:** revert `RH_MAX_POS_PCT` ≤ 0.10 (ideally 0.05 with fractional shares or a
sub-$35 whole-share universe) and raise `RH_MAX_POSITIONS` ≥ 10; re-validate the deployed sub-$50
universe edge (OOS 1.068 @5bps is barely above breakeven) before adding any capital to the lane.

## Lane 52 — Pre-FOMC announcement drift (Lucca & Moench 2015) — NO-GO-WITH-REASON

`research/pre_fomc_backtest.py` → `research/pre_fomc_results.json` + `research/fomc_calendar.json`
(263 scheduled meetings 1994-2026 scraped from federalreserve.gov; unscheduled/cancelled/conference-call
excluded). LONG SPY/QQQ at close of the trading day BEFORE the FOMC announcement day, EXIT at close of
the announcement day (1-day hold). Round-trip bps deducted; PF on net returns.

| universe | n | mean/trade @5bp | t | PF @5bp | IS / OOS (60/40) | ≥2016 PF @5bp | ≥2016 t | ≥2016 PF @10bp |
|---|---|---|---|---|---|---|---|---|
| SPY (1994-2026) | 259 | +19.3 bp | 2.67 | 1.580 | 1.91 / 1.15 | **0.997** | **-0.01** | 0.880 |
| QQQ (1999-2026) | 218 | +29.6 bp | 2.58 | 1.658 | 1.78 / 1.47 | 1.399 | 1.12 | 1.276 |

**The 24h pre-FOMC drift replicates in-sample (SPY t=2.67, QQQ t=2.58 full-sample) but is DEAD
out-of-sample on SPY** — the canonical instrument. SPY ≥2016: PF 0.997 @5bp, t = −0.01 (pure noise);
@10bp it is clearly negative (0.88). QQQ ≥2016 stays positive (PF 1.40) but statistically insignificant
(t=1.12) and falls below the **1.3 OOS bar at 2× cost** (PF 1.276 @10bp). The ≥2019 QQQ read (PF 1.76,
t=1.65) is beta-inflated: QQQ's *unconditional* 1-day drift is already +5.25 bp (vs SPY +4.07 bp), so the
"premium" is partly the mega-cap bull, not the announcement.

Presser/non-presser split confirms Kurov 2020 "the disappearing drift": the effect is IS-dominated (SPY
presser IS PF 4.61 collapses to 1.10 post-2016; non-presser post-2016 PF 0.07–0.37). The drift only
*ever* existed pre-2016, and it has not returned on the 8-presser/yr schedule.

**Verdict:** NO-GO. The famous pre-FOMC drift is a real-but-decayed anomaly — it reproduces the
Lucca-Moench headline on 1994-2015 data, then vanishes OOS (2022 bear = the "dip before the meeting"
kept dipping). It is also a **long-beta timing overlay** (1-day hold, long-only, 8×/yr), redundant with
the RSI2/REV2 dip-buying family, and would need a close-of-day entry on the primary venue that already
lacks MOC (Lane 46). **Re-activate only if** OOS PF ≥1.3 at 2× cost is sustained on fresh data (≥2027)
and it is shown non-redundant with the dip-buying sleeves.

## Lane 53 — Macroeconomic announcement-day premium (Savor & Wilson 2013) — NO-GO-WITH-REASON

`research/macro_announcement_premium.py` → `research/macro_announcement_results.json` +
`research/macro_release_dates.json` (ALFRED keyless release dates: CPI rid=10, PPI rid=46,
Employment Situation rid=50, downloaded 2026-08-27) + `research/fomc_calendar.json`. LONG
SPY/QQQ at the CLOSE of the trading day BEFORE a scheduled macro release (CPI/PPI/NFP/FOMC),
EXIT at the CLOSE of the announcement day (1-day hold, close-to-close). Round-trip bps
deducted; PF on net returns.

| universe | subset | n | mean/trade @5bp | t | PF @5bp | IS / OOS (60/40) | ≥2016 PF @5bp | ≥2016 PF @10bp |
|---|---|---|---|---|---|---|---|---|
| SPY (1993–2026) | ALL (CPI+PPI+EMP+FOMC) | 1457 | +3.3 bp | 1.03 | 1.082 | 1.13 / 1.01 | 0.962 | 0.849 |
| SPY | non-FOMC only (CPI+PPI+EMP) | 1233 | +1.7 bp | 0.47 | 1.040 | 1.06 / 1.00 | 0.956 | 0.843 |
| SPY | FOMC only | 259 | +19.3 bp | 2.67 | 1.580 | 1.91 / 1.15 | 0.997 | 0.880 |
| QQQ (1999–2026) | ALL | 1206 | +5.0 bp | 0.99 | 1.088 | 1.08 / 1.10 | 1.080 | 0.983 |
| QQQ | non-FOMC only | 1016 | +2.0 bp | 0.36 | 1.034 | 1.03 / 1.04 | 1.037 | 0.942 |
| QQQ | FOMC only | 218 | +29.6 bp | 2.58 | 1.658 | 1.78 / 1.47 | 1.399 | 1.276 |

**Raw announcement-day premium (gross):** SPY announcement-day 1d return **+8.32 bp** vs
non-announcement **+3.19 bp** → spread **+5.12 bp, t=1.46** (ns); QQQ **+10.01 bp** vs
**+4.27 bp** → spread **+5.74 bp, t=1.04** (ns). The Savor-Wilson headline (11.4 bp excess)
shows up directionally but the *spread* does not clear significance on 1993–2026 data.

**Verdict: NO-GO.** The macro announcement premium is real-but-tiny and **not harvestable**:
(a) the on-day spread (+5–6 bp) is statistically insignificant (t≈1.0–1.5) and the tradeable
close-to-close construction nets only **+1.7–5.0 bp/trade @5bp**; (b) **the entire premium is
FOMC-driven** — strip out FOMC and the CPI/PPI/NFP portion is ~zero edge (SPY non-FOMC PF 1.040
/ OOS 1.000, +1.7 bp; QQQ 1.034 / 1.040, +2.0 bp) and turns negative at 2× cost (PF 0.92–0.95);
(c) the FOMC leg is exactly the pre-FOMC drift already killed in Lane 52 (dead ≥2016). No
construction clears **OOS PF ≥ 1.3**; at 2× cost (10 bp) *every* pooled/non-FOMC cell is ≤ 1.0
(SPY ALL OOS 0.885, QQQ ALL OOS 0.998, non-FOMC OOS 0.84–0.94). Redundant with the dip-buying
family and the already-killed FOMC lane. **Re-activate only if** the CPI/PPI/NFP-only spread
reaches significance (t≥2) on fresh post-2026 data net of 2× cost, shown non-redundant with
Lane 52's FOMC drift.

## Lane 54 — Pre-holiday drift (Ariel 1990 / Lakonishok-Smidt 1988) — NO-GO-WITH-REASON

`research/preholiday_backtest.py` → `research/preholiday_results.json`. LONG SPY/QQQ/DIA at the
CLOSE of the trading day BEFORE the pre-holiday session, EXIT at the CLOSE of the pre-holiday
(last) trading day (1-day hold, ~10 RT/yr). NYSE scheduled market-holiday calendar (observed
closure dates, Good Friday via Computus, Juneteenth since 2022, MLK since 1998; special closures
like 9/11/funerals excluded as non-predictable). Round-trip bps deducted; PF on net returns.
IS/OOS = repo 60/40 chronological AND pre-2000/2000+ split.

| universe | n | gross/trade | PF @5bp | PF @10bp | OOS(60/40) @10bp | post-2000 PF @10bp | PF @15bp |
|---|---|---|---|---|---|---|---|
| SPY (1993–2026) | 140 | +16.7 bp | 1.46 (t=1.45) | 1.24 | 1.23 | 1.35 | 1.06 |
| QQQ (1999–2026) | 116 | +26.3 bp | 1.59 (t=1.70) | 1.43 | 1.06 | 1.32 | 1.28 |
| DIA (1998–2026) | 121 | +15.4 bp | 1.40 (t=1.27) | 1.19 | 0.91 | 1.17 | 1.01 |

**Verdict: NO-GO.** The pre-holiday premium reproduces directionally — gross **+15–26 bp/trade**
(~3–4× the +4–5 bp unconditional 1d drift), win 55–61% — and is concentrated in Good Friday
(+34–62 bp), Thanksgiving (+8–40 bp) and Independence Day (+13–18 bp), while New Year is
strongly NEGATIVE (SPY −16.7 bp, QQQ −40.3 bp gross). But it does **not clear OOS PF ≥ 1.3 at
2× cost**: at 10 bp round-trip the 60/40 OOS PF is 1.23 / 1.06 / 0.91 (SPY/QQQ/DIA) and
post-2000 is 1.35 / 1.32 / 1.17 (DIA fails); at 3× cost (15 bp) every construction is ≈1.0 and
OOS < 1.0. It is a ~10-trade/yr **long-beta 1-day timing overlay** with weak statistical
significance (t=1.3–1.7, none clears 2.0), and the post-holiday reopen day is ALSO positive
(+13.6 / +29.2 / +19.4 bp) — the literature's "negative post-holiday" contra-leg does not hold
in modern data either. Redundant with the dip-buying family / long-beta exposure. **Re-activate
only if** a construction shows OOS PF ≥ 1.3 at 10 bp sustained on fresh data (≥2027) and is
shown non-redundant with the beta/dip-buying sleeves (e.g. a Good-Friday-only or
holiday-cluster variant carrying its own beta hedge).

## Lane 55 — Day-of-week overnight seasonality (Lin 2025 AEF; Kallinterakis et al. 2023) — NO-GO-WITH-REASON

`research/dow_overnight_backtest.py` → `research/dow_overnight_results.json`. LONG SPY/QQQ/DIA
at the CLOSE of a given weekday, EXIT at the NEXT trading day's OPEN (close→next-open overnight).
Tests Mon→Tue (the paper's positive night), Fri→Mon weekend (the paper's negative night), a
3-night Mon/Tue/Thu model, and an every-night benchmark. Cost swept 5/10/15/20 bp round-trip
(5.9 bp = the measured RTH floor, `overnight_cost_floor.json`); IS/OOS = 60/40 chronological +
pre-2000/2000+ split; PF on net returns.

| sym | night | gross bp | PF @5bp | PF @10bp | OOS(60/40) @5bp | post-2000 @5bp |
|---|---|---|---|---|---|---|
| SPY | MON→TUE | +6.5 | 1.076 | 0.838 | 1.151 | 1.045 |
| QQQ | MON→TUE | +8.0 | 1.119 | 0.930 | 1.230 | 1.101 |
| DIA | MON→TUE | +6.3 | 1.067 | 0.837 | 1.195 | 1.052 |
| pooled 3-sym | 3-night (M/T/Th) | +4.0 | 0.956 (t=−1.68) | 0.769 | 1.022 | 0.917 |
| SPY | every-night | +3.3 | 0.923 | 0.726 | 0.914 | 0.884 |

**Verdict: NO-GO.** The Monday overnight premium reproduces directionally — Mon overnight gross
**+6.3–8.0 bp** vs unconditional overnight **+3.3 bp**, so the "strong Monday effect" is only
**~+3 bp** over baseline (and gross t=0.76–1.32, none significant). It cannot clear ANY realistic
cost: at 5 bp the Mon-only PF is 1.07–1.12 (IS), OOS post-2000 1.05–1.10, all well below the
**1.3 OOS bar**; at 2× cost (10 bp) **every** construction is negative (PF 0.71–0.93) and the
3-night model is PF 0.77 pooled. The Friday→Monday weekend is **not** negative as the paper
claims — it is flat-to-slightly-positive gross (+2.4–4.0 bp), merely *lower* than Monday, not a
harvestable short leg. Confirms Lane 49's structural finding: the overnight premium is real but
not harvestable unconditionally — it requires the weak-close/big-drop conditioning of Lanes 47/48.
**Re-activate only if** a conditioning filter pushes OOS PF ≥ 1.3 at 10 bp (not expected — the
raw premium is ~3 bp, an order of magnitude below the cost floor).

## Lane 56 — Crypto weekend→Monday "Monday Asia Open Effect" (Concretum Group 2026; crypto day-of-week literature) — NO-GO-WITH-REASON

`research/crypto_weekend_backtest.py` → `research/crypto_weekend_results.json`. Claim under test: BTC has a
CONCENTRATED positive window Sunday ~19:00 ET (Asia Monday open) through Monday, exit Monday (1-day hold);
plus the passive "Monday effect" (positive Mon / negative weekend). Tradeable lane = LONG at the Monday
00:00 UTC open (= Sunday 19:00 ET within 1h, crypto trades 24/7 so no gap) → EXIT Monday close, 2×ATR14
gap-aware stop, 10 bps/side fee (Binance.US taker) + 0/10/20 bps/side slippage stress; 40/20/40
walk-forward + post-2020 split. BTC/ETH = yf daily 2014/2017→2026-08-28 + ~2y UTC hourly; SOL = Binance.US daily 2020-09→2026-08-15.

**Monday candle-body return (open→close = "Sun-19:00-ET→Mon-close" proxy), bp:**

| sym | Mon n | Mon avg / median | Mon win | Mon t | 2nd-best weekday | Fri→Sun (weekend) |
|---|---|---|---|---|---|---|
| BTC | 623 | **+48.2 / +25.0** | 55% | **3.23** | Wed +23.9 | +22.8 |
| ETH | 459 | +27.7 / +22.5 | 52% | 1.21 (ns) | Sat +40.0 | +55.1 |
| SOL | 308 | +20.9 / **−16.7** | 47% | 0.59 (ns) | Fri +52.1 | +106.3 |

**Tradeable lane (PF, fee 10 bps/side):**

| sym | @slip0 full (IS/OOS) | @slip20 full (IS/OOS) | avg @slip0 → @slip20 | post-2020 OOS |
|---|---|---|---|---|
| BTC | 1.23 (1.31 / **1.09**, n=250) | **0.91** (0.99 / 0.77) | +26.8 → −12.7 bp | 1.14 |
| ETH | 1.01 (1.03 / 0.97) | 0.81 (0.84 / 0.73) | +1.4 → −37.7 bp | 1.08 |
| SOL | 0.99 (1.07 / 0.82) | 0.83 (0.92 / 0.65) | −2.9 → −42.4 bp | — |

**Hourly (2y, UTC):** the "Sunday 19:00 ET → Monday" window is NOT concentrated-positive. EST anchor
(Mon 00:00 UTC→24h) BTC +25.4 bp t=0.99 / ETH +14.4 bp t=0.37 (ns); EDT anchor (Sun 23:00 UTC→24h)
BTC **−10.7** / ETH **−23.5** bp; Tue window negative (−1.3 / −19.6 bp).

**Verdict: NO-GO.** BTC's Monday drift is real and the largest weekday (gross +48.2 bp, t=3.23 over 2014–2026)
but it is a drift-inflated seasonal on top of crypto's ~+17 bp/day unconditional drift, and it dies at cost:
net of the 10 bps/side fee the lane is PF 1.23 with **OOS 1.09** (below the 1.3 bar); at 2× cost (20 bps/side
slip) every construction is negative (BTC PF 0.91 / OOS 0.77, ETH 0.81, SOL 0.83). The paper's "post-2020
stronger" claim **reverses** — BTC post-2020 OOS PF 1.14 is *weaker* than the pre-2020 IS 1.35. It does not
generalize: ETH (t=1.21, PF ~1.0) and SOL (median Monday return **negative** −16.7 bp, win 47%) show no Monday
effect. The "negative weekend" sub-hypothesis also fails — Fri→Sun is positive on all three (+23/+55/+106 bp,
just crypto drift). The specific intraday "Sun-19:00-ET" window is unsupported by the 2y hourly data
(ambiguous-to-negative, all ns). Redundant with the already-shelved crypto momentum (Lane 13) — no incremental
edge. **Re-activate only if** the BTC Monday drift sustains OOS PF ≥ 1.3 at 2× cost on fresh data **and** the
Sun-19:00-ET intraday window is confirmed with proper intraday bars (not a UTC-daily proxy).

## Lane 57 — Cross-sectional crypto momentum (relative strength; Zarattini-Pagani-Barbon SSRN 5209907) — NO-GO-WITH-REASON

`research/crypto_crossmom_backtest.py` → `research/crypto_crossmom_results.json`. Rank
BTC/ETH/SOL/XRP/LTC/ADA by trailing 3d/5d return, LONG top-2 (and/or SHORT bottom-2), 1–7 day
hold, daily/3d/weekly rebalance. Binance.US daily 2019-09→2026-08-15; SOL starts 2020-09 and XRP
was delisted 2021-01..2023-07, so the cross-section ranks only coins *present* each signal date.
Honest fills: 10 bps/side fee (Binance.US taker) + 0/10/20 bps/side slip stress, 2×ATR14 gap-aware
stop, 40/20/40 walk-forward + post-2020 split, PF on net per-position returns.

| config | gross top2−bot2 spread | PF @slip0 (IS/OOS) | PF @slip20 (IS/OOS) |
|---|---|---|---|
| N3 H1 (daily) | +17.9 bp (t=2.85) | 1.00 (1.06 / **0.90**) | 0.78 (0.85 / 0.68) |
| N5 H1 (daily) | +15.0 bp (t=2.43) | 0.99 (1.05 / **0.88**) | 0.78 (0.84 / 0.66) |
| N3 H3 (3d) | +26.0 bp (t=2.31) | 1.08 (1.20 / **0.90**) | 0.94 (1.05 / 0.76) |
| N5 H7 (weekly) | +77.9 bp (t=4.40) | 1.21 (1.47 / **0.85**) | 1.11 (1.35 / 0.77) |
| L/S N3 H1 | — | 0.98 (1.02 / 0.92) | — |
| L/S N5 H7 | — | 1.16 (1.28 / 0.97) | — |

**Verdict: NO-GO.** The cross-sectional spread is REAL gross — top-2 beat bottom-2 by **+15 to +78 bp**
(t=2.3–4.4, strongest at 5d→7d), so crypto momentum is partly a relative effect, not just per-coin
Donchian. But the tradeable LONG-only top-2 lane does not clear cost: the marginal edge over crypto's
unconditional **+17.7 bp/day** drift is only ~**+6.6 bp/day** at H=1 (top-2 +24.3 bp vs all +17.7 bp),
i.e. thinner than the **20 bp round-trip fee**, so the daily lane is breakeven at base cost (PF 1.00)
and clearly negative at 2× cost (PF 0.78 @slip20). The weekly lane's +86.7 bp/trade is drift-inflated
and its OOS PF is **0.85**. Critically, the 40/20/40 walk-forward **OOS PF is 0.66–0.90 in every
construction** — the momentum spread decayed in the recent out-of-sample window (≈2023-08→2026-08) —
and shorting the bottom-2 does not rescue it (L/S OOS 0.92/0.97). Fails the 1.3 OOS bar massively.
Redundant with Lane 13 (per-coin Donchian, already marginal) — no incremental edge. **Re-activate only
if** the cross-sectional spread sustains OOS PF ≥ 1.3 at base cost on fresh data, or a
lower-fee venue (not Binance.US spot) emerges.

## Lane 58 — Post-FOMC announcement drift + CMVJ even-week overlay — NO-GO-WITH-REASON

`research/fomc_post_drift_backtest.py` → `research/fomc_post_drift_results.json`. Distinct from the
retired pre-FOMC Lane 52 (entered the day BEFORE, exited on announcement day): this enters at the
CLOSE of the FOMC announcement day and exits 2–5 days later, plus the Cieslak–Morse–Vissing-Jorgensen
(2019) "even-week" overlay (long FOMC-cycle weeks 0/2/4/6, flat odd). Same 263-meeting calendar
(1994–2026). Round-trip bps deducted, PF on net returns, IS/OOS 60/40 + ≥2016 + ≥2020.

**Post-FOMC drift (LONG at announcement-day close, exit H days later):**

| sym | H | PF @5bp (IS/OOS) | avg/t @5bp | ≥2016 | ≥2020 |
|---|---|---|---|---|---|
| SPY | 2 | 0.76 (0.91 / **0.56**) | −17.2 bp / t=−1.65 | 0.57 | 0.62 |
| SPY | 3 | 0.87 (1.00 / 0.72) | −9.8 bp / t=−0.80 | 0.73 | 0.86 |
| SPY | 5 | 0.88 (0.90 / 0.86) | −10.7 bp / t=−0.74 | 0.93 | 1.12 |
| QQQ | 2 | 0.92 (1.14 / 0.66) | −7.1 bp / t=−0.44 | 0.70 | 0.78 |
| QQQ | 3 | 1.02 (1.15 / 0.85) | +2.2 bp / t=0.11 | 0.90 | 1.01 |
| QQQ | 5 | 1.05 (1.03 / 1.09) | +5.9 bp / t=0.23 | 1.12 | 1.29 |

**Bad-news conditioned (announcement-day return < 0), the "buy-after-bad-news" drift:** only H=5 is
positive — QQQ H=5 @10bp **PF 1.33 (IS 1.26 / OOS 1.48, n=85)**, SPY H=5 PF 1.19 (OOS 1.26). H=2/H=3
are negative-to-breakeven on both, and n ≈ 85–112 over 27 years (~3–4/yr).

**Post-FOMC next-day reversal** (the literature's "post-FOMC day negative"): **absent** — ann+1 day is
flat (SPY −3.0 bp t=−0.36, QQQ +1.1 bp t=0.08).

**CMVJ even-week overlay:** daily gross even-week vs odd-week spread is **+1.30 bp (SPY, t=0.50)** and
**+2.98 bp (QQQ, t=0.73)** — not significant, and odd weeks are NOT flat (+3.4/+3.8 bp). The weekly
long-even/flat-odd overlay @5bp is PF **1.22/1.23 (OOS 1.01/1.14)**, @10bp **1.15/1.18 (OOS 0.94/1.09)**,
≥2020 0.98/1.16 — every construction below the 1.3 OOS bar.

**Verdict: NO-GO.** (a) The classic post-announcement drift does **not** replicate: SPY (canonical
instrument) is PF 0.76–0.88 with negative expectancy at every horizon, and QQQ only clears breakeven
at H=5 (+5.9 bp, t=0.23). The drift (if it ever existed) has fully decayed — consistent with the
pre-FOMC Lane 52 finding. (b) The only positive cells are the bad-news-conditioned H=5 (QQQ PF 1.33
OOS 1.48, SPY 1.19), but that is ~3–4 trades/yr over 27 years, fails at H=2/H=3, fails on SPY, and is
long-beta (bad-news FOMC days in the 2020–26 bull bounce — the ≥2020 PFs are beta, not signal).
(c) The "post-FOMC reversal" next-day leg is zero. (d) CMVJ's even-week premium does **not** replicate
(spread ≈ +1–3 bp, ns) — the 2019 paper's 8-week-cycle framing does not hold on 1994–2026 daily data
once you account for the actual ~6.5-week meeting cadence and post-2019 pressers. Redundant with the
FOMC Lanes 52/53 (all the same long-beta announcement-cycle exposure). **Re-activate only if** a
bad-news-conditioned H=5 construction sustains OOS PF ≥ 1.3 at 2× cost on fresh post-2026 data AND is
shown non-redundant with beta (e.g. hedged).

## Lane 59 — Options-expiration (OPEX) week drift (Stoll-Whaley 1997; Ni-Pearson-Poteshman 2005) — NO-GO-WITH-REASON

`research/opex_week_backtest.py` → `research/opex_week_results.json`. LONG SPY/QQQ at the close of the
last trading day before the monthly-expiration (3rd-Friday) week, EXIT at expiration-day close (5d) or
the day-before (4d); post-OPEX week tested as the "dealer-gamma unwind" contra-leg. ~12 RT/yr; 3rd-Friday
calendar 1993–2026 (Good-Friday expirations shifted to Thursday). Round-trip bps deducted, PF on net
returns, IS/OOS 60/40 + pre/post-2000 + ≥2016/≥2020. Unconditional 5d drift benchmark: SPY +19.7 bp,
QQQ +25.2 bp (win ~58%).

| leg | sym | PF @5bp (IS/OOS) | post-2000 | ≥2020 | PF @10bp |
|---|---|---|---|---|---|
| pre-OPEX 5d (through exp) | SPY | 1.02 (1.03 / 1.01) | 0.91 | 0.70 | 0.96 |
| pre-OPEX 5d (through exp) | QQQ | 1.07 (1.02 / 1.17) | 1.05 | 0.96 | 1.03 |
| pre-OPEX 4d (exit Thu) | SPY | 1.34 (1.33 / 1.35) | 1.18 | **0.89** | 1.25 |
| pre-OPEX 4d (exit Thu) | QQQ | 1.31 (1.23 / 1.48) | 1.29 | 1.13 | 1.25 |
| post-OPEX 5d | SPY | 1.16 (0.98 / 1.50) | 1.17 | 1.64 | 1.09 |
| post-OPEX 5d | QQQ | 1.21 (1.07 / 1.47) | 1.19 | 1.49 | 1.16 |

**Verdict: NO-GO.** There is no OPEX-specific premium that beats beta. (a) Holding **through** the
expiration Friday is a *drag*, not a drift: pre-OPEX 5d nets only **+1.6/+8.3 bp @5bp** vs the
unconditional +19.7/+25.2 bp 5-day drift (SPY PF 1.02, post-2000 0.91, ≥2020 0.70) — the expiration
day itself eats the week's return, consistent with gamma pinning/expiration-day clustering. (b) The
exit-Thursday (4d) variant looks better only because it captures ~+21.9/+28.7 bp ≈ the *unconditional*
drift, i.e. beta: it is pre-2000-dominated (SPY pre-2000 PF 2.45 vs post-2000 1.18) and **decayed to
PF 0.89 (SPY) / 1.13 (QQQ) ≥2020**, failing the 1.3 bar at 2× cost in the modern era. (c) The post-OPEX
week is **positive, not negative** (SPY +11.5 bp / QQQ +21.3 bp; ≥2020 PF 1.64/1.49) — the "dealer-gamma
unwind → post-OPEX selloff" contra-leg does not exist, and it is again ≤ unconditional beta (SPY post-OPEX
+11.5 bp < +19.7 bp unconditional). Same family as the killed calendar/timing overlays (Lanes 52–55):
long-beta 5-day hold, ~12 RT/yr, no incremental edge. **Re-activate only if** an OPEX-week construction
shows OOS PF ≥ 1.3 at 2× cost sustained on fresh post-2026 data AND is shown non-redundant with beta
(e.g. an expiration-day-only short/avoid overlay, or an L/S construction vs the non-OPEX weeks).

## Lane 60 — Volume-gated dip-buy (Campbell–Grossman–Wang 1993) — NO-GO-WITH-REASON

`research/volume_gate_backtest.py` → `research/volume_gate_results.json`. Test of the unbanked filter
#10 in `NEW_SHORT_HORIZON_EDGES.md`: does a volume gate (RVOL = vol / prior-20d mean) add >5 bp/trade
net to the surviving dip-buy family? Two baselines on the deployed sub-$50 universe (488 usable syms,
2006–2026, OOS from 2022), RVOL gate 1.5 / 2.0, 5/10 bps-per-side.

**Broken Arrow (close→next-open, no stop):**

| drop | construction | PF @5bp (IS/OOS) | avg/trade | Δ vs unconditional |
|---|---|---|---|---|
| −8% | unconditional | 1.368 (1.542 / 1.235) | +42.5 bp | — |
| −8% | RVOL ≥ 1.5 | 1.258 (1.269 / 1.249) | +26.5 bp | **−16.0 bp** |
| −8% | RVOL ≥ 2.0 | 1.355 (1.232 / 1.466) | +31.9 bp | −10.6 bp |
| −10% | unconditional | 1.517 (1.712 / 1.362) | +67.0 bp | — |
| −10% | RVOL ≥ 1.5 | 1.338 (1.416 / 1.278) | +38.0 bp | **−29.0 bp** |
| −10% | RVOL ≥ 2.0 | 1.368 (1.247 / 1.474) | +36.4 bp | −30.6 bp |

**RSI2<5 (next-open, 2×ATR stop):**

| construction | PF @5bp (IS/OOS) | avg/trade | Δ vs unconditional |
|---|---|---|---|
| unconditional | 1.096 (1.120 / 1.067) | +15.6 bp | — |
| RVOL ≥ 1.5 | 1.149 (1.145 / 1.155) | +24.5 bp | +8.9 bp |
| RVOL ≥ 2.0 | 0.995 (0.984 / 1.012) | −1.0 bp | −16.6 bp |

**Verdict: NO-GO.** The volume gate does **not** add a robust edge — it *falsifies* the
Campbell–Grossman–Wang thesis. On the strong Broken Arrow lane, high-volume down days bounce
**LESS, not more**: gating at RVOL ≥ 1.5 costs −16 bp (−8% drop) to −29 bp (−10% drop) per trade, and
−31 bp at 2.0. On RSI2<5 the response is **non-monotonic** (+8.9 bp at RVOL 1.5, but −16.6 bp at RVOL 2.0
→ PF 0.995) — the +8.9 bp is threshold-noise, not a monotone "more volume ⇒ more bounce" mechanism, and
the underlying sub-$50 RSI2 edge is already thin (unconditional OOS PF 1.067). No construction improves
the unconditional lane by >5 bp *robustly* (both gates and both lanes at 2× cost). The volume signal here is
a *liquidity/crisis* marker (the highest-volume down days are the falling knives, 2022-style), not a
mean-reversion amplifier. **Re-activate only if** a monotone volume-conditioning is shown to add ≥5 bp/trade
across all thresholds on fresh data (not expected — direction is currently negative on the stronger lane).

## Lane 61 — Volume-return interaction classifier (Llorente–Michaely–Saar–Wang 2002) — NO-GO-WITH-REASON

`research/llorente_interaction_backtest.py` → `research/llorente_interaction_results.json`. Per-stock
rolling regression R_t = C0 + C1·R_{t−1} + C2·(V_{t−1}·R_{t−1}), V = detrended log volume; C2 > 0 ⇒
informed ⇒ continuation, C2 < 0 ⇒ hedging ⇒ reversal. 185 liquid large-caps (bot.live_equities.STOCKS),
2y rolling window re-estimated monthly, signal = |R_{t−1}| ≥ 2% on RVOL ≥ 1.5, LONG next-open, 1/3/5d hold,
5/10 bps-per-side, OOS from 2022.

**Directional sanity check (gross fwd H-day return, bp — does C2 sort correctly?):**

| H | UP high-C2 | UP low-C2 | DOWN high-C2 | DOWN low-C2 |
|---|---|---|---|---|
| 1 | **−5.2** | +14.0 | +10.6 | +15.2 |
| 3 | **−1.6** | +24.8 | +36.1 | +59.2 |
| 5 | **−0.4** | +42.4 | +52.7 | +76.9 |

**Tradeable long-only legs @5bps (PF, IS/OOS):**

| leg | H | PF | avg/trade | OOS PF |
|---|---|---|---|---|
| momentum (hi-C2 up) | 1 | 0.894 | −15.2 bp | 1.047 |
| momentum (hi-C2 up) | 5 | 0.956 | −10.4 bp | 1.141 |
| fade (lo-C2 down) | 3 | 1.278 | +49.2 bp | 1.395 |
| fade (lo-C2 down) | 5 | 1.322 | +66.8 bp | 1.402 |
| unconditional down | 5 | 1.243 | +53.8 bp | 1.388 |

**Verdict: NO-GO.** The C2 sign does **not** replicate the paper's direction. On UP moves the classifier is
*inverted*: high-C2 (informed) names show −5.2/−1.6/−0.4 bp forward (H1/3/5) while low-C2 names show
+14.0/+24.8/+42.4 bp — the "informed-trading ⇒ continuation" leg does not exist, and the momentum trade
(hi-C2 up) is PF 0.89–0.96 @5bp and clearly negative @10bp. On DOWN moves both buckets bounce (short-term
reversal is universal in large caps) and low-C2 bounces only marginally more (+76.9 vs +52.7 bp at H5). The
one positive tradeable leg (fade lo-C2 down, H5 PF 1.322 / OOS 1.402) is statistically indistinguishable from
the *unconditional* high-volume down-move bounce (H5 PF 1.243 / OOS 1.388) — the C2 sort adds ~+13 bp/trade
of no incremental, non-redundant value over the dip-buy already deployed in Lanes 1/47. C2 is also noisy: only
79/185 names are majority-positive and the cross-sectional median C2 ≈ −0.007 ≈ 0. **Re-activate only if** a
re-estimated C2 (or an insider-trading/size/short-constraint proxy for informed trading, per the paper's own
cross-sectional correlate) is shown to cleanly separate continuation from reversal on fresh data — the sign
alone does not.



