# Crypto Trading Venues + Robinhood AI Leverage (research, 2026-08-24)

Ground-truth findings from live probes + official docs. Owner directive: crypto
must be **blue-chip only** (BTC/ETH/XRP) and traded as **fractional** on
Robinhood + IBKR first, later moving out to dedicated exchanges.

## 1. Robinhood — crypto

- Robinhood has a **separate Robinhood Crypto Trading API** (NOT the equities
  MCP at `agent.robinhood.com/mcp/trading`). Docs:
  https://robinhood.com/us/en/support/articles/crypto-api/ and
  https://docs.robinhood.com/ — "view crypto market data, access account info,
  and place crypto orders programmatically."
- **Fractional**: yes ("buy or sell crypto at fractional amounts").
- **XRP**: YES — Robinhood lists XRP (plus BTC, ETH, DOGE, LTC, BCH, BNB, SOL,
  and ~20+ more). Confirmed via coin-availability doc.
- **Our current integration does NOT touch crypto.** The equities MCP
  `tools/list` (live, 2026-08-24) shows ONLY equity/option/watchlist/scan tools —
  zero `*crypto*` tools. So crypto needs its own client + credentials.
- Crypto account enablement + API credentials = **owner-gated OAuth** (one-time).

## 2. Interactive Brokers — crypto (Paxos)

- Crypto via **Paxos Trust** (+ Zero Hash). Live probe on paper account
  `DUR193467` (clientId 98, 2026-08-24) resolves these contracts:
  **BTC ✓ ETH ✓ LTC ✓ BCH ✓ SOL ✓** — and **XRP ✗ (Error 200: no security definition)**.
- **XRP is NOT available on IBKR.** Venue-dependent universe:
  RH = BTC/ETH/XRP; IBKR = BTC/ETH (or +LTC/BCH/SOL, but not XRP).
- **Fractional**: yes (crypto trades in fractional units; ~$10 min order).
- Commission: 0.12%–0.18% of trade value, **$1.75 minimum** per order.
- **Paper account CANNOT trade crypto (verified 2026-08-24):** orders require
  `cashQty` (USD) — a `totalQuantity` order is rejected Error 10289 — but on
  paper (DUR193467) crypto orders sit `PendingSubmit` forever (no fill). PAXOS
  crypto is **live-only**; paper does not simulate it. So IBKR crypto execution
  is blocked until the LIVE account (U26949861) is funded + crypto enabled.
  The lane scaffolding lives in `bot/live_crypto_ibkr.py` (correct, dormant).
- Paper account DUR193467 resolves crypto contract definitions (view-only) but
  cannot execute (see above). Live crypto needs the live gateway (U26949861,
  `ibgateway-live` currently DISABLED/unfunded).

## 3. Robinhood "AI" — what is actually leverable

- **Robinhood Cortex** is the AI investing assistant ("design custom indicators
  in plain English", trade ideas). **Cortex Digests** = daily AI research
  digests. Both are **APP-ONLY** — there is NO public API for Cortex's advice.
- **The programmatic leverage is the trading MCP's research tools**, already
  authenticated and NOT yet used by this system:
  - `run_scan` / `create_scan` / `get_scanner_filter_specs` / `get_scans` —
    Robinhood's own screener (curated + custom scans = Robinhood's "picks").
  - `get_equity_technical_indicators` — RSI/MACD/SMA/etc. per symbol.
  - `get_equity_fundamentals` / `get_financials` — fundamentals.
  - `get_earnings_calendar` / `get_earnings_results` — earnings catalyst feed
    (real intraday/swing signal source).
  - `get_equity_historicals`, `get_equity_price_book`, `get_index_quotes`.
- Full live tool list (2026-08-24): accounts/portfolio/pnl, equity quotes/orders/
  positions/tax-lots/fundamentals/historicals/technical-indicators/tradability,
  options chains/orders/positions, watchlists, and **scans/screener**.

## 4. Recommendation

Highest-value, zero-friction first step = **wire the MCP research tools into a
signal-research lane** (screener + technicals + earnings → RSI2/breadth feed).
Crypto trading: build the **IBKR crypto paper lane** now (no gating), and the
**Robinhood Crypto API client** in parallel (owner-gated OAuth).
