# SPY Option-Flow Directional Signal — Data Requirements & Minimum-Cost Path

Research date: 2026-08-31. Verified by live fetch of vendor docs/pricing pages.

## Signal decomposition → exact fields required

The signal needs, per SPY option series (strike × expiration × call/put), per day:
1. **call/put** flag — inherent to contract identity.
2. **volume** (total traded) — for the flow magnitude.
3. **buy/sell** (aggressor side) — NOT in volume; needs trade-side classification or vendor open-close file.
4. **opening/closing** — NOT in volume; needs OCC-style open-close flag OR a proxy via Δ open interest.
5. **moneyness / strike / expiration** — contract metadata.
6. **bid/ask** (and/or mark) — for the single long-option P&L leg.
7. (nice-to-have) **open interest, IV, greeks** — for filters and for an OI-change open/close proxy.

## (1) CBOE daily put/call ratios — FREE but AGGREGATE, not per-symbol, not decomposed
- URL: https://www.cboe.com/us/options/market_statistics/daily/ (canonical: /markets/us/options/market-statistics/daily)
- Free, daily, historical CSV ("Download CSV").
- Series are asset-class / index aggregates only: TOTAL, EQUITY, INDEX, EXCHANGE TRADED PRODUCTS (ETF), VIX, SPX+SPXW, OEX, DJX, etc.
- **NOT per-symbol.** SPY is folded into the aggregate "Exchange Traded Products (ETP) put/call ratio" — all ETFs combined.
- **NOT decomposed** by buy/sell or open/close — just put volume ÷ call volume.

## (2) AlphaVantage HISTORICAL_OPTIONS — PREMIUM; has volume+OI+bid/ask+IV+greeks (no buy/sell, no open/close)
- URL: https://www.alphavantage.co/documentation/#historical-options ; pricing https://www.alphavantage.co/premium/
- Docs explicitly: "this is a premium API function. Subscribe to any of the premium membership plans to unlock historical options data."
- Verified via live demo call — returned fields per contract/date:
  contractID, symbol, expiration, strike, type (call|put), last, mark, bid, bid_size, ask, ask_size,
  **volume, open_interest**, date, **implied_volatility, delta, gamma, theta, vega, rho**.
- History since **2008-01-01**.
- **Minimum premium: $49.99/month** (75 req/min); tiers to $249.99/mo. (Annual ≈ 2 months off.)
- Call/put ✓, volume ✓, OI ✓ (→ ΔOI open/close PROXY), bid/ask ✓ (→ P&L), IV/greeks ✓.
- buy/sell ✗, open/close ✗ (only ΔOI proxy).

## (3) Vendors: fields / cost / history

### ORATS (orats.com/data-api) — best-value P&L + volume/OI history
- **Delayed Data API $99/mo** (20k req) — "Strikes + Near EOD History", "Core Data", IV Rank+History, daily price, HV, etc.
- Live Data API $199/mo (100k req); Live Intraday API $399/mo (1M req). Institution tier higher.
- Historical EOD option data **since 2007** (1-min intraday since Aug 2020).
- Provides bid/ask/IV/greeks/volume/OI per strike; NO buy/sell, NO open/close flag.

### CBOE DataShop — "Cboe Open-Close Volume Summary" — THE flow dataset (buy/sell × open/close)
- URL: https://datashop.cboe.com/cboe-options-open-close-volume-summary
- Categorizes **every trade** by participant type (Customer, Pro Customer, Broker-Dealer, Market Maker, Firm),
  **action (buy/sell)** and **position (open/close)**, plus contract-size buckets (<100, 100-199, >199).
- EOD / 10-min / 1-min; SFTP (Snowflake w/ restriction). Fields 10-17 = OHLC, total volume, open interest (EOD only).
- History: **C1 EOD since 2005-01-03**; C1 10-min 2011; C1 1-min 2019-10-07; BZX/C2/EDGX EOD 2018; BZX/C2/EDGX intraday 2019-03.
- Proprietary: internal use only; redistribution requires extra license.
- Pricing NOT published on page — "Fee Schedules filed with SEC (see LiveVol Fees)"; factsheet: "contact sales datasales@cboe.com." → the true per-symbol decomposed flow is a paid, sales-quoted, SEC-filed product (typically hundreds+ $/mo/exchange; not viable on a $700 account).

### OptionMetrics (institutional)
- **IvyDB US** since **Jan 1996**: EOD bid/ask quote, volume, OI, IV (American/European models), greeks (delta/gamma/vega/theta). URL: https://optionmetrics.com/data-products/equities/united-states/
- **TradeFlow** = their order-flow product (nav item; institutional/sales). URL: https://optionmetrics.com/data-products/tradeflow/ (page 404s publicly → sales-only).
- Pricing: institutional, via WRDS (academic) or sales; thousands $/yr. Overkill for a $700 account.

### Polygon (now "Massive", massive.com — was polygon.io/pricing)
- Options plans: **Basic $0/mo** (15-min delayed, 2y history), **Starter $29/mo** (4y), **Developer $79/mo** (5+y), **Advanced $199/mo** (real-time, non-pro).
- Data: all 17 US options exchanges — trades (tick), NBBO **quotes (bid/ask)**, aggregates (OHLCV), plus **open interest, greeks (delta/gamma/theta/vega), implied volatility** in contract/snapshot endpoints.
- History ~2012+ for options aggregates (plan-gated depth above).
- Call/put ✓, volume ✓, bid/ask ✓, OI/IV/greeks ✓ (current snapshot; historical OI/greeks series limited). buy/sell = raw tick trades only (self-classify), open/close ✗.

## (4) Free proxy feasibility — VERDICT

**Full signal as specified (SPY-specific, buy/sell × open/close) is NOT testable free.**
- Free CBOE P/C ratios are market-wide aggregates → they test a *different* (whole-market ETF-sentiment) hypothesis, not SPY-specific flow.
- Free per-symbol options data (OCC volume/OI reports, CBOE delayed quotes, Yahoo/Barchart current chains) is **current-snapshot only** — volume/OI/call/put for today, no clean historical archive, and **no historical bid/ask**, so the P&L leg cannot be backtested free either.

**Cheapest workable path = reduce the signal to what free-ish paid APIs actually carry:**
- call/put × volume × **ΔOI (open/close proxy)** → next-day direction → long-option P&L.
- **Minimum paid dataset: AlphaVantage HISTORICAL_OPTIONS @ $49.99/mo** (volume + OI + bid/ask + IV + greeks, since 2008). ORATS @ $99/mo (since 2007) is the alternative.
- The **buy/sell side** is the irreducibly-paid piece: only CBOE DataShop Open-Close (or OptionMetrics TradeFlow / tick-level Lee-Ready classification from paid tick data) provides it, and those are sales-quoted/SEC-filed products far above the $49.99/mo tier.

## Bottom line
- Free: NO (only market-wide aggregate P/C and non-historical current snapshots).
- Minimum paid for a near-complete test (call/put + volume + ΔOI + bid/ask + IV/greeks, since 2008): **AlphaVantage premium $49.99/mo** (or ORATS $99/mo since 2007).
- Exact buy/sell × open/close decomposition: **CBOE DataShop Open-Close Volume Summary** (paid, contact sales) — the only true "option-flow" dataset; likely cost-prohibitive vs. a $700 account.
