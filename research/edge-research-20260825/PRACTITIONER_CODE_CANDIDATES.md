# Practitioner-Code Mining: Intraday & Close-to-Open US Equity Strategies
**Researcher:** practitioner-code / community-archive domain
**Date:** 2026-08-25
**Sources actually fetched:** QuantConnect research + strategy library (incl. Wayback for JS-rendered tutorial text), r/algotrading (via redlib mirrors `safereddit.com` / `redlib.catsarch.com` — reddit.com and old.reddit.com both 403 `r.jina.ai`), Quantitativo (Substack), Concretum Group, AlvarezQuantTrading, QuantifiedStrategies, GitHub raw + REST API.

**Ranking key:** (Robinhood-feasibility × testability-on-our-daily-bars × edge size). Ranks 1–5 are the ones worth backtesting first; 6–9 are conditional; 10–14 are documented-but-blocked on our stack.

---

## HOW TO READ THE FEASIBILITY COLUMN

Our binding constraints: Robinhood, ~$700 equity, whole shares, ~$105/position → **share price must be < ~$50**; **no MOC/MOO**; no stops outside 09:30–16:00 ET; measured round-trip cost **5.9 bp regular hours / 50.7 bp pre-market / 71.3 bp evening**; long-only; equity **daily** bars for 20y (intraday equity minute bars ≈ absent).

Consequence used throughout: *anything whose legs are both inside 09:30–16:00 is cheap; anything requiring MOC/MOO, minute bars, shorts, or an SPY-priced instrument is degraded or dead.*

---

# TIER 1 — TEST THESE FIRST

## 1. Quantitativo "Mind the Gap" — gap-down long, open → next open
**Thesis:** Stocks in an uptrend that open with a large gap down revert; harvest the reversion by buying the gap-down open and selling the next open.

**EXACT rules** (as published):
- Universe: US stocks; **open price above the 200-day SMA** ("bullish stocks"). Liquidity screen not stated → UNVERIFIED.
- Entry: **at the open (09:30)** of any qualifying stock that opened with a **gap down vs. previous close wider than a threshold**. *The author explicitly refuses to publish the threshold* ("this study seems so promising to me that I will share the overall gist but refrain from quoting specific parameters") → threshold must be re-derived by us.
- Position cap: **max 10 names**; if more than 10 qualify, **rank by volatility and take the LEAST volatile**.
- Exit: **hold until the NEXT open, sell at the open**, repeat. Holding period = 1 trading day + 1 overnight.
- Execution note from author: use **limit orders, not market orders, to avoid the opening auction**; there is a "sweet spot" delay after 09:30 (place too early → fill everything but on worse stocks; too late → miss fills); split orders for size.

**Reported results** (2010–2024, 15y, net of **10 bp round-trip**): annual return **22.9%** vs S&P 500 **11.8%**; positive in **13 of 15 years**; max DD **19.7%**; **Sharpe 1.66** vs 0.73 benchmark; ~**10 trades/day**; win rate **55.6%**; expected return/trade **+0.11%**; payoff ratio **0.96**.
Source: https://www.quantitativo.com/p/mind-the-gap — blog with own backtest (not a repo; no code published). 8 bp and 12 bp cost variants exist but their stat panels are **images → NOT-EXTRACTED**.

**Decay / failure evidence:** Author states pre-2010 results were *significantly better* and deliberately excluded — i.e. the edge has decayed over time. He also says the whole thing lives or dies on getting round-trip slippage **under 10 bp**, and that his slippage evidence at publication was **IBKR paper trading**, not live. Related community evidence (below, item 8) shows the naive gap-fill version is unprofitable, so the 200-SMA + least-volatile + threshold filters are doing the work.

**Data needed:** daily OHLC (prev close, open) + 200-day SMA + a volatility rank + survivorship-free universe. **We have all of this in the 20y IBKR daily set.** No minute bars needed to backtest.

**Robinhood-feasible long-only at ~$105, both legs regular hours?** **YES — best fit in this report.** Long-only by construction; both legs are at/just after the 09:30 open (limit orders, which is the only thing RH does well); no MOC/MOO needed; no stops needed. Two real frictions: (a) our cost is 5.9 bp round trip vs the author's 10 bp assumption → *we are cheaper than his base case*; (b) 10 concurrent names × $105 = $1,050 > our $700 → we run 6–7 names, and the "gap down > threshold + price < $50" intersection needs checking.

---

## 2. Alvarez "Broken Arrow" — buy the -15% close, exit next open
**Thesis:** After a violent single-day collapse in an otherwise healthy uptrend, the *worst* time to sell is that close; the next open is systematically better — which is a tradeable close-to-open long.

**EXACT rules:**
- Setup: stock in S&P 500 (also tested on **top-1000 by dollar volume**); Close > 40-day MA of closes; today's 40-day MA > yesterday's 40-day MA (rising).
- Trigger: **yesterday was a setup AND today closes down ≥15%** (he also tested −20% and −25%; those gave only 34 and 8 trades).
- Entry: **at that day's close** (≈15:55 in practice).
- Exits tested: (1) **next day's open**; (2) next open after RSI(2) closes > 70; (3) five days later on the open.
- Test window: from 2009.

