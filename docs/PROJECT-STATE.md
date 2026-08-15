# PROJECT-STATE — Data Coverage vs Gaps

At-a-glance map of what market data we have, from which source, at what depth — and what is
missing. Kept current by the trading-system operator (VPS Hermes). The standing rule that
governs this file: **never silently substitute free/stale data for critical paid data — flag
the gap and ask the owner whether to purchase the proper subscription.**

> The detailed **source/prefix/clientId/symbol-registry** truth lives in
> [`docs/DATA-CATALOG.md`](DATA-CATALOG.md) (owned by the data-collection project). This file
> is the *coverage-vs-gaps* view: what's covered, what's missing, and what's needed.

## Coverage (current)

| Source | Tier | What we get | Depth | Where |
|---|---|---|---|---|
| IBKR (paper, broker-verified) | **Paid / source of truth** | 42-symbol futures registry (34 resolve) across index/rates/energy/metals/ags/fx: daily + intraday (1h/15m/5m/1m) + L1 real-time ticks (`marketDataType=1`) | daily ~3y (index) / ~16mo (rates); intraday 1h/15m/5m ~1y; 1m ~30d | `futures-bars/`, `futures-ticks/`, `contracts/`, `sessions/`, `options/` |
| yfinance | Free / unofficial | ETFs, sectors, futures-continuous (`ES=F` etc), fx, crypto spot | daily ~10-16y; 1h intraday ~2y | `yf/` |
| FRED | Free / public | Macro series (DGS10/2/30, DFEDTARU, CPIAUCSL, UNRATE, PAYEMS, T10Y2Y, VIXCLS) | daily/monthly, 60y+ | `macro/` |
| FMP (free tier) | Free | Quote + company profile | — (QQQ→402 → use profile) | `fmp/` |
| Binance.US | Free | Crypto spot ticks + daily candles | — | `crypto-tick/`, `crypto-candles/` |
| NewsAPI | Free | News headlines | — | `newsapi/` |

## Gaps (what's needed / flagged)

- **FX futures majors `6E 6J 6B 6A 6C 6S 6N`** — "no security definition" on paper (separate
  CME FX-futures entitlement). Only `6M` (MXN) resolves. → purchase decision pending.
- **IBKR historical depth is thin** (~3y index, ~16mo rates) — the *depth* gap is filled by
  yfinance (10-16y) + FRED (60y+). Free sources are research-grade depth, NOT a replacement
  for the paid archive.
- **FMP metrics/ratios/treasury = paid-only** (free tier returns `[]`). No substitute → flag
  before any decision that needs fundamentals.
- **Options on futures BARS (historical)** — not attempted; separate subscription. Only chain
  *metadata* (expiries + strikes) is captured.
- **L2 market depth** — separate paid package; we have top-of-book L1 only.
- **Schwab API = ON HOLD** (approval pending, NOT dropped).
- **No long IBKR contract chain**: `reqContractDetails(includeExpired=True)` returns only ~4
  recent expiries — a full rollover schedule must be derived from the quarterly cycle.

## Current edge → data requirement

- **index-LONG (sole promoted edge)**: uses 16y yfinance futures-continuous. **NOT stale** —
  same CME contracts, adequate depth. **No purchase needed now.**
