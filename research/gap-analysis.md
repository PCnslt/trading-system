# Trading-System Gap Analysis — Free Data/Features & Overlooked Tools (verified 2026-08-30)

Scope: live US-equities, long-only, fractional, ~$700 flexible capital. Exec: Robinhood (quotes+orders), IBKR (historical daily+1min). Keys held: FMP, AlphaVantage, NewsAPI, Serper, Binance.US. Currently used: daily+1min OHLCV, news keyword gate (NewsAPI), earnings calendar, market-regime light.

Legend: [VERIFIED] = live-probed on the operator's actual key / endpoint this session. [DOC] = documented free, verify on key. [PROBE] = guessed path 404'd; verify exact /stable/ name (may be paid).

---

## PRIORITY 1 — Under-used FREE features on keys you ALREADY hold (zero new accounts)

### 1. AlphaVantage NEWS_SENTIMENT — replace the keyword news gate with scored sentiment  [VERIFIED free]
- **Unlocks:** per-article sentiment score (−1..+1), ticker-relevance score, topic tags (earnings, ipo, mergers_and_acquisitions, economy_monetary…), source. Aggregate to a per-ticker bullish/bearish score + volume of coverage — a real signal, not "did the word match".
- **Why it matters:** the current NewsAPI gate is keyword-only and ~24h delayed. This is live, ticker-targeted, and carries a numeric sentiment you can backtest against next-session return.
- **Free** (25 req/day cap — batch + cache). Endpoint: `https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers=AAPL&apikey=…`
- Docs: https://www.alphavantage.co/documentation/#news-sentiment

### 2. AlphaVantage INSIDER_TRANSACTIONS — Form-4 insider buy/sell feed  [VERIFIED free]
- **Unlocks:** insider cluster-buy screens (multiple officers buying near a low), buy/sell ratio, transaction type + shares + price.
- **Why:** insider buying is one of the best-documented short-to-intermediate-horizon catalysts and you currently have zero access to it.
- Endpoint: `https://www.alphavantage.co/query?function=INSIDER_TRANSACTIONS&symbol=AAPL&apikey=…`
- Docs: https://www.alphavantage.co/documentation/#insider-transactions

### 3. AlphaVantage EARNINGS (history + surprise %) + EARNINGS estimates  [VERIFIED free (calendar); DOC]
- **Unlocks:** actual-vs-estimate surprise ranking → post-earnings-drift (PEAD) lane; estimate-revision drift from EARNINGS estimates.
- **Why:** your current earnings calendar gates dates but doesn't quantify surprise — PEAD is the strongest short-horizon earnings signal and needs only surprise magnitude + direction.
- `function=EARNINGS&symbol=AAPL` (history + surprise%), `function=EARNINGS&symbol=AAPL` + `EARNINGS` estimates via `function=EARNINGS` … see docs.
- Docs: https://www.alphavantage.co/documentation/#earnings

### 4. AlphaVantage CONGRESS_TRADES  [DOC free / "Trending"]
- **Unlocks:** STOCK-Act politician trades (Pelosi-index-style). High retail attention → short-horizon momentum; also a news-magnet.
- Endpoint: `function=CONGRESS_TRADES`
- Docs: https://www.alphavantage.co/documentation/#congress-trades

### 5. AlphaVantage TOP_GAINERS_LOSERS + SECTOR  [DOC free]
- **Unlocks:** daily relative-strength/momentum universe scan (biggest movers) and sector-rotation signal. SECTOR gives live 11-sector performance — sharpen your "market-regime light" into a sector-breadth regime.
- Endpoints: `function=TOP_GAINERS_LOSERS`, `function=SECTOR`
- Docs: https://www.alphavantage.co/documentation/#top-gainers-losers , https://www.alphavantage.co/documentation/#sector

### 6. AlphaVantage INSTITUTIONAL_HOLDINGS (13F)  [DOC free]
- **Unlocks:** ownership-change signal (quarterly 13F delta). Lower short-horizon value than the above; keep as enrichment.
- Endpoint: `function=INSTITUTIONAL_HOLDINGS` — https://www.alphavantage.co/documentation/#institutional-holdings

### 7. FMP dividends + splits  [VERIFIED free — 200 on your key]
- **Unlocks:** ex-dividend calendar (avoid buying into a −div gap; or dividend-capture) AND split-adjusted gap detection (a 4:1 split reads as a fake "−75% drop" — this poisons any "down X% buy-the-close" signal).
- **Why:** directly protects the close-to-open / gap strategies already in the portfolio from false signals.
- Endpoints: `https://financialmodelingprep.com/stable/dividends?symbol=AAPL&apikey=…`, `…/stable/splits?symbol=AAPL&apikey=…`

### 8. FMP analyst-estimates  [VERIFIED endpoint exists — needs `period` param]
- **Unlocks:** analyst estimate + revision data (revision momentum is a real short-horizon factor).
- Endpoint: `https://financialmodelingprep.com/stable/analyst-estimates?symbol=AAPL&period=annual&limit=10&apikey=…` (probe; the 400 said "missing period").
- ⚠ FMP free-tier caveat (consistent with prior session probes): insider-trading, institutional-ownership, ratings, social-sentiment, earnings-surprises, press-releases, sec-filings, etf-holder, market-hours, historical-price-full all 404'd on guessed `/stable/` names — either renamed or paid. Probe correct names before relying on FMP for these; **AlphaVantage covers most of them free anyway.**

