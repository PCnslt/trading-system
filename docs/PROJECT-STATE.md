# Project State — living one-pager (laptop ↔ VPS cross-context alignment)

> **Both sides keep this current.** Laptop = research + Robinhood order placement.
> VPS = build/backtest/deploy/monitor (IBKR paper). Commit every update so the
> other side picks it up on next pull. Last updated: **2026-08-17**.

---

## Current phase

**Objective (owner-clarified, 2026-08-16): CAPITAL PRESERVATION.** "The system should
not lose money" — drawdown minimization is the #1 objective; returns are secondary; no
asset class is a priority. **Horizon: intraday → 2–3-day swing.** See
`research/INTRADAY_BUILD.md` for the full build spec and the new drawdown-first
evaluation standard.

**Futures phase-1 (paper forward-test).** Two validated futures edges are being
paper-forwarded toward live capital (index-LONG + gold momentum); everything else
is shelved/tabled (never deleted — optionality is preserved). **Robinhood is the
LIVE small-capital lane** (~$700 acct `515821577`, whole-share small-ticket RSI2,
gated live, paper-forward first) — see `docs/SMALL-CAPITAL-LIVE-PLAN.md`. Crypto
is paper-signal research-grade (LOWEST live-priority).

Execution-layer hardening is **done** (3 phases):
1. Persistent risk ledger (`RISK#`) — restart-safe daily loss cap.
2. Broker reconciliation (`reconcile-daemon`, 45s → `RECONCILE/system`).
3. Execution manager + idempotent `TradeIntent` (`INTENT#` conditional writes —
   no strategy calls IBKR directly).
4. **Never-lose-money discipline** — every entry rests a hard protective stop at
   fill time; the reconciler verifies a stop EXISTS on every open position
   (missing/orphaned stop = MISMATCH → halt). `exec_manager.submit_entry` refuses
   any unprotected entry fail-closed.

## Live paths wired (RH LIVE since 08-20; IBKR live-ready, gateway disabled)

- **IBKR LIVE gateway** (`U26949861`): second GWClient on `:100`, settings dir
  `/home/ubuntu/Jts-live` (`tradingMode=l`), systemd `ibgateway-live.service`
  (**DISABLED**). Live API port = **4001** default (paper = 4002). ⚠️ Login
  screen "Trading Mode" defaults to Paper and is NOT driven by jts.ini — must be
  switched to "Live Trading" at first login, then verify
  `managedAccounts()==['U26949861']`. See `docs/IBGATEWAY-LIVE-OPS.md`.
- **Robinhood LIVE client** (`hardening/rh_client.py`, committed `77fbb1e`): OAuth
  via SSM `/trading/robinhood/*` (MCP-gateway transport). **✅ LIVE since
  2026-08-20 (owner-approved go-live):** deployed `RH_EXECUTION_MODE=LIVE` +
  `RH_LIVE_ENABLED=true` + `RH_MAX_POSITIONS=5` + `RH_DAY_LOSS_CAP=$50` in BOTH
  `.env` and the `live-equities.service` unit (systemd overrides `.env` — edit
  both). Code default stays PAPER/OFF (fail-closed). Token fresh (re-authed
  2026-08-16 21:58 ET); read path verified live (acct `515821577`,
  `agentic_allowed=true`). 0 live FILLS through 08-24 (rare RSI2 dips +
  whole-share sub-$35 universe — no naked exposure). Plan:
  `docs/ROBINHOOD-LIVE-PLAN.md`; sizing: `docs/SMALL-CAPITAL-LIVE-PLAN.md`.

## Active edges

