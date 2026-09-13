# News-Sentiment + Alternative-Data Equity Edges — verified candidate bank

Researched 2026-09-09 (subagent pass). Every number below was read from fetched text
(OpenAlex abstracts, NBER/SSRN-via-Wayback full text, DuckDuckGo HTML snippet of the
EconPapers abstract, jina full-page). Paywalled/absent numbers are marked NOT-EXTRACTED,
never estimated. Serper was out of credits; used the fallback ladder throughout.

**Cost prior (system-specific, from the brief):** ~6bp regular-hours round trip, whole-share,
long-only, ~$1.8k tradeable, sub-$50 names, 1–5-day holds preferred, no MOC/MOO.
Cross-sectional signals here are mostly MONTHLY/event rebalance (low turnover) → cost NOT
binding, but they are **long-short** in the literature → long-only leg ≈ half the spread,
and any SHORT-leg signal is an AVOIDANCE screen, not a buy signal.

---

## RANKED LIST (testability-on-FREE-data × edge × short-horizon fit)

### 1. "Lazy Prices" — SEC 10-K/10-Q textual-CHANGE drift  ← STRONGEST, FREE DATA
- **Rules:** compute the similarity (cosine on 4-gram/jargon vectors) between this quarter's
  filing and the prior one; "changers" (low similarity) vs "nonchangers" (high). Portfolio
  SHORTS changers / BUYS nonchangers. For long-only: **avoid/hold nonchangers, avoid newly
  changed filings** (or enter short side is impossible — use as an exclusion + the nonchanger
  long leg). Rebalanced around each filing (quarterly, ~low turnover).
- **Magnitude:** long-short alpha **up to 188 bp/month** (value-weight, Jensen alpha vs FF).
- **Citation:** Cohen, Malloy & Nguyen 2020, "Lazy Prices," *Journal of Finance* 75(3).
  DOI 10.1111/jofi.12885. Abstract verified via OpenAlex (cited-by 394).
- **Cost prior:** monthly/quarterly rebalance → ~6bp is immaterial; but the 188bp is LONG-SHORT
  gross — long-only nonchanger leg is a fraction. Still the largest gross alpha in this batch.
- **Free-data backtestable: YES.** SEC EDGAR full-text + bulk filing indexes are FREE (verified
  EDGAR full-text search API returns hits), Loughran-McDonald dictionary FREE. Labor = NLP diff
  engine on filings.
- **Verdict: ACTUAL EDGE** (documented, large, replicated-adjacent) — but gross is long-short.

### 2. Cross-sectional short-interest AVOIDANCE screen — FREE DATA, easy to test
- **Rules:** (a) Desai et al.: exclude/underweight the most heavily shorted names (highest
  short-interest ratio); (b) Boehmer et al.: heavily-shorted stocks underperform over the next
  ~20 trading days. Long-only translation = **exclusion filter on the buy universe** (and, if
  ever shortable, a short candidate).
- **Magnitude:** Desai et al. — heavily shorted firms earn **−0.76 to −1.13%/month** abnormal
  (Nasdaq 1988–1994, controlling size/BTM/momentum). Boehmer et al. — heavily shorted
  underperform lightly shorted by **1.16% over 20 trading days** (NYSE 2000–2004).
- **Citation:** Desai, Ramesh, Thiagarajan & Balachandran 2002, *JF* 57(5), DOI
  10.1111/0022-1082.00495; Boehmer, Jones & Zhang 2008, *JF* 63(5), DOI
  10.1111/j.1540-6261.2008.01324.x. Both verified via OpenAlex (cited 688 / 975).
- **Cost prior:** an exclusion screen has ~zero direct cost; it raises the quality of remaining
  buys. As a SHORT signal it's untradeable here (long-only).
- **Free-data backtestable: YES.** FINRA publishes bi-monthly short interest AND daily short-sale
  volume files (free .txt, verified present on finra.org). Nasdaq/NYSE short interest free.
- **Verdict: ACTUAL EDGE** (as an avoidance/quality screen), decay uncertain post-2008.

### 3. Opportunistic insider purchases (Cohen–Malloy–Pomorski) — FREE DATA, heavy parsing
- **Rules:** classify insiders as **routine** vs **opportunistic** by whether they traded in the
  same calendar month for each of the prior 3 years. BUY (long-only) names where an
  opportunistic insider PURCHASES (open-market buys; ignore routine trades and all sales).
  Hold ~1 month; rebalance monthly.
