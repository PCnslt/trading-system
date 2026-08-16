# Project State — living one-pager (laptop ↔ VPS cross-context alignment)

> **Both sides keep this current.** Laptop = research + Robinhood order placement.
> VPS = build/backtest/deploy/monitor (IBKR paper). Commit every update so the
> other side picks it up on next pull. Last updated: **2026-08-15**.

---

## Current phase

**Futures phase-1 (paper forward-test).** One validated edge is being paper-
forwarded toward live capital; everything else is shelved/tabled (never deleted —
optionality is preserved). Stocks/options (Robinhood) are live-ish on the laptop
side; crypto is paper-signal research-grade (LOWEST live-priority).

Execution-layer hardening is **done** (3 phases):
1. Persistent risk ledger (`RISK#`) — restart-safe daily loss cap.
2. Broker reconciliation (`reconcile-daemon`, 45s → `RECONCILE/system`).
3. Execution manager + idempotent `TradeIntent` (`INTENT#` conditional writes —
   no strategy calls IBKR directly).
4. **Never-lose-money discipline** — every entry rests a hard protective stop at
   fill time; the reconciler verifies a stop EXISTS on every open position
   (missing/orphaned stop = MISMATCH → halt). `exec_manager.submit_entry` refuses
   any unprotected entry fail-closed.

## Active edges

| Edge | Status | Note |
|---|---|---|
| **index-LONG** (Donchian + RSI2-LONG, `live.py`) | ✅ PROMOTED | Sole live-cap candidate. Donchian PF 1.56/1.52/1.43@3t; RSI2-LONG 1.99/2.57/1.88@3t (corr 0.002). |
| **intraday MES** (FADESHORT + DONCH15, `live_intraday.py`) | ▶️ paper | RTH entries, EOD flatten 15:45 ET. |
| **gold momentum** (GC Donchian L/S + TSMOM, `gc_signals.py`) | ▶️ paper-signal | Promoted (EDGE_SWEEP). Donchian 1.45/1.81 OOS/1.31 IB, 3-tick 1.42; TSMOM 1.37/1.73/1.99, 3-tick 1.35. Signal-only (GC L1 delayed). |
| **equities RSI2-dip + Donchian(200d)** (`equity_signals.py`) | ▶️ paper-signal | Promoted (EQUITIES_SWEEP). RSI2 champion (both regimes); Donchian gated by close>200d-MA. Robinhood stays manual. |
| **crypto Donchian-20+200d** (`crypto_paper.py`) | ▶️ paper-signal | Promoted (CRYPTO_SWEEP) but buy-and-hold proxy; LOWEST live-priority. |
| **bonds fade-SHORT** (ZB/ZN, `live_bondsfx.py`) | 📦 SHELVED | Dies at 1-tick slip. Code kept + disarmed no-op; cron paused. Revisit only if cost/regime materially changes. |
| **BBAND_INDEX_LONG** | 📦 TABLED | Redundant w/ RSI2-LONG (corr 0.69, PF 1.84 / OOS 1.71). Paper fwd-test candidate if RSI2-LONG underperforms live. |
| **Screening** | 🔒 CLOSED | Weekly scan paused. |
| **Wheel (CSP→CC)** | 🔬 evaluating | Backtest: pooled PF 0.72, assignment drag is the killer. Not for real money yet. |
| **futures-options** (chain scaffold, `options_plan.py`) | 🔬 research | Chain metadata for 12 underlyings captured; vol-surface/greeks need paid bars — NOT requested. See `FUTURES_OPTIONS_PLAN.md`. |
| **Crypto** | ▶️ paper-signal | Donchian-20+200d promoted (buy-and-hold proxy, LOWEST live-priority). Mean-reversion KILLED. Deep `crypto-hist/` sweep (6.9y, 6 syms): 0 promotes. Binance.US ticks still collected. |
| **forex spot** (28 yfinance pairs) | 🔬 data-on only | No edge/broker yet. Daily (max) + 1h (~2y) → `yf/fx/` for future research. Reopens Sun 17:00 ET. |

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

## Next actions (VPS)

1. Paper-forward `live.py` (index edge) until **Gate 5** (paper validation) passes.
2. Micro-live — min size, hard loss limit, tested kill + rollback.
3. Optional: buy CME FX-futures entitlement to un-gap 6E/6J/6B/6A/6C/6S/6N.

## Laptop's active research focus

<!-- LAPTOP: keep this section current. What are you researching / testing next? -->

*(to be filled by laptop Hermes)*

## Kill-switch / safety

- Control state `KILLED` = runtime kill-switch (flatten + halt). **Distinct** from
  the *strategy* statuses above (SHELVED/TABLED are roadmapping labels, not the switch).
- All IBKR collectors are read-only (`readonly=True`), distinct clientIds.