| Edge | Status | Note |
|---|---|---|
| **index-LONG** (Donchian + RSI2-LONG + RSI2PT + REV2, `live.py`) | ✅ PROMOTED | Sole live-cap candidate. Donchian PF 1.56/1.52/1.43@3t; RSI2-LONG 1.99/2.57/1.88@3t (corr 0.002). RSI2PT = A/B take-profit variant (+0.5% broker-side limit) vs RSI2's RSI2>70/5d exit. REV2 = 2-day reversal (drop >1×ATR, **close >200d SMA**, revert/3d exit) — validated 2026-08-19: ES/NQ PF 2.07/2.04 maxDD -$14k/-$26k with SMA filter, independent of RSI2 (corr +0.07-0.14). ⚠️ Long-beta caveat: RSI2/RSI2PT/REV2 are all "buy the dip in a bull market" (drift-inflated, lose in bears); SMA filter is the mitigation. |
| **intraday MES** (FADESHORT + DONCH15, `live_intraday.py`) | ▶️ paper | RTH entries, EOD flatten 15:45 ET. |
| **gold momentum** (MGC Donchian L/S + TSMOM, `live_gc.py`) | ✅ paper-EXEC | Promoted (EDGE_SWEEP) → IBKR paper execution (clientId 78, ~19:10 ET). Donchian 1.45/1.81 OOS/1.31 IB, 3-tick 1.42; TSMOM 1.37/1.73/1.99, 3-tick 1.35. Donchian = chandelier 3·ATR trail; TSMOM = fixed 3·ATR stop. **Forward-test runs on MGC micro ($10/pt, GC_CONTRACT=MGC, $250k sleeve)** — full GC ($100/pt) at 1% risk needs a ~$2.3M sleeve (size=0); MGC sizes 1 contract (~$2.3k stop risk). **HORIZON NOTE (2026-08-19): both strategies are LONG-HOLD (Donchian ~weeks, TSMOM ~months) — mismatched vs owner's intraday→2-3-day-swing mandate. At elevated gold ATR (85.6, +38% 12m bull) the 3·ATR stop = $2,569 > 1% budget $2,500 → size=0 = correct fail-closed, NOT a defect. Parked (not deleted); do not bump sleeve to force long-hold trades the owner does not want.** |
| **equities RSI2-dip + Donchian(200d)** (`equity_signals.py`) | ▶️ paper-signal | Promoted (EQUITIES_SWEEP). RSI2 champion (both regimes); Donchian gated by close>200d-MA. Robinhood stays manual. |
| **RH equities RSI2** (`live_equities.py`) | ▶️ paper → **LIVE-READY (ACTIVE — enabled, not blocked)** | Robinhood lane (VPS `rh_client` submits — single-writer; laptop MCP retired). RSI(2)<5 + SMA200, 2xATR whole-share stop, 5d cap, revert. 1%/trade (5% cap), $150/day loss cap. Index regime gate REJECTED (2022 0.81→0.21). OOS PF 1.47 (all 5 folds >1.0)/1.36@5bps. **Whole-share small-ticket live ENABLED** — $675 buying power, 20-pos hard ceiling / 5–15 recommended. Plan: `docs/ROBINHOOD-LIVE-PLAN.md`; sizing: `docs/SMALL-CAPITAL-LIVE-PLAN.md`. |
| **crypto Donchian-20 momentum MOM20** (`crypto_exec.py` paper-EXEC, `crypto_paper.py` signal) | ▶️ paper-EXEC | Pure Donchian-20 channel (no 200d-SMA — that was the buy-and-hold proxy). BTC/ETH/SOL/XRP; marginal on BTC/ETH, edge in alts. LOWEST live-priority. |
| **bonds fade-SHORT** (ZB/ZN, `live_bondsfx.py`) | 📦 SHELVED | Dies at 1-tick slip. Code kept + disarmed no-op; cron paused. Revisit only if cost/regime materially changes. |
| **BBAND_INDEX_LONG** | 📦 TABLED | Redundant w/ RSI2-LONG (corr 0.69, PF 1.84 / OOS 1.71). Paper fwd-test candidate if RSI2-LONG underperforms live. |
| **Screening** | 🔒 CLOSED | Weekly scan paused. |
| **Wheel (CSP→CC)** | 🔬 evaluating | Backtest: pooled PF 0.72, assignment drag is the killer. Not for real money yet. |
| **futures-options** (chain scaffold, `options_plan.py`) | 🔬 research | Chain metadata for 12 underlyings captured; vol-surface/greeks need paid bars — NOT requested. See `FUTURES_OPTIONS_PLAN.md`. |
| **Crypto** | ▶️ paper-signal | Donchian-20+200d promoted (buy-and-hold proxy, LOWEST live-priority). Mean-reversion KILLED. Deep `crypto-hist/` sweep (6.9y, 6 syms): 0 promotes. Binance.US ticks still collected. |
| **forex spot** (28 yfinance pairs) | 🔬 data-on only | No edge/broker yet. Daily (max) + 1h (~2y) → `yf/fx/` for future research. Reopens Sun 17:00 ET. |
| **VWAP equity-index sleeve** (`live_vwap.py`, Lane 10 re-activation) | ✅ paper-EXEC (armed) | Scoped re-activation 2026-08-18: volume-filtered VWAP 2σ on MES/MNQ, 5-min, real paper fills, 2×ATR native stop, round-trip journal. 1-min 24mo re-validation blocked (30d entitlement cap). |
| **Order-flow / microstructure** (Lane 32, Creamer auction) | 🔬 data + signal-only (exec=NONE) | Orderbook depth (IBKR L1-only, RH L2 for 15 small-ticket names) + `kind`-tagged ticks + 1-min bars; footprint features → `MICRO#`; auction signals → `AUCTION#MNQ`. 0 setups/8 sessions (needs tuning). |

