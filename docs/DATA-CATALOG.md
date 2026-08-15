# Data Catalog — sources, prefixes, symbol registry, clientId map

Single source of truth for **what we collect**, **where it lives**, and **which
clientId touches IBKR**. Keep this current when you add a symbol or source.

The futures symbol registry lives in **`data/symbol_registry.py`** (one list ->
every collector). Adding an IBKR futures symbol = edit that one list + re-run
the collectors (see bottom).

---

## 1. Futures symbol registry (IBKR — CME Group bundle)

`data/symbol_registry.py::FUTURES` — 42 rows. One source of truth; `SYMBOLS`
(tuple list), `MONTHS`, `ASSET_CLASSES`, `OPTION_UNDERLYINGS` are derived exports.

| Asset class | Symbols | Exchange | Contract months | Options? |
|---|---|---|---|---|
| index | ES NQ MES MNQ RTY | CME | quarterly (3,6,9,12) | ES,NQ |
| index | YM MYM | CBOT | quarterly | — |
| index | M2K | CME | quarterly | — |
| rates | ZB ZN ZF ZT UB TN | CBOT | quarterly | ZB,ZN |
| energy | CL NG RB HO QM QG | NYMEX | monthly (1–12) | CL,NG |
| metals | GC SI HG MGC | COMEX | GC/MGC 2,4,6,8,10,12 · SI 1,3,5,7,9,12 · HG monthly | GC,SI,HG |
| metals | PL PA | NYMEX | PL 1,4,7,10 · PA quarterly | — |
| ags | ZC ZW ZS ZM ZL ZO | CBOT | grains (varies) | ZC,ZW,ZS |
| ags | HE LE | CME | livestock (varies) | — |
| fx | 6M | CME | quarterly | — |

**Resolution status (verified 2026-08-14 via reqContractDetails): 35/42 resolve.**
- ✅ Resolve: all index (8), all rates (6), all energy (6), metals GC/SI/HG/PL/PA/MGC (6), all ags (8), FX 6M.
- ⛔ **Subscription gap — "No security definition found":** FX majors `6E 6J 6B 6A 6C 6S 6N`. Only `6M` (MXN) resolves. Likely a separate CME FX-futures entitlement.
- ⛔ **Micro silver** (`SIL`) has **no separate root** — it is the SI chain's `tradingClass='SIL'` (multiplier 1000 vs full SI 5000). Access via the SI chain, not a `SIL` symbol. (MGC micro gold DOES have its own root.)

Contract months are used by the rollover-schedule derivation + `front_month_for()`
fallback; the collectors actually resolve the **active front via reqContractDetails**
(`bot/futures_contracts.py::resolve_front`) — exact for monthly/quarterly alike.

---

## 2. S3 prefixes (`trading-datalake-920641308584`)

| Prefix | Source | Shape | Written by |
|---|---|---|---|
| `futures-bars/daily/<sym>/<date>.json` | IBKR | daily OHLCV (CONTFUT-merged, idempotent) | `bot/backfill_bars.py`, `data/daily_collect.py` |
| `futures-bars/intraday/<sym>/<barsize>/<date>.json` | IBKR | 1h/15m/5m/1m RTH bars | same |
| `futures-ticks/<sym>/<date>/<ts>.jsonl` | IBKR L1 | top-of-book tick stream (RTH) | `bot/tick_recorder.py` |
| `contracts/<sym>/{contracts,rollover}.json` | IBKR | chain + rollover schedule | `bot/futures_contracts.py` |
| `sessions/<sym>/calendar.json` | IBKR (derived) | RTH/holidays/early-close | `bot/session_calendar.py` |
| `options/<sym>/chains.json` | IBKR | expiries + strikes (metadata only) | `data/options_chains.py` |
| `yf/<class>/<sym>.json` | yfinance | daily (max) + 1h (~2y) OHLCV | `data/yf_collect.py` |
| `yf/stocks/daily/<sym>.json` | yfinance | **US equities data engine** — full daily history (IPO→), ~6.9k common stocks | `data_engine/collect_daily.py` |
| `yf/stocks/intraday/<sym>/<interval>/<date>.json` | yfinance | data engine — 1h (~2y) + 1m (~8d rolling) session bars, liquid ~1k subset | `data_engine/collect_intraday.py` |
| `ibkr/equities/daily/<sym>.parquet` | **IBKR** | full daily history (20y+, `quality=BROKER`) — replaces yfinance for equities | `data/ibkr_full_backfill.py` |
| `ibkr/equities/1min/<sym>/<yyyy-mm>.parquet` | **IBKR** | 1-min month-partitioned (~2y, liquid ~1k) | `data/ibkr_full_backfill.py` |
| `ibkr/futures/daily/<sym>_continuous.parquet` | **IBKR** | CONTFUT daily continuous (~3y index / ~16mo rates) | `data/ibkr_full_backfill.py` |
| `ibkr/futures/daily/<sym>/<expiry>.parquet` | **IBKR** | per-contract daily (current chain, far-dated → up to ~4y) | `data/ibkr_full_backfill.py` |
| `ibkr/futures/1min/<sym>/<yyyy-mm>.parquet` | **IBKR** | 1-min RTH, front contract (16 liquid) | `data/ibkr_full_backfill.py` |
| `ibkr/crypto/daily/<sym>.parquet` · `ibkr/crypto/1min/<sym>/<yyyy-mm>.parquet` | **IBKR** | micro BTC/ETH (MBT/MET) daily ~9-12mo + 1-min | `data/ibkr_full_backfill.py` |
| `data-engine/universe/…` · `data-engine/meta/…` | Nasdaq Trader + yfinance | universe snapshot, liquid rank, collection manifest | `data_engine/universe.py` |
| `macro/<series>.json` | FRED | daily/monthly macro series | `data/fred_collect.py` |
| `fmp/<sym>/<Y>/<m>/<d>/<ts>.json` | FMP | quote+profile (fundamentals) | `data/fmp_ingest.py` |
| `newsapi/<Y>/<m>/<d>/<ts>.json` | NewsAPI | news batches | `data/newsapi_ingest.py` |
| `crypto-tick/<sym>/<Y>/<m>/<d>/<ts>.json` | Binance.US | spot ticks | `data/crypto_tick.py` |
| `crypto-candles/<sym>/<date>.json` | Binance.US | daily candle | `data/crypto_tick.py` |
| `research/scan-results/<name>/…` | — | strategy scan outputs | `bot/*_scan.py` |