**Reported results (TEXT table, extracted):**
| Exit | Universe | # trades | Avg P/L % | % winners |
|---|---|---|---|---|
| Next day open | Top 1000 | 412 | **+0.77%** | 56% |
| RSI(2)>70 | Top 1000 | 412 | +1.29% | 53% |
| Five days | Top 1000 | 412 | +1.36% | 49% |
| Next day open | S&P 500 | 121 | **+0.66%** | 60% |
| RSI(2)>70 | S&P 500 | 121 | +4.27% | 57% |
| Five days | S&P 500 | 121 | +2.66% | 52% |

Source: https://alvarezquanttrading.com/blog/dealing-with-broken-arrows/ (AmiBroker + Norgate survivorship-free data; blog-reported, no code).
**Data-integrity caveat I must flag:** the prose says the top-1000 −15% screen gave **318** trades but the table says **412**; and the S&P-500 −15% screen is quoted as **121** in both. Treat trade counts as approximate.

**Decay evidence:** none published for this specific study (2013 post, sample starts 2009 — a bull regime the author himself flags as a limitation: *"I do not like testing too far back because markets change"*). The broader risk is obvious: a −15% day is usually earnings/news, and the overnight distribution is fat-tailed.

**Data needed:** daily OHLC + 40-day MA + dollar-volume ranking. **Fully covered by our 20y daily set.**

**Robinhood-feasible?** **YES, with one execution caveat.** Long-only; entry leg is a limit order in the last minutes of regular hours (no MOC needed — we place a limit at/near the last print) and exit is a limit at the open. Both legs inside 09:30–16:00 → 5.9 bp. Edge (+66 to +77 bp/trade) is ~11–13× our round-trip cost, the widest margin in this report. Caveats: (a) a stock that just fell 15% has a *wide* spread, so our measured 5.9 bp (from normal L2 books) is optimistic for this specific event — must re-measure on gap/crash names; (b) event frequency is low (≈40/yr across top-1000), so this is a supplementary lane not a daily engine; (c) whole-share at $105 restricts us to sub-$50 post-crash names, which biases toward small caps where the spread penalty is worst.

---

## 3. QuantifiedStrategies gap-down + IBS + RSI overnight (S&P 500 / SPY)
**Thesis:** A gap-down open on an already-oversold day carries an extra risk premium; buy the open, and exit intraday only if the gap fills, otherwise hold overnight.