## Data sources + coverage vs gaps

The detailed **source / prefix / clientId / symbol-registry** truth lives in
[`docs/DATA-CATALOG.md`](DATA-CATALOG.md) (owned by the data-collection project).
Standing rule: **never silently substitute free/stale data for critical paid data —
flag the gap and ask the owner whether to purchase the proper subscription.**

| Source | Tier | What we get | Depth | Where |
|---|---|---|---|---|
| IBKR (paper, broker-verified) | **Paid / source of truth** | **63-symbol** futures registry (56 resolve) + **US equities (~6.9k common stocks, 20y+ daily)** + crypto micros (MBT/MET) + options chains: daily + 1-min + L1 real-time ticks | futures daily ~3-4y (index/energy/metals) / ~16mo (rates); **equities daily 20y+**; 1-min ~1-2y (month-partitioned); 1m futures RTH ~1-2y | `ibkr/` (equities/futures/crypto, parquet `quality=BROKER`), `futures-bars/`, `futures-ticks/`, `contracts/`, `sessions/`, `options/` |
| yfinance | Free / unofficial | ETFs, sectors, futures-continuous (`ES=F` **16y — the only 20y-class futures depth**), fx (**28 pairs**), crypto spot | daily ~10-16y; 1h ~2y | `yf/` |
| FRED | Free / public | Macro (DGS10/2/30, DFEDTARU, CPIAUCSL, UNRATE, PAYEMS, T10Y2Y, VIXCLS) | daily/monthly, 60y+ | `macro/` |
| FMP (free tier) | Free | Quote + company profile | — (QQQ→402 → use profile) | `fmp/` |
| Binance.US | Free | Crypto spot ticks + daily candles (6.9y deep history) | daily ~6.9y | `crypto-tick/`, `crypto-candles/`, `crypto-hist/` |
| NewsAPI | Free | News headlines | — | `newsapi/` |

### Gaps (what's needed / flagged)

- **20y futures history is NOT achievable from IBKR paper.** Verified 2026-08-15:
  `reqContractDetails(includeExpired=True)` returns 0 expired contracts (only the
  full FUTURE chain), and an expired contract month (`Future('ES','202006','CME')`)
  → Error 200 "No security definition". IBKR futures daily caps at ~3-4y
  (CONTfut ~3y index + current-chain far-dated contracts ~4y). The only 20y-class
  futures depth is yfinance `ES=F` (16y, retained). → no subscription fixes this;
  it's an IBKR non-professional historical limitation.
- **US equities real-time streaming (consolidated tape)** — NOT in the futures
  "CME Group" bundle. Equity bars are historical-only (20y+ daily, 1-min ~1-2y);
  live stock L1 needs a separate consolidated-tape subscription.
- **US options real-time + historical BARS** — separate paid subscription. Only
  chain *metadata* (expiries+strikes) is captured.
- **Real-time NYMEX energy + COMEX/NYMEX metals L1** — Error 354 (delayed-only)
  on paper, even though historical BARS work.
- **CME FX futures majors `6E 6J 6B 6A 6C 6S 6N`** — "no security definition" on paper
  (separate CME FX-futures entitlement). Only `6M` (MXN) + micros resolve.
- **Crypto spot (PAXOS BTC/ETH)** — "No market data permissions" (separate
  subscription). CME micro crypto futures MBT/MET ARE entitled (~9-12mo).