---

## PRIORITY 2 — Free sources NOT wired (new integration, no paid key)

### 9. SEC EDGAR full-text search + submissions + company-facts  [VERIFIED live]
- **Unlocks:** 8-K catalyst feed (guidance, buybacks, offerings, M&A, pre-announcements), direct Form-4 filings, quarterly fundamentals via XBRL. 8-Ks are THE short-horizon catalyst stream and you currently have none.
- **Why:** free, authoritative, no key, real-time — the highest-value source not yet wired.
- Endpoints:
  - Search UI: https://www.sec.gov/edgar/search/
  - Search API: `https://efts.sec.gov/LATEST/search-index?q=<query>&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD` (returns JSON; set a `User-Agent` header)
  - Submissions: `https://data.sec.gov/submissions/CIK##########.json`
  - Company facts (XBRL): `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
- Rate limit: ~10 req/sec, no key. https://www.sec.gov/developer

### 10. FINRA short-sale volume (daily) + short interest (bi-monthly)  [VERIFIED 200]
- **Unlocks:** short-squeeze / crowded-short screen (high short interest + rising price = squeeze fuel); daily short-sale volume as a sentiment proxy.
- **Free.** https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data and https://www.finra.org/finra-data/browse-catalog/equity-short-interest

### 11. Federal Reserve FOMC calendar + press releases  [VERIFIED 200]
- **Unlocks:** macro event-risk gate — don't hold through FOMC / CPI / NFP. Add as a "skip day" guard on top of your market-regime light.
- https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm and https://www.federalreserve.gov/newsevents/pressreleases.htm

### 12. CME FedWatch — rate-path probabilities  [bot-blocked for curl; scrape or use embedded JSON]
- **Unlocks:** hawkish/dovish regime tilt (probability of cut/hike) as a regime conditioner for the light model.
- https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html

### 13. FRED — you already pull macro/, extend the SERIES list (regime upgrade)  [DOC]
- **Add:** `BAMLH0A0HYM2` (ICE BofA high-yield OAS — credit stress), `BAA10Y` (credit spread), `DFF` (fed funds), keep `VIXCLS`/`T10Y2Y`.
- **Unlocks:** a proper risk-on/risk-off regime model instead of a single "light" indicator. Free, no key. `https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2`

### 14. ETF flows — semi-manual free  [DOC]
- **Unlocks:** sector/asset-class flow momentum (where money is rotating). No clean free API; scrape daily tables.
- State Street daily flows: https://www.ssga.com/us/en/intermediary/etfs/insights ; ETF.com: https://www.etf.com/sections/daily-etf-flows

---

## PRIORITY 3 — Overlooked strategy families & risk tools (data now available from 1–14)

| Strategy / tool | Feeds it needs | What it unlocks |
|---|---|---|
| Relative volume (RVOL) + sector relative strength | existing bars + AV SECTOR / FMP sector-performance | breakout/momentum day-scan on liquid names |
| Post-earnings-drift (PEAD) | AV EARNINGS surprise + EARNINGS_CALENDAR | rank names by surprise, hold drift |
| Insider cluster-buy | AV INSIDER_TRANSACTIONS | contrarian accumulation signal |
| Congress-trade mirror | AV CONGRESS_TRADES | retail-attention momentum |
| Short-squeeze screen | FINRA short interest + volume | crowded-short reversal |
| 8-K event catalyst | SEC EDGAR | guidance/buyback/offering/M&A event trades |
| Sector rotation | AV SECTOR / FMP sector-performance | regime-conditioned universe tilt |

Risk tools you're missing:
- **Macro event gate** (FOMC/CPI/NFP calendar) — avoid holding through binary events (#11).
- **Regime model upgrade** — credit spreads + VIX/realized-vol ratio (variance-risk-premium proxy) from FRED + your bars (#13). Note: full VIX *term structure* is NOT computable (no VX futures in the lake) — use VIX level + VIX/realized-vol instead.
- **Ex-dividend & split calendar** (#7) — kills false "−X% gap" signals and accidental dividend-fall buys.
- **Sector concentration/breadth check** — AV SECTOR.

---

## Constraints / caveats
- **AlphaVantage free = 25 req/day** (I consumed 3 this session). Batch + cache aggressively (DynamoDB `AV#<fn>#<sym>` / S3 `alphavantage/…`), don't poll live per-ticker.
- **FMP free tier is thin** on catalyst endpoints (insider/institutional/ratings/sentiment/surprise all need correct `/stable/` names or are paid). Use AlphaVantage for those — it's the richer free source for short-horizon catalysts.
- **NewsAPI stays** only for broad headline discovery; NEWS_SENTIMENT supersedes it for signal.
- **No free options IV/put-call ratio** (AlphaVantage realtime options = Premium). Leave options-flow signals out of the free plan.