- **Magnitude:** a portfolio following **opportunistic** insider trades earns value-weight
  abnormal returns of **82 bp/month**; routine-trader abnormal returns are **essentially zero**
  (routine trades > half the insider-trade universe).
- **Citation:** Cohen, Malloy & Pomorski 2012, "Decoding Inside Information," *JF* 67(3);
  NBER w16454. Verified full text via jina on the NBER PDF (the 82 bp/month sentence read
  verbatim); DOI 10.3386/w16454 (cited 239).
- **Cost prior:** monthly rebalance → cost immaterial; no short needed for the buy leg.
- **Free-data backtestable: YES (with effort).** SEC EDGAR Form 4 is FREE and complete
  (verified EDGAR full-text search API works). FMP's insider endpoints are **DEAD on this key**
  (all `v3/v4/stable/insider-*` return "Legacy Endpoint" → paid tier). The hard part is the
  3-year same-month routine/opportunistic classification + insider-history DB.
- **Verdict: ACTUAL EDGE** (documented, robust, free data) — but the classification step is
  real work; decays as it's a well-known strategy.

### 4. Analyst-forecast DISPERSION avoidance (Diether–Malloy–Scherbina) — FREE-ish proxy
- **Rules:** exclude/underweight high-dispersion names (large std of analyst EPS estimates).
  Long-only translation = **avoid high-dispersion** (they're overpriced under short-sale
  constraints); effect strongest in small stocks + prior losers.
- **Magnitude:** higher dispersion → LOWER future returns (decile spread magnitude paywalled;
  direction + "most pronounced in small/poorly-performing" verified from abstract).
- **Citation:** Diether, Malloy & Scherbina 2002, *JF* 57(5), DOI 10.1111/0022-1082.00490.
  OA PDF at scholarsarchive.byu.edu (verified; cited 2290).
- **Cost prior:** avoidance screen, ~zero direct cost.
- **Free-data backtestable: PARTIAL.** FMP `stable/analyst-estimates` returns `epsHigh/low/avg`
  (free snapshot, verified in prior pass) → dispersion = (high−low)/|avg| is a FREE proxy TODAY,
  but it's a current snapshot, not point-in-time history (same limitation as the banked
  revision-momentum finding).
- **Verdict: ACTUAL EDGE** (documented) as an exclusion; needs DIY point-in-time polling.

### 5. News-tone MOMENTUM (underreaction) — Sinha / Heston–Sinha — PAID DATA (RavenPack-class)
- **Rules:** weekly news-tone score per stock (aggregate article tone); LONG past-positive-tone,
  SHORT past-negative-tone. Long-only = buy high-tone names; hold 1–13 weeks. Daily news tone
  predicts 1–2 days; WEEKLY tone predicts a full quarter (Heston–Sinha).
- **Magnitude:** long-short tone portfolio **16.54 bp/week = 8.60%/yr** (Sinha). Heston–Sinha:
  daily news → 1–2 days, weekly news → 1 quarter (900k stories, Thomson Reuters neural net).
- **Citation:** Sinha 2016, "Underreaction to News in the US Stock Market," *Quarterly Journal
  of Finance* 6(3), DOI 10.1142/s2010139216500051 (abstract verified; 16.54bp/wk read verbatim).
  Heston & Sinha 2017, "News vs. Sentiment," *Financial Analysts Journal* 73(3), DOI
  10.2469/faj.v73.n3.3 (abstract verified).
- **Cost prior:** 13-week hold → low turnover; long-short gross → long-only ≈ half of 8.6%/yr.
- **Free-data backtestable: NO (practically).** Point-in-time, ticker-mapped news sentiment =
  RavenPack / Refinitiv (PAID). GDELT is free but (a) 5s/request rate limit (verified message),
  (b) **no ticker mapping** (company-name matching only), (c) poor historical per-ticker
  backfill. DIY-scrape is possible but noisy.
- **Verdict: ACTUAL EDGE** (documented, strong) — data acquisition is the whole cost.

### 6. Put-call ratio (Pan–Poteshman) + O/S ratio (Johnson–So) — PAID DATA (option volume)
- **Rules:** (a) put-call ratio from buyer-initiated open positions → LOW P/C = bullish, buy;
  (b) option-to-stock volume ratio (O/S) → LOW O/S decile = bullish, buy; high O/S = bearish.
  Both are 1-day-to-1-month directional option-VOLUME signals (NEW — the bank has RV-IV /
  dealer-gamma / VRP, but NOT these directional-volume signals).
