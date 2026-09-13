# BOOKS · COURSES · TALKS — INTRADAY & CLOSE-TO-OPEN EQUITY DAY-TRADING CANDIDATES

Date: 2026-08-25 · Miner: VPS Hermes subagent · **Research only, paper-first, no live wiring.**
Scope: strategies with EXACT rules for (A) same-day intraday entry→exit-before-close, and
(B) close-to-open / buy-the-close overnight holds.

## Sourcing & honesty ledger (read first)

| Source class | What I actually got | Verdict |
|---|---|---|
| Larry Connors / Cesar Alvarez books | Rules + Connors' OWN reported stats, via a 2010 practitioner post that reproduces all 6 *High Probability ETF Trading* systems with his backtest figures; plus Alvarez's own blog; plus Quantitativo's re-implementation quoting the book rules verbatim | **STRONG** |
| Toby Crabel *Day Trading With Short Term Price Patterns and ORB* (1990) | Exact ORB/Stretch/NR definitions with **page citation (p. 167)**; PLUS Crabel's own 2026 Substack revising the method | **STRONG on rules, WEAK on numbers** |
| Raschke & Connors *Street Smarts* | 80-20 rules reproduced with book attribution | MEDIUM (secondary) |
| University course material | Hasbrouck (NYU Stern), *Securities Trading: Principles and Procedures*, 2024 draft, free PDF — auction/MOC/MOO mechanics | **STRONG for execution realism, no strategy** |
| Peer-reviewed / working papers | Basdekidou 2017 (open-access, full PDF read); Zarattini–Aziz–Barbon ORB & intraday-momentum (abstracts + CXO rule reconstructions) | **STRONG** |
| Conference talks / podcasts | Connors' own transcribed TraderTalk workshop (tradingmarkets.com, 2002) = CVR3 primary source. YouTube transcript route **FAILED** (401 from r.jina.ai; no API key) | PARTIAL |
| archive.org full-text | **FAILED** — `numFound: 0` for all four target books; they are lending-only and not in the full-text index. No page-level quotes obtainable legally | **FAILED — declared** |

**Rules I obeyed:** no pirated PDFs used (pdfcoffee / scribd / coursehero / z-library / epdf appeared in
results and were **deliberately not fetched**). Every number below carries a URL or book+page. Numbers
that exist only inside chart images are marked **NOT-EXTRACTED** per the chart-only rule. Nothing is
reconstructed from memory.

**Cost yardstick used throughout:** 6 bp = 0.06% round trip on notional.

---

# RANKED CANDIDATES

Ranking = testability × edge size × fit to (A) intraday or (B) close-to-open.

---

## 1. Connors/Alvarez *High Probability ETF Trading* — the 6-system ETF mean-reversion suite  ★ top pick
**Fit: B-adjacent (buy the close, hold 3–7 days, exit on close). Closest published analogue to the RSI(2) book we already run.**

**Thesis:** In an ETF above its 200-day MA, short-horizon selling exhaustion (measured 6 different
ways) reverts within ~3–6 sessions; buy the close of the exhaustion day.