`yf/` asset classes: `etfs` `sectors` `futures` `fx` `crypto` (crypto = BTC-USD/ETH-USD spot cross-check). `fx` = **28 yfinance spot pairs** (7 USD majors + 21 G7 crosses, e.g. `EURUSD=X` … `NZDCHF=X`); each object holds `daily` (max history) + `hourly` (730d) — free research-grade FOREX SPOT depth, distinct from the (ungapped) CME FX-*futures* entitlement in §5.

The **data engine** (`data_engine/`, a separate decoupled project) owns the
`yf/stocks/…` and `data-engine/…` namespaces. See `docs/DATA-ENGINE.md`.

---

## 3. DynamoDB keys (`trading-data`, single-table pk/sk)

| pk | sk | Meaning |
|---|---|---|
| `CONTRACT#<sym>` | `active` | active front contract (conId/expiry/multiplier) |
| `SESSION#<sym>` | `current` | next open/close, is_open, regular session |
| `QUOTE#<sym>` | `latest` | latest L1 bid/ask/last (futures + crypto) |
| `OPTCHAIN#<sym>` | `latest` | options chain counts + strike/expiry range |
| `FMP#<sym>` | `<date>` | FMP quote/profile snapshot |
| `RISK#<date>` / `RISK#<scope>` | — | persistent risk ledger |
| `RECONCILE/system` `INTENT#` `RUN#` `POSITION#` `SIGNAL#` | — | trading state (bots) |

---

## 4. IBKR clientId map (paper gateway `:4002`)

| clientId | Owner | Role |
|---|---|---|
| 70 | `bot/live.py` | index paper signals |
| 71 | `bot/live_bondsfx.py` | bonds (SHELVED, disarmed no-op) |
| 72 | `bot/live_intraday.py` | intraday MES |
| 73 | `bot/backfill_bars.py` + `bot/futures_contracts.py` | historical backfill + contract resolver |
| 74 | `bot/tick_recorder.py` | L1 tick stream (systemd) |
| 75 | `data/daily_collect.py` | daily delta collector |
| 76 | `hardening/reconciler.py` | broker reconciliation daemon |
| 77 | `data/options_chains.py` | options chain metadata |
| 90 | `data/backfill_futures_bars.py` | legacy backfill (kept) |
| 50 | `data/ibkr_full_backfill.py` | full-depth IBKR backfill (equities/futures/crypto/options) |
| 91–94 | ad-hoc probes | one-off gateway probes (not scheduled) |

---

## 5. Subscription gaps (need a SEPARATE IBKR subscription later)

1. **FX futures majors** `6E 6J 6B 6A 6C 6S 6N` — no security definition on paper (CME FX-futures entitlement). `6M` works.
2. **L1 real-time (reqMktData) for NYMEX energy + COMEX/NYMEX metals** — Error 354 "not subscribed" (delayed-only) on paper DUR193467, even though historical BARS work for the same symbols. The L1 tick recorder excludes these (`L1_LIVE` in the registry) so delayed ticks are never recorded as real-time. Live L1 on paper = CME + CBOT listings only (index/rates/ags/livestock/6M).
3. **Options on futures BARS** (historical) — NOT attempted; separate subscription. Only chain *metadata* (expiries+strikes) is captured.
4. **L2 depth** — separate paid package; we have top-of-book L1 only (no `reqMktDepth`).
5. **IBKR historical depth caps** (entitlement): daily ~3y index / ~16mo rates, intraday 1h/15m/5m ~1y, 1m ~30d. Free-source depth fills this: `yf/` (10–16y daily) + `macro/` (FRED 60y+).
6. **20y futures is NOT achievable on paper.** `reqContractDetails(includeExpired=True)` returns 0 expired contracts (only the full FUTURE chain); an expired contract month (`Future('ES','202006','CME')`) → Error 200 "No security definition". Verified 2026-08-15. Deep 20y futures remains yfinance `yf/futures/` only; IBKR futures daily = ~3-4y via CONTFUT + current-chain far-dated contracts.
7. **US options historical BARS** — separate paid subscription (NOT entitled on paper). Only chain *metadata* (expiries+strikes) is captured; option bars tagged "shallow by design".
8. **US equities real-time streaming (consolidated tape)** — the futures "CME Group" bundle does NOT cover stock L1. Equity bars are historical-only; real-time stock quotes need a separate subscription.

---

## 6. Adding a symbol

1. Edit `data/symbol_registry.py::FUTURES` (add a `dict(sym=…, exchange=…, asset_class=…, months=…, options=…)`).
2. Re-run (each is read-only, distinct clientId):
   ```
   ./venv/bin/python bot/futures_contracts.py    # CONTRACT# + contracts/
   ./venv/bin/python bot/session_calendar.py      # SESSION# + sessions/
   ./venv/bin/python bot/backfill_bars.py --symbols <NEW>   # futures-bars/
   ./venv/bin/python data/options_chains.py       # OPTCHAIN# + options/ (if options=True)
   ```
3. `data/daily_collect.py` (cron 23:20 UTC) picks it up automatically next tick.