- **FMP metrics/ratios/treasury = paid-only** (free tier returns `[]`). No substitute → flag.
- **L2 market depth** — separate paid package; top-of-book L1 only.
- **Schwab API = ON HOLD** (approval pending, NOT dropped).
- **Micro silver** (`SIL`) has no separate root — it is SI `tradingClass='SIL'`
  (multiplier 1000). Accessed via the SI chain.

## Current edge → data requirement

- **index-LONG (sole promoted edge)**: uses 16y yfinance futures-continuous. **NOT
  stale** — same CME contracts, adequate depth. **No purchase needed now.**

## Evaluation standard (NEW — applies to ALL future evaluation)

Rank every strategy **primarily by maxDrawdown, worst-case, and consistency
(win rate / longest losing streak) — NOT by PF/return.** A low-return but
tiny-drawdown strategy outranks a high-return high-drawdown one. PF/Sharpe/return
are reported but demoted to tie-breakers. Risk per trade: **0.5–1% max**, hard daily
loss cap, mandatory stops + trailing (already fail-closed). No asset priority.

### Daily-loss limit — ONE authoritative policy (no ambiguity)

Effective daily-loss halt, **as enforced by code**, is per-lane:

| Lane | Enforced by | Daily-loss limit |
|---|---|---|
| Index futures (MES/MNQ/MYM) | `bot/risk.py` RiskEngine | 2% × sleeve ($350k) = **$7,000** (paper) |
| Gold (MGC) | RiskEngine | 2% × sleeve ($250k) = **$5,000** (paper) |
| VWAP sleeve (MES/MNQ) | RiskEngine | 2% × sleeve ($25k) = **$500** (paper) |
| Intraday MES | RiskEngine | 2% × `INTRA_RISK_BUDGET` (paper) |
| RH equities | `live_equities.py` `RH_DAY_LOSS_CAP` | **$150 flat** |

- Futures lanes: `max_daily_loss_pct` (2%) × `risk_budget_usd`, checked before every entry, persisted in `RISK#`.
- **Portfolio heat cap (2026-08-19):** `heat_cap_pct` (index lane default **3%**) caps the TOTAL open risk — the sum of `|entry−stop| × point_value × qty` across ALL concurrent positions — so RSI2/RSI2PT/REV2 (correlated dip-buys) can't stack N× on one signal. Persisted as `open_risk_usd` in `RISK#`; env `HEAT_CAP_PCT` (0=off). Other lanes default 0 (unchanged).
- RH lane: flat `$150/day` realized-loss throttle, separate from RiskEngine.
- **Micro-live note:** the "$150/day" plan target equals `2% × $7,500` sleeve. When funding live, set the sleeve so `2% × budget = $150` — do NOT carry the paper $350k/$250k sleeves into live. There is no single global "$1,000" limit; the value above is the one actually enforced.

## Next actions (VPS)

1. **Robinhood small-capital live (the live lane):** build the small-ticket liquid
   sub-universe (§5 of `docs/SMALL-CAPITAL-LIVE-PLAN.md`), paper-forward ≥30 days,
   then gate live behind `RH_EXECUTION_MODE=LIVE`+`RH_LIVE_ENABLED=true`. No live
   orders until the owner resolves the 5%-cap vs "$10–$150 tickets" decision (§4).
2. Paper-forward `live.py` (index edge) — **Gate 5 session 1/10 starts Mon
   2026-08-17** (10 RTH sessions, drawdown-first bar, not PF alone).
3. Add 2–3-day short-swing variants (Donchian 2–3d lookback, 2–3d mean-reversion) to
   the intraday/short-swing evaluation, alongside ORB/MOM/VWAP/DONCH15/FADESHORT.
4. Micro-live — min size, hard loss limit, tested kill + rollback.
5. Optional: buy CME FX-futures entitlement to un-gap 6E/6J/6B/6A/6C/6S/6N.

## Laptop's active research focus

<!-- LAPTOP: keep this section current. What are you researching / testing next? -->

*(to be filled by laptop Hermes)*

## Kill-switch / safety

- Control state `KILLED` = runtime kill-switch (flatten + halt). **Distinct** from
  the *strategy* statuses above (SHELVED/TABLED are roadmapping labels, not the switch).
- All IBKR collectors are read-only (`readonly=True`), distinct clientIds.