- **Magnitude:** Pan–Poteshman — low P/C beats high P/C by **>40bp next day and >1%/week**.
  Johnson–So — lowest O/S decile beats highest by **1.47%/month** risk-adjusted (stronger when
  short-sale costs high / option leverage low; predicts firm-specific earnings news).
- **Citation:** Pan & Poteshman 2006, *RFS* 19(3), DOI 10.1093/rfs/hhj024 (abstract verified;
  >40bp/>1% read verbatim; cited 913). Johnson & So 2012, *JFE* 106(2), DOI
  10.1016/j.jfineco.2012.05.008 (1.47%/mo read verbatim from SSRN-via-Wayback abstract;
  cited 351). Ge, Lin & Pearson 2016, *JFE* 120(3), DOI 10.1016/j.jfineco.2015.08.019 (why O/S
  predicts — earnings/announcement channel; cited 223).
- **Cost prior:** the >40bp/day leg is high-turnover but the gross >> cost; 1.47%/mo is
  low-turnover. BUT both are long-short → long-only leg ≈ half, and the daily leg needs
  buyer-initiated flow (proprietary) not just OI.
- **Free-data backtestable: NO.** Historical per-stock option volume + buyer-initiation =
  CBOE/OPRA/ORATS/LiveVol (PAID). AlphaVantage has no options endpoint.
- **Verdict: ACTUAL EDGE** (documented) — data is the blocker; best short-horizon gross in batch.

### 7. Aggregate short interest = market-timing overlay (Rapach–Ringgenberg–Zhou) — FREE DATA
- **Rules:** detrend aggregate (market-wide) short interest; HIGH aggregate SI → reduce equity
  exposure next month. This is a MARKET-timing signal, not a stock picker — usable here only as
  an exposure-on/off overlay on the long-only book, not a candidate generator.
- **Magnitude:** "arguably the strongest known predictor of aggregate stock returns" — in-sample
  annual R² **12.89%**, out-of-sample **13.24%** (beats popular predictors; utility gains > …).
- **Citation:** Rapach, Ringgenberg & Zhou 2016, *JFE* 121(1):46–65, DOI
  10.1016/j.jfineco.2016.03.004 (abstract verbatim from DuckDuckGo→EconPapers snippet; cited 603).
  **Free data + code** (SII index 1973–2021) posted by the authors.
- **Cost prior:** monthly on/off → minimal cost.
- **Free-data backtestable: YES** (author-posted SII data + FINRA). 
- **Verdict: ACTUAL EDGE** (documented) — but WRONG SHAPE for this system (timing overlay,
  not a 1–5-day long-only stock signal). Listed for completeness.

### 8. Insider direction (aggregate) — weaker, supporting evidence only
- **Rules:** insiders are contrarian and their trades predict market moves better than naive
  contrarian strategies (Lakonishok–Lee); purchase portfolios earn abnormal returns (Jeng et al.
  ~6%/yr purchase portfolios).
- **Citation:** Lakonishok & Lee 2001, *RFS* 14(1), DOI 10.1093/rfs/14.1.79 (abstract verified;
  cited 1336). Jeng, Metrick & Zeckhauser 2003, *REStat* 85(3), DOI
  10.1162/003465303765299936 (abstract verified; cited 589).
- **Verdict: EVIDENCE OF EDGE** but subsumed by #3 (CMP opportunistic filter is the sharp form).

---

## Lower-priority / negative verdicts (do NOT queue for backtest)

### 9. News-tone REVERSAL (Tetlock 2007) — market-level, not a stock signal
- High media pessimism (WSJ column) → downward price pressure **followed by reversion**; extreme
  pessimism → high volume. *JF* 62(3), DOI 10.1111/j.1540-6261.2007.01232.x (abstract verified;
  cited 4661). Market-level (DJIA) → not a sub-$50 stock picker. **Verdict: EVIDENCE OF NO EDGE
  for this system's lane** (it's a market-timing fade, data also paid).

### 10. Garcia 2013 NYT-sentiment — same shape, recession-gated
- NYT financial-news sentiment (1905–2005) predicts Dow returns, concentrated in recessions.
  *JF* 68(3), DOI 10.1111/jofi.12027 (abstract verified; cited 1190). Market-level + recession
  regime → **INSUFFICIENT DATA for a tradeable long-only stock edge** without regime gating.

