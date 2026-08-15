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
| **intraday MES** (FADESHORT + DONCH15, `live_intraday.py`) | ▶️ paper | RTH entries, EOD flatten 19:45 UTC. |
| **gold momentum** (GC Donchian L/S + TSMOM, `gc_signals.py`) | ▶️ paper-signal | Promoted (EDGE_SWEEP). Donchian 1.45/1.81 OOS/1.31 IB, 3-tick 1.42; TSMOM 1.37/1.73/1.99, 3-tick 1.35. Signal-only (GC L1 delayed). |
| **equities RSI2-dip + Donchian(200d)** (`equity_signals.py`) | ▶️ paper-signal | Promoted (EQUITIES_SWEEP). RSI2 champion (both regimes); Donchian gated by close>200d-MA. Robinhood stays manual. |
| **crypto Donchian-20+200d** (`crypto_paper.py`) | ▶️ paper-signal | Promoted (CRYPTO_SWEEP) but buy-and-hold proxy; LOWEST live-priority. |
| **bonds fade-SHORT** (ZB/ZN, `live_bondsfx.py`) | 📦 SHELVED | Dies at 1-tick slip. Code kept + disarmed no-op; cron paused. Revisit only if cost/regime materially changes. |
| **BBAND_INDEX_LONG** | 📦 TABLED | Redundant w/ RSI2-LONG (corr 0.69, PF 1.84 / OOS 1.71). Paper fwd-test candidate if RSI2-LONG underperforms live. |
| **Screening** | 🔒 CLOSED | Weekly scan paused. |
| **Wheel (CSP→CC)** | 🔬 evaluating | Backtest: pooled PF 0.72, assignment drag is the killer. Not for real money yet. |
| **futures-options** (chain scaffold, `options_plan.py`) | 🔬 research | Chain metadata for 12 underlyings captured; vol-surface/greeks need paid bars — NOT requested. See `FUTURES_OPTIONS_PLAN.md`. |
| **Crypto** | ▶️ paper-signal | Donchian-20+200d promoted (buy-and-hold proxy, LOWEST live-priority). Mean-reversion KILLED. Deep `crypto-hist/` sweep (6.9y, 6 syms): 0 promotes. Binance.US ticks still collected. |
| **forex spot** (28 yfinance pairs) | 🔬 data-on only | No edge/broker yet. Daily (max) + 1h (~2y) → `yf/fx/` for future research. Reopens Sun 21:00 UTC. |

## Data sources + coverage vs gaps

The detailed **source / prefix / clientId / symbol-registry** truth lives in
[`docs/DATA-CATALOG.md`](DATA-CATALOG.md) (owned by the data-collection project).
Standing rule: **never silently substitute free/stale data for critical paid data —
flag the gap and ask the owner whether to purchase the proper subscription.**

| Source | Tier | What we get | Depth | Where |
|---|---|---|---|---|
| IBKR (paper, broker-verified) | **Paid / source of truth** | 42-symbol futures registry (35 resolve) across index/rates/energy/metals/ags/fx: daily + intraday (1h/15m/5m/1m) + L1 real-time ticks | daily ~3y index / ~16mo rates; intraday 1h/15m/5m ~1y; 1m ~30d | `futures-bars/`, `futures-ticks/`, `contracts/`, `sessions/`, `options/` |
| yfinance | Free / unofficial | ETFs, sectors, futures-continuous (`ES=F` etc), fx (**28 pairs: 7 majors + 21 crosses**), crypto spot + **US equities universe (~6.9k stocks, data engine)** | daily ~10-16y; 1h ~2y; 1m ~8d | `yf/`, `yf/stocks/` |
| FRED | Free / public | Macro (DGS10/2/30, DFEDTARU, CPIAUCSL, UNRATE, PAYEMS, T10Y2Y, VIXCLS) | daily/monthly, 60y+ | `macro/` |
| FMP (free tier) | Free | Quote + company profile | — (QQQ→402 → use profile) | `fmp/` |
| Binance.US | Free | Crypto spot ticks + daily candles (6.9y deep history) | daily ~6.9y | `crypto-tick/`, `crypto-candles/`, `crypto-hist/` |
| NewsAPI | Free | News headlines | — | `newsapi/` |

### Gaps (what's needed / flagged)

- **FX futures majors `6E 6J 6B 6A 6C 6S 6N`** — "no security definition" on paper
  (separate CME FX-futures entitlement). Only `6M` (MXN) resolves. → purchase decision pending.
- **L1 real-time for NYMEX energy + COMEX/NYMEX metals** — Error 354 (delayed-only)
  on paper, even though historical BARS work. L1 tick recorder streams CME+CBOT
  listings only (excludes delayed symbols). → separate real-time energy/metals subscription if needed.
- **IBKR historical depth is thin** (~3y index, ~16mo rates) — the *depth* gap is
  filled by yfinance (10-16y) + FRED (60y+). Free sources are research-grade depth,
  NOT a replacement for the paid archive.
- **FMP metrics/ratios/treasury = paid-only** (free tier returns `[]`). No substitute → flag.
- **Options on futures BARS (historical)** — not attempted; separate subscription.
  Only chain *metadata* (expiries + strikes) is captured.
- **L2 market depth** — separate paid package; top-of-book L1 only.
- **Schwab API = ON HOLD** (approval pending, NOT dropped).
- **Micro silver** (`SIL`) has no separate root — it is SI `tradingClass='SIL'`
  (multiplier 1000). Accessed via the SI chain.
- **Tick-level US equities data** (every-second) — NOT in the futures subscription;
  needs a paid real-time consolidated-tape feed. Tagged *"needed only if a future
  project needs tick-level stock data"* (see `docs/DATA-ENGINE.md` §10). **Do NOT buy.**
- **Deeper than ~8 days of 1m intraday** — yfinance hard-caps 1m at ~8 days;
  deeper 1m needs a paid intraday archive (research-grade only for now).

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