**Universe (Connors' own, verbatim):** DIA, EEM, EFA, EWH, EWJ, EWT, EWZ, FXI, GLD, ILF, IWM, IYR,
QQQQ(→QQQ), SPY, XHB, XLB, XLE, XLF, XLI, XLV — 20 liquid ETFs.

**Common frame:** long only when Close > MA(200); short only when Close < MA(200). **Entry = market-on-close
of the signal day (16:00 ET). Exit = market-on-close of the day the exit condition prints.** No stops in the
published version. Sizing: 1 unit/signal; "aggressive" variant doubles down on a second signal against you.

| # | System | Long entry (all require Close>MA200) | Long exit | Connors' reported: n / win% / avg gain / avg hold |
|---|---|---|---|---|
| 1 | **3-Day High/Low** | Close<MA(5) AND 3 consecutive lower lows AND 3 consecutive lower highs | Close > MA(5) | 709 / **76.9%** / **+0.66%** / 3.3 d |
| 2 | **RSI(4)** | RSI(4) < 25 | RSI(4) > 55 | 786 / **76.7%** / **+1.06%** / 6.2 d |
| 3 | **R3** | RSI(2) falling 3 days AND RSI(2) 3d ago < 60 AND RSI(2) < 10 | RSI(2) > 70 | 700 / **75.9%** / **+0.92%** / 5.0 d |
| 4 | **%B** | BB %B(20,2) < 0.2 on each of last 3 days | %B > 0.8 | 1,014 / **76.5%** / **+0.70%** / 4.2 d |
| 5 | **Multiple Days Down** | Close<MA(5) AND close lower on 4 of last 5 days | Close > MA(5) | 1,071 / **73.6%** / **+0.50%** / 3.3 d |
| 6 | **RSI(2) 10/6** | RSI(2) yesterday < 10 AND RSI(2) today < 6 | Close > MA(5) | 1,075 / **81.9%** / **+0.93%** / 3.7 d |

Short side mirrors exactly (Close<MA200; 3 higher highs/lows; RSI(4)>75→exit<45; RSI(2) rising 3d & >90→exit<30;
%B>0.8 ×3 → exit<0.2; up 4 of 5 → exit<MA(5); RSI(2)>90 then >94 → exit<MA(5)).
Reported shorts: 71.5%/+0.88%; 68.1%/+1.26%; 70.4%/+1.15%; 70.1%/+0.95%; 71.1%/+0.80%; 76.0%/+1.56%.

**Citation:** Connors, L. & Alvarez, C., *High Probability ETF Trading* (2009). Rules + Connors' backtest
figures ("inception of the ETF through 12/31/08") transcribed system-by-system by user *Kevin_in_GA*:
https://stockfetcher.com/forums/Filter-Exchange/HIGH-PROBABILITY-ETF-TRADING-BY-LARRY-CONNORS-GET-YOUR-FILTERS-HERE/93830
(msgs #93832, #93835–#93841, 14 Jun 2010). Book chapter/page numbers **NOT-EXTRACTED** (no legal full text).

**Known criticism / replication — this is the valuable part.** Same post carries an *independent* out-of-sample
replication (12/31/2006 → 14 Jun 2010, same 20 ETFs) **and it deliberately exits at the NEXT DAY'S OPEN
instead of the close** (author: "SF uses buy/sell on the open of the day *following* the signal"):

- 3-Day High/Low: 258 trades, 67.5% (↓9.4pp), +0.50% (↓)
- RSI(4): 321 trades, **78.5% (↑), +1.28% (↑)**
- R3: 177 trades, 75.1% (≈), **+1.34% (↑)**
- %B: 138 trades, 79.0%, +2.65% but hold blew out to **16.6 d**, and *"every trade since 4/16/2010 has been negative"*
- Multiple Days Down: 415 trades, 68.5% (↓), +0.49% (≈)
- RSI(2) 10/6: 153 trades, 73.9% (↓8pp), +0.79% (↓)
- Shorts degraded worst: RSI(2) 90/94 short fell **76.0% → 59.0%**, +1.56% → +0.84%

→ **Directly on-brief:** a next-open exit reproduced or beat the close-exit numbers on 3 of 6 long systems.
That is real evidence the Connors family tolerates close→next-open execution.

**Data needed:** daily OHLC + dividend-adjusted closes for the 20 ETFs from inception; MA(200), MA(5),
RSI(2), RSI(4), Bollinger %B(20,2). Plus a next-open series to test the B-variant. All within existing yfinance/IBKR reach.

**6 bp prior: HIGH (survives).** Gross edge 0.50–1.06%/trade → 6 bp is 6–12% of edge. Caveat: figures are
gross, single-ETF, pre-2009, and the ~5–20 signals/day clustering means portfolio-level exposure caps bind first.

---

## 2. Connors/Alvarez Cumulative RSI(2) — the version explicitly executed CLOSE-SIGNAL → NEXT OPEN  ★ best B fit
**Fit: B (signal at close, fill at next open, exit at a later next open).**

**Thesis:** Summing consecutive RSI(2) readings measures *duration-weighted* exhaustion, not a one-day spike;
it halves signal count and nearly doubles per-trade expectancy vs vanilla RSI(2).

**Connors' original book rules (quoted):**
1. Security is above its 200-day MA. 2. Use a 2-period RSI. 3. Sum the past X days of RSI(2).
4. Buy if the Cumulative RSI is below Y. 5. Exit when RSI(2) closes above 65.
Book's suggested parameters: **X = 2 days, Y = 10.**

**Reported magnitude (event study, US stocks, 1998 → 2024):**
- Cumulative RSI(2 days) < 10: **~280,000 events**, **expected return +1.0%**, **win rate 65%**, avg win +4.1%, avg loss −4.8% (payoff 0.84)
- Vanilla RSI(2) < 5 with close>SMA(5) exit: **~600,000 events**, +0.6%, **74% win**, avg win +2.5%, avg loss −4.9% (payoff 0.50)
- Significance: Cum-RSI vs non-events p = 9.2e-05; Cum-RSI vs vanilla p = 4.3e-73
- Portfolio backtest of the enhanced variant (prior article, since 1999): **30.3% annual, 35% max DD** vs benchmark 57% DD

**The exact executable spec (Quantitativo's, and it is close→next-open on BOTH legs):**
- Cum RSI(2,2) < 10 → **buy on the next opening**; Cum RSI(2,2) > 65 → **exit on the next opening**
- Only if price > 200-day SMA; if close < 200-day SMA while in a position → **exit at next open**
- Large & mega caps only (delisting-risk control); max **3 concurrent positions**
- If >3 setups, sort by market cap and **prioritize the LOWEST market cap**
- Liquidity: stock traded every session in the past 3 months; **trade capital ≤ 5% of 3-month median ADV**

**Citation:** https://www.quantitativo.com/p/squeezing-more-profits-with-cumulative (22 Jun 2024), quoting
Connors & Alvarez, *Short Term Trading Strategies That Work* (2008). Book page **NOT-EXTRACTED**.

**Known criticism (from the same author):** *"Since he published this idea in 2008, we saw that the vanilla
strategy lost most of its power."* The 30.3% figure is only reached after two non-book modifications —
small-cap tilt and multi-instrument parallelism. Treat 30.3% as the *modified* system, not Connors'.

**Data needed:** daily OHLC + **next-day open** for a large/mega-cap survivorship-free universe (Norgate-class or
CRSP), 200-day SMA, RSI(2), rolling 3-month median ADV, point-in-time market cap.

**6 bp prior: HIGH.** +1.0%/trade expectancy against 6 bp = 6% of edge. The ADV≤5% cap is exactly the
right realism guard. Main risk is the market-cap tilt: lower caps carry far more than 6 bp of true spread.

---

## 3. Larry Connors / Dave Landry **CVR3** VIX reversal — buy the close, exit within 2–4 days  ★ verified primary source
**Fit: B (buy on the close; short holding period). Signal is exogenous (VIX), so it is orthogonal to our RSI(2) book.**

**Thesis:** When the VIX stretches ≥10% from its own 10-day MA, fear/complacency is mechanically overextended
and the S&P reverses over 2–3 days.

**EXACT rules (verbatim from Connors' own workshop transcript):**
- **Buys:** (1) Today the **low of the VIX** is above its 10-day MA. (2) Today the VIX **closes ≥10% above** its
  10-day MA. (3) If 1 & 2 met → **buy the market on the close.** (4) **Exit on the close** the day VIX trades
  (intraday) below **yesterday's** 10-day MA — or exit within **2 to 4 days**.
- **Sells:** (1) VIX **high** below its 10-day MA. (2) VIX closes **≥10% below** the 10-day MA. (3) **Sell on the close.**
  (4) Exit on the close the day VIX trades above yesterday's 10-day MA, or within 2–4 days.
- StockCharts adds a third condition Connors' transcript omits: **close below the open** for buys / above the open
  for sells — cite that variant separately.
- Vehicle, stated: **S&P futures (E-minis) or SPDRs.** Frequency: ~1 signal / 2.5 weeks.

**Reported magnitude:** CVR3 "correctly predicted a two- to three-day reversal **better than 68%** of the time"
over the prior **nine years (≈1993–2002)**; the 10-CVR family ≈65%. Also: *"had you traded one contract for every
CVR signal since 1993, you would have earned approximately $1.8 million"* — with Connors' own all-caps disclaimer.

**Citation:** Connors, L., "Market Timing Using The VIX", TradingMarkets.com, 11 Jan 2002 — transcribed from a
live TraderTalk workshop: https://tradingmarkets.com/recent/market_timing_using_the_vix-665086
Rule restatement: https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/cvr3-vix-market-timing

**Known criticism:** "68% directional hit rate" is **not** a P&L statement — no avg gain, no drawdown, no
per-trade expectancy is published. The $1.8M is an unaudited aggregate across all 10 CVR signals with no
contract-count or margin basis. **Reported magnitude in return terms: NOT-EXTRACTED.** Also: the 1993–2002
sample predates VIX-complex financialisation (VIX futures 2004, VXX 2009), which plausibly changed the
mean-reversion speed of VIX itself.

**Data needed:** daily VIX OHLC (we have), SPY/ES daily OHLC, 10-day SMA *and* 10-day EMA of VIX (StockCharts'
PPO(1,10,1) variant uses EMA — test both).

**6 bp prior: HIGH.** ~20 trades/yr × 6 bp = 1.2%/yr drag; a 2–4 day index hold typically carries ≫6 bp of move.
Cheapest candidate here to falsify — we already hold all the data.

---

## 4. Connors/Alvarez **Double 7s** — with a modern, standardised replication
**Fit: B-adjacent (buy the close of a 7-day closing low; exit on close).**

**EXACT rules:** Universe **SPY only**, long/cash, max 1 position.
1. SPY closes **above its 200-day SMA** (entry filter only — it does NOT force an exit).
2. SPY **closes at a 7-day closing low** → **buy on the close.**
3. SPY **closes at a 7-day closing high** → **sell on the close.**
No RSI anywhere; no stops; not a 200-SMA timing model.

**Reported magnitude — independent standardised backtest (methodology BTS-3377, publ. 6 May 2026):**
- Full window **1994–2025 (32 y)**, $10,000 start, benchmark buy-&-hold SPY — headline full-period metrics paywalled
- **Free preview 2021–2025:** time in market **28.9%**, **19.2 trades/yr**, **win rate 77.1%**, vol 8.9% (SPY 17.1%),
  **max DD −12.9%** (SPY −24.5%), Sharpe 0.8 (SPY 0.9), Calmar 0.5 (SPY 0.6), **CAGR 7.0% (SPY 14.7%)**,
  ending capital $13,994 vs $19,791

**Citation:** https://www.backtestedstrategies.com/strategies/connors-double-7s-backtest/ ; source credited to
Connors & Alvarez, *Short Term Trading Strategies That Work*, and Alvarez's "Double 7's Strategy". Book page **NOT-EXTRACTED**.

**Known criticism — explicit and recent:** over 2021–2025 the strategy **lost to buy-and-hold on CAGR, ending
capital, Sharpe AND Calmar**; it only won on volatility and drawdown. That is a defensive-overlay profile, not
an alpha profile. The 77% win rate is intact while the money edge is gone — a textbook decayed mean-reversion signal.

**Data needed:** SPY daily adjusted OHLC 1993→ (have), 200-day SMA, 7-day rolling close min/max.

**6 bp prior: MEDIUM.** 19.2 trades/yr × 6 bp ≈ 1.15%/yr against a 7.0% CAGR = ~16% of the return. Survives
arithmetically but the post-cost residual no longer beats SPY.

---

## 5. Connors/Alvarez **TPS** (Time / Price / Scale-In)
**Fit: B-adjacent (scales in on closes, exits on close).**

**EXACT rules:** trade an S&P 500 ETF; require ETF **above its 200-day MA**;
- Open a **10%** long position when **RSI(2) < 25 for two consecutive days**
- Add **20%** if the close dips below the previous entry price
- Add **30%** if the close dips below the previous entry price
- Add **40%** if the close dips below the previous entry price (→ 100% deployed after 4 legs)
- **Exit when RSI(2) closes above 70** (exit the whole position)
- Mirror-image rules for the short side

**Citation:** rules per https://www.turingtrader.com/portfolios/connors-tps/ , attributed to Connors & Alvarez,
*High Probability ETF Trading* (2009). TuringTrader states its implementation *"slightly altered the entry and
exit points"* and **trades on the market OPEN rather than the close** — i.e. a documented close-signal→next-open
variant exists in production form.

**Reported magnitude: NOT-EXTRACTED.** TuringTrader's performance table renders empty for non-members
(CAGR/Sharpe/maxDD/Ulcer all blank). Their qualitative claims: equity curve "smooth in almost all market
regimes", **trails the S&P 500**, lower vol, **slightly negative beta**, "not trading often enough to use its
capital efficiently", tail risk "identical to holding the S&P 500 index", generates heavy wash sales, not
suitable for retirement accounts.

**Known criticism:** the scale-in is a **martingale on a mean-reverting signal** — position is largest exactly
when the thesis is most wrong. Tail risk is unhedged and TuringTrader says so explicitly.

**Data needed:** SPY daily OHLC, RSI(2), plus per-leg fill accounting and next-open series for the OPEN variant.

**6 bp prior: MEDIUM-HIGH** on cost alone (few, large trades), but **capital efficiency and left-tail are the
binding constraints, not cost.** Do not run without a hard portfolio-level stop that the book does not provide.

---

## 6. Toby Crabel — **Opening Range Breakout with the "Stretch"** (NR4 / NR7 setups)
**Fit: A (intraday, entry from the open).** The canonical ORB text.

**EXACT rules (definitions are Crabel's own):**
- **Noise[i] = min(High[i] − Open[i], Open[i] − Low[i])** — distance from the open to the nearest same-day extreme
- **Average_Noise = SMA(Noise, 10)**
- **Stretch[i] = Average_Noise[i] × 2**
- **Entry (ORB):** long **buy-stop at Open + Stretch**; short **sell-stop at Open − Stretch**, both placed at the
  09:30 open. **First stop touched is the position; the other stop becomes the protective stop.** If both fire
  same-day, count one entry/one exit and score it a loser (no reversals).
- **Setups that qualify a day:**
  - **NR7** — today's daily range is narrower than each of the previous 6 days' ranges individually
  - **2-bar NR (NR4 family)** — narrowest 2-day high-to-low range vs any 2-day range in the previous 20 market days
- **Exits tested:** time exit (Nth day at the close), Stretch exit (opposite stop at Open ∓ Stretch, levels fixed
  at entry day), target exit at a multiple of initial risk, and ATR stop = **6 × ATR(20)**
- Sizing in the test: $1,000,000 initial, **fixed-fractional 1%**

**Citation:** Crabel, T. (1990). *Day Trading With Short Term Price Patterns and Opening Range Breakout*,
Greenville: Traders Press. Crabel's Wyckoff rationale quoted at **p. 167**. Full specification tables:
https://oxfordstrat.com/trading-strategies/nr7/ and https://oxfordstrat.com/trading-strategies/toby-crabel-narrow-range-1/
(portfolio = 42 US futures markets, 1980-01-01 → 2016-01-31 / 2013-02-28, MATLAB).

**Reported magnitude: NOT-EXTRACTED.** Oxfordstrat publishes PF / Sharpe / UPI / CAGR / maxDD / %profitable /
win-loss ratio **only as 3-D and 2-D contour images**. Chart-only ⇒ excluded by rule.

**Known criticism — from Crabel himself, 2026:** *"The primary session open no longer carries the same
significance it once did. That moment used to concentrate liquidity and information. Today, that effect has
been diluted."* He also says the 1989/90 book's entry logic *"was more complicated than necessary"* and now
prefers **a simple percentage of an n-day average range**. His 100+ year multi-market baseline test shows
*"a gradual decline in both dollars per contract and Sharpe ratio over time."*
https://tobycrabel.substack.com/p/the-evolution-of-the-opening-range (20 Apr 2026). Result tables are images ⇒ **NOT-EXTRACTED**.

**Data needed:** intraday 1-min (or at least daily O/H/L/C + intraday touch sequence) for the equity ETFs/names;
10-day Noise average; ATR(20). **Crabel's stop-and-reverse construction requires intraday path, not OHLC alone** —
whether both stops fired, and in what order, is unrecoverable from daily bars.

**6 bp prior: MEDIUM for index ETFs, LOW for the futures-scale version.** The Stretch is 2× a 10-day
average noise; on SPY that is typically tens of bp, so 6 bp is a modest but real haircut. Entries are
**stop orders**, so real slippage exceeds 6 bp on gap-through fills — model that explicitly.

---

## 7. Crabel's own 2026 **simplified ORB, exit on the NEXT OPEN**
**Fit: A→B hybrid — enters intraday off the open, holds overnight, exits next open. Unusual and directly relevant.**

**EXACT rules (author's own current baseline):**
- Entry at **0.80 × the 10-day average range** away from the open (direction = whichever side triggers)
- **No stops, no profit targets**
- **Exit on the next day's open**
- Markets equally weighted; study spans **>100 years**, starting with a single market (wheat) and adding
  markets as data becomes available

**Citation:** Crabel, T., "The Evolution of the Opening Range Breakout", 20 Apr 2026,
https://tobycrabel.substack.com/p/the-evolution-of-the-opening-range

**Reported magnitude: NOT-EXTRACTED.** He lists exactly which columns the tables contain (contracts traded,
total profit, % return, dollars per contract, max drawdown, return-to-drawdown, Sharpe, Sortino, std dev,
trades/year, number of markets) but the tables are **posted as images**. The only text-stated result is
directional: **declining $/contract and declining Sharpe over time.**

**Other author-stated modifiers worth testing as filters:** reference points other than the open (regional
closes; any fixed-magnitude move from any level); **time-of-day** ("a multi-billion-dollar firm used the open
to 11:00 EST as a primary directional signal… held over multiple days" — behaviour since changed);
**day-of-week** ("a gap lower on a Monday can be a dangerous place to initiate short positions… momentum later
in the week can be quite powerful when markets are active").

**Data needed:** daily open + 10-day average range + **next-day open**. Cheapest possible test in this whole
report — pure daily data, no intraday required.

**6 bp prior: MEDIUM.** Single round trip per signal, no stop churn. But it inherits the unconditional
overnight-hold problem (see #9): the close-to-open drift is ~4 bp, so the *directional* ORB edge must carry
the whole cost by itself.

---

## 8. Zarattini–Aziz–Barbon — **SPY intraday momentum with noise boundaries + VWAP trailing stop**
**Fit: A (pure same-day; all positions closed at the bell).** Highest reported Sharpe among the A candidates.

**EXACT rules:**
- Every minute, compute **noise boundaries** = daily opening SPY price × (1 ± average daily return up to that
  same minute over the **last 14 trading days**); **adjust the upper bound UP by any prior overnight gap-down,
  and the lower bound DOWN by any prior overnight gap-up**. Inside the band ⇒ supply/demand balanced, no trade.
- **Entry:** only at a clock **HH:00 or HH:30**, if SPY has moved above the upper (below the lower) boundary →
  open long (short).
- **Sizing, two variants:** (i) 100% of funds per trade; or (ii) size to a **2% daily volatility target** using
  realised SPY vol over the past 14 days, **allowing up to 4× leverage** when realised vol < 2%.
- **Trailing stop, two variants, executed at the next HH:00/HH:30:** (i) opposite boundary, **and flip to the
  opposite trade** when it triggers; or (ii) **max(upper boundary, intraday VWAP)** for longs and
  **min(lower boundary, intraday VWAP)** for shorts.
- **Terminate all positions at the market close** — no overnight exposure.

**Reported magnitude:** **total return 1,985% net of costs**, **annualised 19.6%**, **Sharpe 1.33**,
sample **May 2007 – April 2024**, 1-minute SPY + VIX data.
Assumed frictions: **$0.0035/share commission + $0.001/share slippage.**

**Citations:** Zarattini, C., Aziz, A. & Barbon, A. (2024), "Beat the Market: An Effective Intraday Momentum
Strategy for S&P500 ETF (SPY)", SSRN 4824172 · results: https://concretumgroup.com/beat-the-market-an-effective-intraday-momentum-strategy-for-sp500-etf-spy/
· rule reconstruction: https://www.cxoadvisory.com/momentum-investing/complex-intraday-time-series-momentum-strategy-applied-to-spy/

**Known criticism:** (a) **the assumed cost is ~0.1–0.35 bp per side, i.e. 20–60× cheaper than our 6 bp
yardstick** — the headline is not comparable to our cost regime; (b) it is an *iteratively constructed*
strategy (four rule variants explored) on one instrument, so multiple-comparison risk is real;
(c) the volatility-target variant's 4× leverage does the heavy lifting; (d) CXO's own framing is
"**Complex** Intraday Time Series Momentum" — the boundary construction has ≥3 tuned choices
(14-day lookback, gap adjustment, HH:00/HH:30 grid).

**Data needed:** 1-minute SPY OHLCV **and** 1-minute VIX, ≥2007; 14-day trailing intraday return profile
*by minute-of-day*; intraday running VWAP. This is the most data-hungry candidate here.

**6 bp prior: LOW.** With entries/stops/flips on a 30-minute grid, realistic trade counts are ~1–3 round
trips/day. At 6 bp round trip that is ~15–45 bp/day of cost against a 19.6%/yr (≈8 bp/day) gross return.
**Do not port this without first re-deriving per-trade expectancy at 6 bp** — the published edge very likely
inverts. Test it as a *signal*, not as a P&L claim.

---

## 9. **Unconditional close-to-open ("Overnight Return Anomaly")** — the honest baseline every B strategy must beat
**Fit: B, and it is the null hypothesis for the whole B category.**

**EXACT rule (verbatim from the paper):** *"Buy at the Close of the current daily session. Hold position
overnight. Sell at the Open of the next day's session."* Operationalised time-targets: **open the position in
the last 5 minutes before the closing bell (15:55–16:00 ET); close it in the first 5 minutes after the opening
bell (09:30–09:35 ET)** (the paper elsewhere widens the exit window to 09:30–10:00).

**Reported magnitude (SPY, 02-Feb-1993 → 15-Jun-2011, 4,624 trades, $100,000 per trade):**

| | Annual return | Annual σ | Sharpe | Total return | Winners / Losers | Profit gross | **Net @ $0.01/share** |
|---|---|---|---|---|---|---|---|
| **Overnight (close→open)** | **9.23%** | 10.46% | **0.89** | 171.29% | 2,480 / 2,112 (**54.0% win**) | $171,289 | **$73,539** |
| Daytime (open→close) | −4.33% | 17.05% | −0.25 | −39.36% | 2,234 / 2,371 | −$39,360 | −$137,110 |

Same test on UGAZ (3× ETN, 1/1/2010–30/6/2016, 3,820 trades): overnight 8.61% / σ 11.92% / Sharpe 0.93 /
+130.42% gross → **$49,666 net**; daytime −4.90% / Sharpe −0.30.

**★ The cost sentence that matters most in this whole report**, verbatim:
*"Please note that in case of a commission cost of $0.02 per share, the total net profit of both overnight and
daytime return strategies would be less than zero."*

**Citation:** Basdekidou, V. (2017). "The Overnight Return Temporal Market Anomaly." *International Journal of
Economics and Finance* 9(3), 1–10. DOI 10.5539/ijef.v9n3p1. Open access; full PDF read directly (rule on p.1,
Tables 1–4 on pp. 6–7): https://ccsenet.org/journal/index.php/ijef/article/download/65109/35744
Corroborating scale: SPY average close→open gain **+0.04%** since 1993; open→close cumulative ≈ zero over
1993→present — https://www.quantifiedstrategies.com/overnight-trading/

**Known criticism / failed replication:** this is the candidate that **fails our own cost test on the author's
own numbers.** $0.01/share on ~$100 SPY ≈ 1 bp/side = **2 bp round trip**, and that already destroyed **57%** of
gross profit. $0.02/share ≈ 4 bp round trip ⇒ **negative**. Our yardstick is **6 bp**. Therefore:
**unconditional close-to-open in SPY does NOT survive 6 bp.** Corroborated independently by the +0.04% (=4 bp)
average overnight gain. Additional weakness: the paper's own conclusion leans on Lou/Polk/Skouras rather than
its own tests, and the Sharpe figures exclude the risk-free rate by construction (stated in the text).

**Data needed:** SPY daily open & close 1993→ (have). Optionally 15:55/16:00 and 09:30/09:35 prints for
auction-fill realism.

**6 bp prior: FAILS — do not trade unconditionally.** Its real value: it fixes the bar. **Any close-to-open
candidate must show >6 bp of *conditional* edge over and above this ~4 bp unconditional drift**, otherwise it
is just harvesting a drift that costs more than it pays.

---

## 10. Zarattini & Aziz — **5-minute Opening Range Breakout on QQQ / TQQQ**
**Fit: A (same-day; liquidate at the close).**

**EXACT rules:**
- If QQQ **rises (falls) during the first 5-minute interval** (09:30–09:35), **buy (sell) at the start of the
  second 5-minute interval (09:35)**. **No position if the first 5-min open and close are equal** (doji).
- **Stop-loss** = the **low (high) of the first 5-minute bar** for long (short).
- **Profit target = 10 × |entry − stop|.**
- If neither triggers, **liquidate at the market close (16:00)**.
- Sizing: **each trade sized so a stop-loss costs exactly 1% of current capital**; $25,000 start;
  max **4× leverage**; commission **$0.0005/share**; **no bid-ask spread, no slippage, no other execution uncertainty.**
- **Optimised variant:** stop = **5% of the 14-day ATR**, **no profit target**, hold to EoD; run on **TQQQ** to
  escape broker leverage caps.

**Reported magnitude (1 Jan 2016 – 17 Feb 2023):**
- QQQ version: **annualised alpha 33%** net of commissions
- **TQQQ version: +1,484% total** vs QQQ buy-and-hold **+169%**
- Optimised TQQQ (5%-of-ATR stop, EoD exit): **+9,350% P&L**, **annualised alpha 93%**, $25,000 → **$6,400,000**;
  **average P&L per trade = 0.18R** (≈$45 on a $250 risk unit) with a **low win rate**

**Citations:** Zarattini, C. & Aziz, A. (Apr 2023), "Can Day Trading Really Be Profitable? …", SSRN 4416622 ·
rules: https://www.cxoadvisory.com/technical-trading/day-trading-with-an-opening-range-breakout-strategy/ ·
numbers + paper quotes: https://retailtradersrepository.substack.com/p/trading-research-paper-can-day-trading-really-be-profitable

**Known criticism — much of it from the paper itself:**
- The authors: *"we deliberately kept the model very simple and did not try to optimize the parameters"* — then
  the headline 9,350% comes **from optimizing** (a 1R–10R × stop-width grid). The 93% alpha is an in-sample grid maximum.
- Explicitly conceded: *"this result can, under certain circumstances, be considered unrealistic because the
  model doesn't factor in slippage."* CXO likewise records **no bid-ask spread, no slippage**.
- The optimal stop is **absurdly tight**: *"the 14-day ATR of TQQQ as of February 2023 is around $1.60, while
  TQQQ is trading at around $25… A stop placed at 5% of the 14-day ATR implies a stop width of $0.08."*
  On a $25 share that is **32 bp**. Risking 1% of capital on a 32 bp stop ⇒ **notional ≈ 3× capital** ⇒ 6 bp on
  notional ≈ **18 bp of capital per round trip**, versus an average trade of 0.18R = 18 bp of capital.
  **The entire average edge is consumed by cost at 6 bp.** The reviewer independently flags this:
  *"With a large account and a large share exposure, the stop will likely be exceeded."*
- Doji rule is under-specified: open == close to the cent almost never happens, so the no-trade filter is inert.

**Data needed:** 1-minute (or 5-minute) QQQ **and** TQQQ OHLCV from 2016; ATR(14); exact 09:35 and 16:00 prints;
intraday touch sequence for stop/target ordering.

**6 bp prior: VERY LOW for the optimised variant (arithmetically ~breakeven-to-negative, shown above);
LOW-MEDIUM for the plain variant** where the stop is the 5-min bar low (typically 30–60 bp wide → notional
≈1.5–3× capital). Keep the *structure*, discard the headline returns.

---

## 11. Zarattini, Barbon & Aziz — **ORB restricted to "Stocks in Play"**
**Fit: A (same-day), and the most credible A candidate because the cost objection was pre-empted.**

**EXACT rules:** Same 5-minute ORB mechanics as #10, but the universe is filtered each day to **"Stocks in
Play"** — stocks showing **higher-than-normal trading activity that day**, mostly driven by **company
fundamental news / earnings**. Portfolio = **top 20 Stocks in Play**. Also tested with **15-, 30- and
60-minute** opening ranges.

**Reported magnitude (>7,000 US stocks, 2016–2023):** **total NET performance >1,600%**, **Sharpe 2.81**,
**annualised alpha 36%**, versus S&P 500 **+198%** over the same period. The abstract states the benefit of
restricting to Stocks in Play holds **"even after considering transaction costs."**

**Citation:** Zarattini, C., Barbon, A. & Aziz, A. (2024). "A Profitable Day Trading Strategy For The U.S.
Equity Market." Swiss Finance Institute Research Paper 24-98. Abstract read in full at
https://ideas.repec.org/p/chf/rpseri/rp2498.html · summary: https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/

**Known criticism:** (a) **"Stocks in Play" is not quantitatively defined in any free text I could reach** —
the RVOL threshold, the news-detection rule and the ranking metric are all **NOT-EXTRACTED**, and that single
undefined filter is the entire claimed contribution; (b) it is a **top-20-per-day cross-sectional** strategy, so
Sharpe 2.81 partly reflects 20-name diversification, not per-trade quality; (c) high-RVOL news names are
precisely where spreads and slippage are widest — the "even after transaction costs" claim needs the actual
cost model, which is not in the abstract; (d) survivorship/point-in-time construction of the 7,000-stock
universe is unstated.

**Data needed:** 1-min OHLCV for a **point-in-time, survivorship-free** US universe from 2016 (this is the
expensive part), a daily RVOL measure, a news/earnings timestamp feed, and per-name spread history.

**6 bp prior: MEDIUM.** The economics are far better than #10 because a 20-name spread of full-session
momentum trades has larger per-trade moves. But 6 bp is optimistic for high-RVOL small/mid caps —
**model per-name spreads, not a flat 6 bp**, or this will look profitable and trade unprofitably.

---

## 12. Raschke & Connors — **"80-20's"** (*Street Smarts*)
**Fit: A (intraday reversal, entry after the open).**

**EXACT rules (long side):**
1. **Yesterday** the market **opened in the upper 20%** of its daily range and **closed in the lower 20%** of
   that range (an "80-20 bar"). Additional condition: **yesterday's range must be larger than the average
   daily range** (lookback unspecified by the author; the reference implementation uses **20 days**).
2. **Wait until today's LOW breaks yesterday's low by at least 5 ticks.**
3. Place a **buy limit/pending order at the lower border of yesterday's range** (i.e. yesterday's low).
4. On fill, set initial **stop-loss at today's low**.
5. **Trail the stop** to protect profit. (No fixed target in the original — the reference implementation adds an
   optional TP = breakout distance × a ratio.)
Short side mirrors: yesterday's bar bullish (opened lower 20%, closed upper 20%), entry at yesterday's high,
stop at today's high.
**Explicitly intraday-only; the book's examples use 15-minute charts** (reference implementation illustrates on M1/M5).

**Citation:** Raschke, L. & Connors, L., *Street Smarts: High Probability Short-Term Trading Strategies* (1996) —
rules reproduced with book attribution and Taylor/Moore/Gipson lineage at https://www.mql5.com/en/articles/2785
(22 Dec 2016). Book page **NOT-EXTRACTED**.

**Reported magnitude: NOT-EXTRACTED.** No win rate, expectancy or sample from the book is quoted. The
implementing author's stated purpose is itself a warning: *"to develop tools allowing us to check if the strategy
is still viable today, since Raschke and Connors used the market behavior at the end of the last century."*

**Known criticism:** two rule parameters are **left undefined by the authors** — the average-range lookback and
the trailing-stop mechanism — so any backtest is the tester's strategy, not Raschke's. The 5-tick trigger is a
futures-tick convention that needs re-expression in bp for equities.

**Data needed:** daily OHLC (for the 80-20 bar) **plus intraday 1–15 min bars** to detect the 5-tick low
breach and the pending-order fill, and to trail the stop.

**6 bp prior: MEDIUM.** It is a limit-order entry (spread-favourable, but with adverse-selection/no-fill bias
that a naive backtest will over-credit) and a single intraday round trip. Cost is not the main risk here —
**unspecified parameters and fill assumptions are.**

---

## 13. **Turn-of-the-month (−1, +3)** overnight/short-hold seasonal
**Fit: B (buy the close, hold across the month boundary).**

**EXACT rules:** **Buy SPY at the close of the last trading day of the month** (some formulations: 1 day before
month-end, some 4 days) and **sell at the close of the 3rd trading day of the new month.** The
turn-of-the-month window is defined as **the last trading day of the month through the third trading day of the
following month**. Long-only, index/ETF, in cash otherwise.

**Reported magnitude:** source-paper backtest **1926–2005**; **indicative performance 7.2% p.a.**, derived from an
**annualised daily return of 0.15% (arithmetic) from Table 3, Panel A1 for the (−1,+3) strategy**, return excluding
cash earned on days out of the market; **estimated volatility 6.9%** (inferred from the t-statistic in Table 3).
Historical anchor: Lakonishok & Smidt (1988) found **the four days at the turn of the month accounted for ALL of
the positive returns to the DJIA over 1897–1986**; the same pattern recurs in the modern sample, and
*"virtually all of the excess market return is accrued during the four-day turn-of-the-month period, and
investors received little or no reward for bearing the market risk over the other 16 trading days of the month."*
Effect documented in **30 different markets**. Carcano & Tornero: in S&P 500 futures it is *"the only calendar
effect that is statistically and economically significant and persistent over time."*

**Citation:** https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes ; underlying papers
McConnell & Xu, "Equity Returns at the Turn of the Month" (SSRN 917884); Lakonishok & Smidt (1988);
Carcano & Tornero, "Calendar Anomalies in Stock Index Futures" (SSRN 1958587).

**Known criticism:** stated by the source itself — *"caution is needed if one implements this strategy as
calendar effects tend to vanish or rotate to different days in a month."* Ogden's payday explanation was
**tested and rejected**; risk-based explanation **rejected** (σ is not higher in the window); McConnell & Xu
call it *"a puzzle in search of an answer"* — i.e. **no mechanism**, which is the weakest possible prior for
out-of-sample persistence. Also note the (−1,+3) window is a *parameter*: the literature variously uses
−1, −4, +3, so window choice is a live degree of freedom.

**Data needed:** SPY/ES daily closes + an exchange trading calendar to index trading days from month
boundaries (both already available). Trivial to test — highest testability-per-hour in this report.

**6 bp prior: MEDIUM-HIGH.** 12 round trips/yr × 6 bp = **0.72%/yr** against a claimed ~7.2%/yr → ~10% of
edge. Cost is genuinely not the problem; **decay and window-selection are.** Test 1926–2005 vs 2006–2026
separately before believing anything.

---

## 14. Connors' classic **RSI(2) + 200-day SMA** (baseline restatement — for parameter-robustness only)
**Fit: B-adjacent. Included because it is what we already run; use it as the control, not a new candidate.**

**EXACT rules:** Long only when close > **SMA(200)**. **Buy at the close when RSI(2) closes below 5 (or 10).**
Exit when **RSI(2) > 65–75**, or when **close > SMA(5)**. Short mirror: close < SMA(200), RSI(2) > 95, exit
below SMA(5) or RSI(2) < 25–30. Connors' research reportedly found **fixed stop-losses reduced performance**.
Screener thresholds: ADV > 500,000 shares, price > $5.

**Reported magnitude (third-party backtests, SPY 1993→):**
- RSI(2)<10 → exit RSI(2)>80, no trend filter: avg **+0.9%/trade**, **CAGR 9%**, **max DD 34%**, invested 28% of the time
- Same with the 200-day filter: avg **+0.95%/trade**, max DD **31%**, **CAGR 6.8%**, invested 18% of the time
- Exit changed to "close above yesterday's high", no trend filter: avg **+0.5%/trade**, max DD **15%**, **win rate 76%**
- Cross-study typical range: win rate 70–80%, avg win 0.5%, CAGR 8–12%, max DD 20–30%

**Citation:** https://www.quantifiedstrategies.com/rsi-2-strategy/ (attributes rules to Connors, *Street Smarts*
1996 and *Short Term Trading Strategies That Work* 2008). ⚠ Retrieved with a `403 Forbidden` warning in the
reader's header — treat as **secondary, provenance-caveated**. Book pages **NOT-EXTRACTED**.

**Cesar Alvarez's own published variant (co-author, primary source, and it exits at the NEXT OPEN):**
Setup: Russell 3000 member; price > $1; 21-day MA of close×volume > $500K; close > **MA(100)**; **RSI(2) < 10**.
**Entry: limit order for the next day at 5% BELOW the close, good for one day only** (deliberate intraday-weakness
fill); cap orders at 10 concurrent positions; if multiple setups, **rank by 100-day historical volatility, high to low**.
**Exit: RSI(2) > 50 OR after 10 trading days — exit on the NEXT OPEN.** No stops, no market-timing rule.
Test range 1/1/2007–6/30/2018. Alvarez's own verdict on the base version: *"These numbers are really
disappointing… the returns in 2016 and 2017 are bad."* His fix was a universe change (trade **ex-Russell-3000**
stocks), yielding CAR +121%, MDD −54%, Sharpe +172% — figures are **relative deltas only; absolute levels are
image-only ⇒ NOT-EXTRACTED**. Source: https://alvarezquanttrading.com/blog/rsi2-strategy-double-returns-with-a-simple-rule-change/
Alvarez also states his production mean-reversion strategies *"typically enter at the next day's open or wait
for a further"* decline — i.e. **the co-author does not trade the book's close entry**.

**Known criticism:** the same page that promotes it lists the decay honestly — *"Out-of-sample validation from
2015-2025 shows slight performance decay from increased HFT competition"*; win rates *"drop below 60%"* in 2008
and March 2020; unfiltered RSI(2) *"produced 15% losses on clustered sell signal failures"* in the 2022 bear
market. Signal clustering during stress is the structural flaw: 10+ correlated positions open simultaneously.

**Data needed:** already in the lake.

**6 bp prior: HIGH.** But note the exposure: 18–28% time-in-market for a 6.8–9% CAGR means the *per-trade*
edge is what pays, and at +0.5–0.95%/trade, 6 bp is 6–12%. The **ex-index / low-cap variants are where 6 bp
becomes a lie** — those names carry far wider spreads.

---

# CROSS-CUTTING: execution mechanics for every close-to-open candidate
*(University course material — the only genuinely academic source I could fully read.)*

Source: **Hasbrouck, J. (2024). *Securities Trading: Principles and Procedures*, draft STPPms14b, 2024-08-20.
NYU Stern, free full PDF (200 pp.): https://pages.stern.nyu.edu/~jh4/STPP/drafts/STPPms14b.pdf
Part II, Chapter 6 "Auctions", §11, pp. 52–57.** Downloaded and read directly.

Why every B candidate needs this:
- **Closing-auction interest is structurally huge and non-discretionary** (p. 53): mutual-fund NAV
  creations/redemptions price off the close; index funds must match index composition at the close; cash-settled
  index derivatives settle at closing index prices; **leveraged and inverse ETFs must deliver a multiple of the
  close-to-close return**. A "buy at the close" strategy is trading *into* that flow.
- **Order-type reality:** the auction is a **single-price double auction (SPDA)**; venues accept unpriced
  **market-on-open (MOO)** and **market-on-close (MOC)** orders (p. 53). Our close entries should be modelled as
  MOC, and next-open exits as MOO — not as "the printed close/open with zero cost".
- **Hard deadlines that constrain automation** (p. 57): in the NASDAQ opening cross the open is timed for 9:30;
  **on-open orders must be received before 9:28 and MAY NOT BE CANCELLED**; from 9:28 NASDAQ transmits **matched
  volume and imbalance** information; between 9:28 and 9:30 only **imbalance-only** orders (which may only reduce
  an existing imbalance) are accepted. **Similar procedures apply to the closing auction.**
  ⇒ Any close-to-open bot must commit its MOO by **9:28:00** with no cancel option. That is a real operational risk.
- **Clearing price = the price that maximises matched volume**; the unmatched remainder is the **signed
  imbalance** (pp. 53–54, worked numerical example).
- **"Marking the close" / "banging the close"** (§6.4, p. 57): closing prices anchor NAVs, derivative settlement,
  takeover pricing and **margin calls**, so there is a documented incentive to distort them in less-active
  names. Confines close-entry strategies to high-ADV instruments.

**Derived untested signal (offered, not claimed):** the 9:28–9:30 published **matched volume + imbalance** is a
free, exchange-disseminated, forward-looking measure of opening pressure — a natural conditioner to turn the
failing unconditional close-to-open trade (#9) into a conditional one. **Magnitude: NOT-EXTRACTED — no
published performance located. Data needed: NASDAQ/NYSE auction imbalance feed (not currently in the lake).**

---

# What I could NOT verify (declared, not papered over)

| Item | Status |
|---|---|
| Any book **page number** for Connors/Alvarez rules or stats | **NOT-EXTRACTED.** archive.org full-text search returned `numFound: 0` for all four target books. Legal full text unavailable; pirated copies (pdfcoffee, scribd, coursehero, z-library, epdf) were found and **not used**. |
| Oxfordstrat Crabel NR4/NR7 performance (PF, Sharpe, CAGR, maxDD, win%) | **NOT-EXTRACTED — chart-only** (3-D/2-D contour images). |
| Crabel's own 100-year ORB baseline results | **NOT-EXTRACTED — image tables.** Only the directional statement (declining $/contract and Sharpe) is text. |
| TuringTrader TPS performance table | **NOT-EXTRACTED — renders empty for non-members.** |
| Connors Double 7s full-period 1994–2025 metrics | **PAYWALLED.** Only the 2021–2025 free preview extracted. |
| CVR3 in return/expectancy terms | **NOT-EXTRACTED.** Only a 68% directional hit rate and an unaudited $1.8M aggregate. |
| "Stocks in Play" quantitative definition | **NOT-EXTRACTED** from free text — and it is the paper's core contribution. |
| Zarattini SPY intraday-momentum full paper | Alexandria/UniSG PDF download returned a 2 KB stub; SSRN blocked by Cloudflare. Rules/results taken from CXO + Concretum. |
| Scott Andrews gap-fade probabilities (Gap Zone Map, gap fades by day of week) | **NOT-EXTRACTED.** Only qualitative descriptions on a free blog ("Wednesday and Thursday have the best historical odds"); the numeric tables live on a subscription site and in pirated PDFs. **No gap-fade candidate is included** rather than cite unverifiable numbers. |
| Podcast / conference-talk transcripts with timestamps | **FAILED.** `r.jina.ai` returns 401 on YouTube without a `JINA_API_KEY`; no transcript helper found in `research/`. The only talk-derived source obtained is Connors' 2002 TraderTalk workshop transcript (candidate #3), which is text, not video. |

# Bottom line for the owner

1. **The single most decision-relevant finding is negative:** unconditional close-to-open in SPY **dies at
   4 bp**, on the source paper's own numbers (#9). Any B strategy must be *conditional* and must show
   >6 bp of edge **over** the ~4 bp drift. This kills "just buy the close and sell the open" outright.
2. **The best B evidence we did find is Connors-adjacent and already half-validated for next-open execution:**
   the independent 2007–2010 replication of all six *High Probability ETF Trading* systems **exited at the next
   open** and matched or beat Connors' close-exit stats on RSI(4), R3 and %B (#1). Cheapest high-value next step.
3. **Cheapest tests, in order:** #13 turn-of-month (daily closes only) → #7 Crabel simplified ORB (daily open +
   10-day range + next open) → #3 CVR3 (VIX daily, all data on hand) → #1 the six ETF systems.
4. **Treat the ORB papers (#8, #10, #11) as signal libraries, not P&L claims.** Their cost assumptions are
   20–60× below our 6 bp yardstick, and for the optimised TQQQ variant the 6 bp cost arithmetically consumes
   the entire 0.18R average trade.
5. **Every published author here who is still trading says the same thing** — Crabel ("gradual decline in
   dollars per contract and Sharpe"; the open "has been diluted"), Alvarez ("these numbers are really
   disappointing… 2016 and 2017 are bad"), Quantitativo on Connors ("lost most of its power"),
   BacktestedStrategies on Double 7s (loses to buy-and-hold 2021–2025). **Assume decay is the base case.**