### 11. Sticky expectations / analyst stickiness (Bouchaud et al.) — factor explanation, not signal
- Bouchaud, Krüger, Landier & Thesmar 2018, "Sticky Expectations and the Profitability Anomaly,"
  *JF* 74(2), DOI 10.1111/jofi.12734 (abstract verified; cited 286). Explains profitability via
  sluggish analyst forecasts; firm-level "stickiness" predicts returns but overlaps the banked
  revision-momentum family. **Verdict: EVIDENCE OF NO EDGE as a NEW standalone signal** (subsumed).

### 12. Selective analyst coverage (Das–Guo–Zhang 2006) — IPO-coverage signal, weak fit
- Residual analyst coverage predicts newly-public-firm performance. *JF* 61(3), DOI
  10.1111/j.1540-6261.2006.00869.x (cited 181). **Verdict: INSUFFICIENT DATA** (IPO-specific,
  not the sub-$50 liquid universe).

### 13. Readability / tone-LEVEL (Loughran–McDonald 2011/2014, Li 2008) — weak/no direct edge
- LM 2011 (*JF*, DOI 10.1111/j.1540-6261.2010.01625.x, cited 1372): Harvard dict misclassifies
  ~3/4 of "negative" words in 10-Ks → build the LM financial dictionary (FREE, published).
  LM 2014 (*JF*, DOI 10.1111/jofi.12162, cited 1523): Fog index poorly specified; file size =
  simple readability proxy. Li 2008 (*JAE*, DOI 10.1016/j.jacceco.2008.02.003, cited 2816):
  harder-to-read reports → lower earnings persistence.
  These are **inputs** (dictionary + readability measure) to #1 (Lazy Prices), not standalone
  edges. **Verdict: EVIDENCE OF NO EDGE as standalone**; use as building blocks.

### 14. 8-K volume/return around filing (Lerman–Livnat) — thin, event-study
- The new Form 8-K disclosures → abnormal volume + return around 8-K filing. *Review of
  Accounting Studies* 15(4), DOI 10.1007/s11142-009-9114-7 (OA via NYU archive; cited 215).
  **Verdict: INSUFFICIENT DATA** — magnitude/robustness for a systematic edge not established.

### 15. Dark-pool prints — no documented retail-tradeable directional edge
- Dark pool trading strategies / dark trading & price discovery: Buti, Rindi & Werner 2016
  (*JFE*, DOI 10.1016/j.jfineco.2016.02.002, cited 141); Comerton-Forde & Putniņš 2015
  (*JFE*, DOI 10.1016/j.jfineco.2015.06.013, cited 213). These study market quality, welfare,
  and price discovery — **no paper documents a directional edge from "dark-pool prints" a retail
  long-only account can harvest**. Dark-pool/ATS print data itself is PAID (FINRA CAT/TRF).
  **Verdict: EVIDENCE OF NO EDGE** (as a tradeable signal).

---

## FREE vs PAID backtestability — quick matrix

| Signal | Data source | Free today? |
|---|---|---|
| Lazy Prices (10-K/Q change) | SEC EDGAR bulk + full-text | **FREE** (heavy NLP) |
| Short-interest avoidance | FINRA bi-monthly + daily short-sale vol files | **FREE** |
| Opportunistic insider | SEC EDGAR Form 4 | **FREE** (heavy parsing); FMP insider = paid/dead |
| Analyst dispersion | FMP `analyst-estimates` high/low (snapshot) | **partial** (not point-in-time) |
| News-tone momentum | RavenPack / Refinitiv; GDELT (no ticker, 5s cap) | **PAID** (GDELT DIY is noisy) |
| Put-call / O/S ratio | CBOE/OPRA/ORATS/LiveVol option volume | **PAID** |
| Aggregate short-interest timing | author-posted SII data + FINRA | **FREE** (market overlay) |
| Dark-pool prints | FINRA CAT/TRF | **PAID** |

## Recommended backtest order (for the parent agent)
1. **Short-interest avoidance** (#2) — cheapest, free FINRA data, immediate buy-universe filter.
2. **Analyst-dispersion avoidance** (#4) — FMP snapshot proxy, immediate filter.
3. **Lazy Prices** (#1) — highest gross alpha, free EDGAR, but needs an NLP diff engine
   (worth building given 188bp/mo headline).
4. **Opportunistic insider** (#3) — free Form 4, but needs the routine/opportunistic classifier.
5. **News-tone momentum** (#5) — queue only if a paid news-sentiment feed (RavenPack/Refinitiv)
   or a GDELT company-name-mapping pipeline is funded.
6. **Put-call / O/S** (#6) — queue only if option-volume history is purchased.