**EXACT rules (published in full, text):**
1. The S&P 500 must **gap down at least 0.15%** (prev close → today's open).
2. **Yesterday's IBS ≤ 0.25** (IBS = (Close−Low)/(High−Low)).
3. **Yesterday's 5-day RSI ≤ 0.45** — as printed; almost certainly means **45** on the 0–100 scale. FLAG: ambiguous in source.
4. If 1–3 true → **buy today's open**.
5. **Exit at the close if the close is higher than yesterday's close**; otherwise **hold overnight** (and repeat the test).

**Reported results:** average gain per trade **0.48** (units printed without a % sign; context implies 0.48%) and **profit factor 1.8**; "on a longer time frame using SPY, the average per trade is still around 0.5% with a rising equity curve."
Source: https://www.quantifiedstrategies.com/gap-trading-strategies/ — vendor blog, own backtest, **code sold separately (AmiBroker)** → results are claimed-in-article, not verifiable-in-repo.

**Decay evidence (same page, valuable):** their *naive* gap-fill day-trading version on 5-min S&P futures data 2011–Jul 2021 is **777 trades with a NEGATIVE return**; gaps worse than −0.7% have expectancy **−0.11%/trade**; restricting to −0.15%..−0.7% and adding "open > yesterday's 25-day MA" (i.e. gap-and-go) only reaches **+0.06%/trade — "still far from profitable"**; the short side is worse. They also state plainly: *"What worked nicely before doesn't work nearly as well anymore… you need more criteria and filters or accept fewer trades"* and *"We used to trade quite a few of them, but as of today we only trade very few."* Gap-fill base rates they publish (**E-mini S&P continuous futures, 25 years, same-day fill only** — note: futures, not cash equities): gaps >1%: bullish **28% filled (204 instances)**, bearish **33% (202)**; gaps >0.5%: 43%/42%; gaps >0.1%: 59%/61%. Their own caution on this table: *"even though the gap has a high chance of getting filled on the same day it doesn't mean it's a profitable trading strategy if it's negatively skewed."*

**Data needed:** daily OHLC only (IBS and 5-RSI are daily). **Fully testable on our data today.**

**Robinhood-feasible?** **PARTLY — instrument problem.** Rules are long-only and both legs are inside regular hours (buy at open, sell at close). But the instrument is the S&P 500 / SPY: SPY cannot be bought whole-share at a $105 clip. Options: (a) apply the identical signal to a basket of sub-$50 single names (changes the statistical claim — must re-test), or (b) trade a cheap broad ETF proxy. As written on SPY: **NO**. As a signal template on our own universe: yes.

---

## 4. "Buy the Dip" / "Close near Low" (Russ_CW, r/algotrading) — weak close → next session
**Thesis:** When the close sits in the bottom of the day's range, the next session is more likely up — and the author found *the profit is concentrated in the overnight gap*.

**EXACT rules:**
- Compute Range = High − Low; Dist = Close − Low; **CloseDistance% = Dist/Range × 100**.
- Signal: **CloseDistance% < 20%** AND (edit, 25/08) **day's range > 10 index points** (to exclude micro-range days; author says this should really be a function of recent average range).
- Entry: **buy at that day's close**; Exit: **at the next day's close**. (Earlier 2021 version of the same idea: identical 20% rule, exit next close.)
- Universe tested: S&P 500 index, 20 years; robustness re-run on Dow, Nasdaq Composite, Russell, Nikkei.

**Reported results:** Win-rate-vs-threshold curve and the equity/metrics tables are **PNG images → NOT-EXTRACTED**. Text-level claims only: beats buy-and-hold, **lower drawdown**, **in the market only 19% of the time**, and outperformed buy-and-hold **in all 5 indices tested**.
Sources: https://www.reddit.com/r/algotrading/comments/1f0689m/backtest_results_for_a_simple_buy_the_dip_strategy/ and https://www.reddit.com/r/algotrading/comments/ni1zuj/backtesting_a_close_near_low_strategy/
**CODE STATUS: DEAD.** The post links `https://github.com/russs123/Buy-The-Dip` and the RSI post links `https://github.com/russs123/RSI`; I fetched both — **HTTP 404**, and the GitHub REST listing of `russs123`'s repos (100/page, sorted by update) contains **no trading repos at all** (only game-dev/pygame/Godot tutorials). All of this author's strategy code has been removed. Rules survive only as forum text.

**Decay / honesty evidence (author's own, in-thread — this is the useful part):**
- Author: *"a lot of the profit actually came from the gaps, so that's why the backtest buys at the day's close, to take advantage of that gap."*
- Author, when asked: *"I also looked at buying at the next day's open as a comparison and the returns suffered so it seems that a gap contributes to the returns."* → **the edge is specifically the close-to-open leg, and it does not survive moving entry to the next open.**
- Author admits: fees/slippage **not modelled**; entry/exit exactly at the close is **not achievable** and would have to become "a few minutes before the close."
- Top commenter (u/GoootIt): *"You can't enter at the close price if the close price generates your signal… Is there an opening auction that you can participate in?"* and warns the index-selection is itself a bias.

**Data needed:** daily OHLC only. **Fully testable now.**

**Robinhood-feasible?** **CONDITIONALLY YES.** Long-only, both legs in regular hours (buy ~15:55 limit, sell next ~15:55 limit — an overnight+full-day hold). Instrument problem again: it was tested on indices, not tradable names, so we must re-test on sub-$50 single names, where the "close near low" event is far noisier than on an index. Because the author's own test says the gap is the edge, our real version should probably exit at the **next open** rather than next close — but he reports that variant is worse, which is a red flag worth resolving empirically.

---

## 5. Alvarez RSI(2) mean reversion, open-to-open — plus the "avoid recent gap-down" filter
**Thesis:** Classic long-only RSI(2) oversold bounce, executed entirely on opens; and a separately-quantified filter showing recent gap-down names should be excluded.

**EXACT rules (Entry-on-Open variant):**
- Universe: is/was a **Russell 3000** member; close > $1; 20-day MA of Close×Volume > $500,000.
- Regime: **$SPX above its 200-day MA**; stock **above its 200-day MA**.
- Signal: **2-period RSI < [0.5 … 5]** (optimized band).
- Ranking: **highest 100-day historical volatility first**; **max 10 positions**.
- Entry: **next day at the open**.
- Exit: **2-period RSI > 70 → exit on the next open**.
- Test window: 1/1/2007 – 6/30/2021.
Source: https://alvarezquanttrading.com/blog/mean-reversion-entry-at-open-vs-intraday-pullback-vs-confirmation/

**Reported results:** Yearly-return and stat tables are **PNG images → NOT-EXTRACTED**. Extractable text comparisons: switching entry from "at open" to a **limit 1–4% below the close** improved **CAR by 21%**, cut exposure 33%, cut MDD, and **doubled avg %P/L**. Stop-entry-above-close ("confirmation") was better than at-open but worse than the limit-below-close, *except in 2021* where confirmation was best. Author's verdict on at-open entry: *"Not great returns but something to compare against."*

**Companion filter, with text numbers:** excluding setups on stocks that had a **≥5% gap in the last 10 days** produced **+28% CAR and +25% avg %P/L for only −6% trades**, and the effect is driven specifically by avoiding **gap-DOWN** names ("the research points to skipping trades that recently gapped down").
Source: https://alvarezquanttrading.com/blog/avoiding-gap-trades/

**Decay evidence:** Author's opening line: *"My current mean reversion strategy, which enters on a limit down, was doing great until a few months ago when the performance started to slip"* — i.e. a live practitioner reporting real-time degradation of the limit-below-close entry, with 2021 favouring the opposite (confirmation) entry. Blunt conclusion: *"no one method always works."*

**Data needed:** daily OHLC + volume + RSI(2) + 200MA + 100-day HV + survivorship-free Russell-3000 membership. Membership history is the only gap; our 6,500-name IBKR daily set is a workable proxy.

**Robinhood-feasible?** **YES.** Long-only; both legs at the open (regular hours, limit orders); no MOC/MOO, no stops. Multi-day hold (until RSI2>70), so it is not strictly close-to-open but it is exactly our order-type profile. Note the *conflict with our cheapest execution*: his best entry is a limit below the close, which is also RH-friendly. Position count 10 → we can run 6.

---

# TIER 2 — REAL CODE, BUT MINUTE-BAR OR ORDER-TYPE BLOCKED

## 6. Opening Range Breakout for "Stocks in Play" (QuantConnect / Zarattini–Barbon–Aziz 2024)
**Thesis:** Trade the 5-minute opening-range breakout only on the 20 stocks with abnormal opening volume ("in play"), with ATR-scaled stops and 1%-risk sizing.

**EXACT rules (full working code published, C# + community Python port):**
- Universe: **1,000 most liquid US equities** (dollar-volume ranked), **price > $5**, **ATR(14) > $0.50** (paper used 7,000 names).
- "In play" score at **09:35**: (volume in first 5 min today) ÷ (average volume in first 5 min over prior 14 days) = RelativeVolume; require **RelVol > 1**; take the **top 20 by RelVol**.
- Direction: if the 09:30–09:35 bar **closed above its open → long stop-entry at the OR high**; if **closed below → short stop-entry at the OR low**.
- Stop: OR high/low ∓ `stopLossAtrDistance × ATR(14)`.
- Size: quantity such that a stop-out loses **1% of the portfolio slice allocated to that name**, capped at the equal-weight slice (1/MaxPositions).
- Exit: **stop loss, or at the close** (never overnight).
**Results in-platform:** 2016 backtest → **Sharpe 2.396, beta −0.042** vs SPY buy-and-hold Sharpe 0.836. Parameter sweep (OR 5–25 min × universe 500–1500): **17 of 25 combos beat the benchmark**; ATR filter sweep $0–$2 gave Sharpe 1.5–2.7; unit-less ATR>1%-of-price variant gave **Sharpe 2.237, PSR 97%**.
Source: https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/ (backtested in-platform, code attached) · paper: SSRN 4729284.

**DECAY / FAILURE EVIDENCE — the richest in this whole report (all from that thread + the r/algotrading thread that promoted it):**
- **Full-period reality check by the person who popularised it** (u/shock_and_awful): ran it 2016→present: *"the sharpe stayed decent at ~1.4; max DD at 8.1; Beta at 0.03 and PSR at 100% BUT… An embarrassing Net return of 176% compared to SPY. It practically fell asleep during the post-covid rally."* And: *"Thought about applying leverage but the win rate is abysmal (17%)."* https://www.reddit.com/r/algotrading/comments/1hezqql/opening_range_breakout_for_stocks_in_play_code/
- **After-hours fill contamination (April 2026 comment):** *"the stop buy/sell orders… seem to feed through to after hours in the backtests. Buy/sell orders that are unfilled during the day may get executed after hours at non realistic fills… The after-hours fills were acting as an artificial performance booster… Strip that out and the true intraday-only performance is much more marginal."*
- **Slippage:** *"These backtests are not representative of live performance. When adding slippage, it can be significant at the open due to volatility, small-cap stocks, and using stop orders, making the results much less appealing."* Another: *"MarketImpactSlippage has quite a savage effect."*
- **Costs/shorting:** *"requires a good broker platform to execute, especially on the short side. IBKR works, but the trading volumes are so high in this strategy that transaction fees become a real issue… most people will have a hard time sticking to it live because of the txn fees."*
- **Backtest-vs-live mechanics:** on minute resolution the protective stop is only placed *the minute after* the entry fills, while live it is placed within seconds — *"This creates quite a difference between backtesting and live trading."* Also *"backtesting on minute resolution provides very different results from second resolution."*
- **Independent replications diverge:** the community Python port scored **Sharpe −0.148** where the C# version scored 2.396 (traced to ATR being warmed up on minute instead of daily bars); a separate user reimplemented it in **backtrader + Alpaca for 2023–2025 and got "way worse Sharpe… It seems like the strategy does not work with the current market."**
- **Regime fragility:** collapses in 2000–2002; *"the whole period of July 2001–end of 2002 is basically flat"*; author of that test: *"I still distrust the results, I guess I've got quite a bit of overfitting going on."*
- **Parameter drift:** multiple users independently found **shortening the opening range to 1–2 minutes** and *enlarging* the universe improved Sharpe/CAGR/MDD across every period 2010→today — a strong hint the "5-minute" choice is not the real structure.

**Data needed:** 1-minute (ideally second) bars for a 1,000-name universe + 14-day history of first-5-minute volumes + daily ATR. **We do not have equity minute bars.**
**Robinhood-feasible?** **NO.** Needs shorts for half the signals; needs intraday **stop-market** orders on 20 simultaneous names; needs whole-share sizing at 1%-risk granularity that $105 cannot express; win rate 17% means the payoff comes from a few large winners that a $105 clip cannot capture; and the honest version of its returns (176% over ~9y, worse than SPY) does not justify the plumbing.

## 7. Concretum Group ORB backtester (single ticker, Polygon minute data)
**Thesis:** Same ORB family, but published as a complete, parameterised Python backtester — the cleanest *code* artifact in the ORB family.

**EXACT rules, as implemented in the published code (`backtest(days, p, orb_m, target_R, risk, max_Lev, AUM_0, commission)`):**
- Opening range = first `orb_m` minutes. `side = sign(close of last OR candle − open of first OR candle)`.
- Entry = **open of the candle immediately after the OR window**.
- Stop = **min low of OR window** (longs) / **max high** (shorts), expressed as a fraction of entry.
- Target = `entry × (1 + target_R × stop)` (or infinite if `target_R = inf`, i.e. "no target → exit at the last close of the day").
- Sizing: `shares = floor(min(AUM×risk/(entry×stop), max_Lev×AUM/entry))` — **explicit whole-share floor**, ATR(14) from *daily* bars is split-adjusted into intraday scale, commission charged **×2** (both sides).
- Exit: stop, target, or **final close of the day** (bar-order logic handles same-bar stop-vs-target).
- Data plumbing: Polygon 1-minute aggregates filtered to **09:30–15:59 ET**; ATR from daily adjusted bars, shifted by 1 to avoid look-ahead; out-of-sample shading begins **2023-02-17** in the plotting code.
Source: https://concretumgroup.com/backtesting-the-opening-range-breakout-orb-strategy-using-polygon-io/ (full code in the page).
**Reported results:** the article publishes **code only** — the equity curve/statistics are produced by the reader's own run; the config block (TICKER, orb_m, target_R, risk, max_Lev, commission) is **not in the fetched page** (I grepped for every one of those assignments: absent). So: **NO reported numbers → NOT-EXTRACTED / claimed-nowhere.** The underlying paper is Zarattini–Aziz, SSRN 4416622/4729284 family.
**Data needed:** 1-minute bars per ticker (Polygon; free tier limited to 2 years) + daily bars for ATR. **We lack equity minute bars.**
**Robinhood-feasible?** **NO** as written (shorts + intraday stop + target orders on a leveraged ETF-style single ticker). Its *value to us is the code*: the whole-share `floor()` sizing, the same-bar stop/target resolution, and the `commission×2` accounting are directly reusable in our own backtester.

## 8. Russ_CW 15-minute ORB (index/CFD) — long-only, time-boxed
**Thesis:** Use the 09:30–09:45 candle as the range; take only *confirmed* upside breakouts and only in the morning.
**EXACT rules:** On the 15-minute chart, the **09:30–09:45 candle defines the range**; wait for a **15-min candle to close above the range high**; **enter on the next candle**, but only **before 12:00**; **stop at the bottom of the range**; **take-profit at 1.5 : 1**. Long-only as tested. Universe tested: **5 years of S&P 500 CFD data**; also BTC and GBP/USD.
**Reported results:** stats panel is an **image → NOT-EXTRACTED**. Text claims: "very promising"; profits concentrated in the first couple of hours (hence the 12:00 cutoff, which is itself an in-sample optimisation); BTC and GBPUSD "positive".
Source: https://www.reddit.com/r/algotrading/comments/1j9pxsr/backtest_results_for_the_opening_range_breakout/ — **code link `github.com/russs123/backtests` is 404 (verified)**.
**Decay evidence (in-thread):** top comment: *"it's a bullish strategy that you backtested during a predominantly hulked-out bull market."* Author's own reply: the **short/downside version was NOT profitable on the S&P 500** ("mixed results"), only BTC worked. A later user tested the same rules on GBPJPY back to 2017 and got **break-even** — *"it happened to be a short term edge."*
**Data needed:** 15-minute bars. **Not available for our equities.**
**Robinhood-feasible?** **NO** — needs 15-min bars, an intraday protective stop on a $105 whole-share position (a range-width stop on a sub-$50 stock rounds to 1–2 shares, so the 1.5:1 geometry is unexpressible), and it was validated on an index CFD we cannot buy.

## 9. melkerliljegren 5-minute ORB (GitHub, full notebook)
**Thesis:** Textbook 5-minute ORB with an extreme 10R target.
**EXACT rules (verbatim from README):** first **5 minutes** after the open define the opening range; **if price > daily open → long; if price < daily open → short**; **stop-loss = opposite side of the range**; **take-profit = 10 × risk distance**; **close all positions before market close**.
**Reported results:** *"backtested on Apple (AAPL) data"*, presented as an equity/cumulative-return **PNG only → NOT-EXTRACTED**. Repo is explicitly a learning project (1 star, author says "my first attempt… main goal is to practice Git/GitHub").
Source: https://raw.githubusercontent.com/melkerliljegren/opening-range-breakout/main/README.md (repo: https://github.com/melkerliljegren/opening-range-breakout) — **backtested in-repo, single ticker, results not stated numerically.**
**Data needed:** 5-minute bars.
**Robinhood-feasible?** **NO** (shorts, intraday stops, minute bars, single-name 10R target implies tiny win rate).

---

# TIER 3 — INTRADAY MOMENTUM / REVERSAL WITH CODE, EVIDENCE MOSTLY NEGATIVE

## 10. Intraday ETF Momentum (Gao–Han–Li–Zhou), QuantConnect tutorial implementation
**Thesis:** The sign of the **first half-hour** return predicts the sign of the **last half-hour** return.
**EXACT rules (code published):** Universe = **SPY, IWM, IYR** (QC narrowed it from the paper's DIA/QQQ/IWM/EEM/FXI/EFA/VWO/XLF/IYR/TLT); minute resolution. `return_bar_count = 30`. **morning_return = (close of the 30th minute − YESTERDAY'S close) / yesterday's close** (note: this includes the overnight gap — that is Gao et al's r₁). When minutes-to-close == 31, **emit an insight in the sign of morning_return**; hold the **last 30 minutes**; exit at the close via a **MarketOnClose order submitted in the same timestep as the entry market order** (`CloseOnCloseExecutionModel`).
**Reported results:** Paper's numbers, quoted by QC: average annual **6.67% (SPY), 11.72% (IWM), 24.22% (IYR)**; equal-weighted **14.2%**.
**QC's own out-of-sample verdict — NEGATIVE, and this is the valuable bit:** *"We conclude that the momentum pattern documented by Gao et al (2017) produces lower returns over our testing period."* Backtest 1/1/2015–8/16/2020: **strategy Sharpe −0.764 (ASD 0.05)** vs **benchmark +0.709 (ASD 0.185)**; Fall-2015 sub-period strategy **−0.696**. The only period it shone was the **2020 crash itself (Sharpe 4.8)**.
Source (JS-rendered live page returns nav only; text recovered from Wayback): http://web.archive.org/web/20221126191324/https://www.quantconnect.com/tutorials/strategy-library/intraday-etf-momentum
**Data needed:** 1-minute bars for the ETFs. **We lack equity/ETF minute bars.**
**Robinhood-feasible?** **NO.** Requires a **MarketOnClose order**, which Robinhood does not offer; requires shorts on negative-r₁ days (long-only halves it); SPY/IWM/IYR are all far above our $105 whole-share ceiling. Also QC's own OOS Sharpe is negative.

## 11. "Mind the Gap" intraday reversal (QuantConnect community, Robert Wiener) — gap-down vs ATR, exit +15 min
**Thesis:** Same gap-down-reversion idea as #1, but harvested entirely **inside the first 15 minutes** — the only version in this report that never holds overnight.
**EXACT rules:** Universe = **S&P 500 stocks trading above their 100-day SMA**. Entry: **at the market open**, if the stock **gaps down more than 1.2 × its 14-day ATR** vs yesterday's close → **go long**. Exit: **liquidate all positions 15 minutes after the open**. Built by combining QC Bootcamp Lesson 6 ("Fading the Gap") and Lesson 7 (EMA momentum universe).
**Reported results:** **NONE published.** Author is explicit: *"I'm a beginner, and my primary goal here was to learn QuantConnect and the LEAN framework, not to build a profitable trading system… While this strategy isn't optimal… it served its purpose as a learning tool. This strategy may not beat the market."* A backtest link exists but the metrics are not in text → **NOT-EXTRACTED**.
**Known bugs (posted in-thread by QC's assistant):** the algorithm *"never sets `self.is_warming_up = False` after warm-up completes, so normal logic in `on_data` and scheduled functions likely never runs as intended"* — i.e. **the published code may not even be executing its own logic**. Treat as a rules template, not a validated result.
Source: https://www.quantconnect.com/forum/discussion/19075/mind-the-gap-an-intraday-reversal-strategy-using-gap-downs-and-atr/ (inspired by Quantitativo, item #1).
**Data needed:** minute bars (for the +15-min exit) + daily ATR(14) + 100-SMA. The **entry signal is daily-bar-computable**; only the exit needs intraday.
**Robinhood-feasible?** **MARGINAL-YES on order types, NO on data.** Both legs (09:30 limit buy, 09:45 limit sell) are inside regular hours → 5.9 bp, long-only, no stops needed. But we cannot backtest the 15-minute exit without minute bars — we'd have to proxy the exit at the same-day close (which converts it into a different strategy) or buy minute data for S&P-500 names. Also S&P 500 constituents mostly exceed $50/share, so the whole-share constraint bites hard.

## 12. Ernie Chan "Buy-On-Gap" as coded on QuantConnect (forum thread, Jared Broad)
**Thesis:** Buy stocks that gap down below the previous day's low at the open, exit the same day's close.
**EXACT rules as discussed/coded:** compare **today's open vs yesterday's LOW**; if the open gapped down below it → buy. Poster's intent, confirmed by QC's CEO in-thread: *"I want to buy on the open that has gapped down and then sell on the close of that same TradeBar."* Implementation reality noted by Jared Broad: with minute data *"you'd be buying 1 bar into the day (09:31) based on the opening price of the opening bar. You could implement additional checks for 3.45pm to close out the position."*
**Reported results: NONE.** This thread is order-plumbing Q&A, not a backtest → treat the *numbers* as UNVERIFIED here. (The canonical statistics for this strategy live in Chan's *Algorithmic Trading* Ex. 4.1, already catalogued in our practitioner bank, along with his own "Beware of Low Frequency Data" warning that 1-minute-bar backtests overstate live fills for exactly this kind of open-auction reversal.)
Source: https://www.quantconnect.com/forum/discussion/598/buy-on-gap-strategy-logic/
**Data needed:** daily OHLC is enough for the *signal* (open vs prior low) and for an open→close backtest. **Testable on our 20y daily set immediately.**
**Robinhood-feasible?** **YES on mechanics** (long-only variant: buy 09:31 limit, sell ~15:50 limit; both regular hours), **but the edge is unquantified in this source** and item #3's evidence says naive gap-fill is negative after costs. Low priority: test only as a cheap sanity baseline alongside #1.

## 13. Connors RSI(2), community re-test with a next-open entry (Russ_CW)
**Thesis:** The most-published short-term mean-reversion rule set, re-tested over 34 years — with the practical modification that you cannot actually buy the signal close.
**EXACT rules:** Indicators = **5-day MA, 200-day MA, RSI(2)**. Long when **price is above the 200-day MA** and **RSI(2) dips below 5**. Canonical entry is the **close of the signal day**; the author *changed it* to **the next day's open** because *"the strategy requires you to buy on the close, but this doesn't seem realistic as you need the market to close to confirm the final values of your indicators."* Exit when **price closes above the 5-day MA**. Tested on **S&P 500 index, 1990–2024 (34y)**.
**Reported results:** metric tables and the RSI-period × threshold heatmap are **images → NOT-EXTRACTED**. Text claims: annual return **low in absolute terms** but strong **per-unit-of-exposure**; drawdown much better than buy-and-hold; win rate "very impressive"; **short-only mirror returns just 0.67% p.a. with 1.92% time in market** (author reads that as robustness, not as an edge).
**Variations, all text:** adding a "close below 200MA" stop made **every metric worse**; time-based holds of 1–20 days did not raise annual return and worsened everything else — **the best time-based variant was a 0-day hold, i.e. buy at the open and exit at the same day's close** (an explicitly *intraday* variant of RSI2, and per the author roughly on par with the original).
**Author's own caveats (text):** tested on the **untradable index**, **no fees**, **no dividends**, no tax.
Source: https://www.reddit.com/r/algotrading/comments/1fm5lfj/backtest_results_for_connors_rsi2_strategy/ — **code link `github.com/russs123/RSI` is 404 (verified)**.
Independent number for the same family (vendor, not repo): https://www.quantifiedstrategies.com/rsi-2-strategy/ reports **avg gain 0.9%/trade, ~9% annual, max DD 34%**.
**Data needed:** daily OHLC. **Fully testable now.**
**Robinhood-feasible?** **YES for the 0-day-hold variant** — buy at the open, sell at that day's close, both legs regular hours, long-only, no stops. This is the single cheapest way for us to test whether the "oversold bounce" is intraday or overnight. Instrument caveat: index-tested, so re-run on sub-$50 names.

---

# TIER 4 — COMMUNITY FAILURE LEDGER (not a candidate; use as a prior)

## 14. "17 strategies dead on MNQ/NQ" — the most detailed public negative result I found
r/algotrading, Apr 2026, 120 upvotes, 161 comments. Futures (MNQ/NQ), **so read it as directional evidence about the *family*, not about equities** — and it is an anecdote in the sense that no code was posted, but it carries specific numbers and a methodology description.
Source: https://www.reddit.com/r/algotrading/comments/1spd5nf/6_months_full_time_on_algo_17_strategies_dead_on/

Directly relevant findings:
- **ORB 5/15/30-minute, with and without ATR trail: ~50% win rate** once measurement bias was corrected.
- **Gap fill at RTH open:** *"worked in recent years but breaks on 7-year history."*
- **Overnight gap fade, measured on 1,696 days of MNQ:** mean gap **+8.3 pts**, but gap-fill rate **inversely scales with size** — **81% fill for tiny gaps** (unexploitable after costs), **33% for gaps > 0.5σ**, **literally 0% for gaps > 1.5σ**. *"The retail folklore that big gaps fill is just false on MNQ. The big gaps continue; they don't revert."* No up/down asymmetry (**30% vs 29%**) so you cannot even pick a side. **This is consistent with item #3's E-mini S&P fill table (28%/33% for gaps >1%) — though both are index futures, so neither is independent evidence about single-stock gaps.**
- **Overnight momentum follow-through: "nothing."**
- **Bollinger-band 5-min mean reversion** BB(20,2σ), ATR stops, 09:40–15:50 with lunch skipped, force-flat 15:45, tested with a 100 ms + 50 ms latency model, one-tick slippage, $0.50/contract/side, next-bar order submission, 68 unit tests: **117 trades in 2023, WR 48.7%, expectancy −$6.52/trade, PnL −$762, Sharpe −1.34**; bootstrap 95% CI on expectancy [−$14.99, +$1.82].
- Post-hoc: the "range regime" filter he expected to help was the **worst** segment (−$11.59/trade, WR 37%); *"In a tight range, the bands are so narrow the signal is triggering on pure bar noise."*
- An experienced responder (u/BottleInevitable7278): *"I tried many 100s of studies claiming Sharpe 2 to over 6 in intraday ES and NQ and they were just curve fitted and completely unrealistic after realistic trading cost… The best was around Sharpe 1.2 but on daily data… Anything on intraday is usually an execution game."*

**Use:** this is the single best argument for our stated preference — **daily-bar, open/close-leg strategies over minute-bar intraday ones** — and a specific warning that *gap-fade sized by gap magnitude is backwards*: big gaps continue.

---

# SUMMARY TABLE

| # | Strategy | Type | Rules exact? | Real code? | Numbers in text? | Daily-bar testable? | RH long-only, both legs RTH? |
|---|---|---|---|---|---|---|---|
| 1 | Quantitativo Mind-the-Gap (open→next open) | B | Yes except threshold | No | **Yes** (22.9%/yr, Sh 1.66, +0.11%/tr @10bp) | **Yes** | **YES** |
| 2 | Alvarez Broken Arrow (−15% close → next open) | B | Yes | No | **Yes** (+0.77%/56%, +0.66%/60%) | **Yes** | **YES** (spread caveat) |
| 3 | QS gap-down + IBS + RSI overnight | B | Yes (RSI scale ambiguous) | Paid AmiBroker | **Yes** (+0.48/tr, PF 1.8) + strong negatives | **Yes** | Signal yes / SPY instrument NO |
| 4 | Buy-the-Dip / close-near-low | B | Yes | **404 dead** | Charts only | **Yes** | Conditional |
| 5 | Alvarez RSI2 open-to-open + gap filter | B | Yes | No | Partial (+21% CAR, +28% CAR filter) | **Yes** | **YES** |
| 6 | ORB Stocks-in-Play (QC/Zarattini) | A | Yes | **Yes, in-platform** | **Yes** (Sh 2.396 '16; Sh 1.4 / 176% full-period) | No (minute) | **NO** |
| 7 | Concretum ORB backtester | A | Yes | **Yes, full Python** | **No** (code only) | No (minute) | NO (code reusable) |
| 8 | Russ_CW 15-min ORB | A | Yes | **404 dead** | Charts only | No (15-min) | NO |
| 9 | melkerliljegren 5-min ORB | A | Yes | **Yes, notebook** | Charts only | No (5-min) | NO |
| 10 | Intraday ETF Momentum (Gao et al) | A | Yes | **Yes, QC code** | **Yes** — incl. **QC OOS Sharpe −0.764** | No (minute) | **NO** (needs MOC) |
| 11 | QC Mind-the-Gap +15min exit | A | Yes | Yes (buggy) | None | Signal yes / exit no | Order types yes, data no |
| 12 | Chan Buy-On-Gap on QC | A | Yes | Sketch | None here | **Yes** | YES mechanics, edge unquantified |
| 13 | Connors RSI2, next-open entry (+0-day-hold variant) | A/B | Yes | **404 dead** | Charts only (+vendor: 0.9%/tr, 9%/yr, DD 34%) | **Yes** | **YES** (0-day variant) |
| 14 | "17 strategies dead" ledger | — | n/a | No | **Yes** (many) | n/a | n/a — use as prior |

# RECOMMENDED NEXT ACTIONS
1. **Backtest #1 (Quantitativo gap-down open→next open) on our 20y daily set first** — it is the only candidate that is simultaneously long-only, daily-bar-testable, RH-order-type-native, and comes with a text-verified net-of-10bp track record. We must re-derive the undisclosed gap threshold ourselves (sweep it and look for a plateau, not a peak).
2. **Backtest #2 (Broken Arrow) as a low-frequency satellite** — biggest per-trade edge (66–77 bp vs our 5.9 bp), but re-measure spreads on actual −15% names before believing our cost model.
3. **Run #13's 0-day-hold RSI2 variant and #12 (open→close gap-down)** as the two cheapest "is the bounce intraday or overnight?" experiments; both are pure daily-bar open/close arithmetic.
4. **Apply Alvarez's "no ≥5% gap in the last 10 days" filter (#5) to every mean-reversion lane** — text-verified +28% CAR / +25% avg P/L for −6% trades, and it is one line of code on daily bars.
5. **Do NOT build the ORB family (#6–#9) on this account.** Independent replications diverge wildly, the QC backtest was inflated by after-hours fills on unfilled stop orders, the honest full-period return underperformed SPY, win rate is 17%, and half the signals need shorts.
6. **Steal code, not signals, from #7** — its whole-share `floor()` sizing, same-bar stop-vs-target resolution, and 2× commission accounting are exactly the honest-fill primitives our backtester needs.
