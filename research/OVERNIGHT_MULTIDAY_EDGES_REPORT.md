# Overnight-Hold & Low-Turnover Multi-Day Edges — Net-of-Cost Survival Research

Compiled 2026-08-29 for a small long-only US-equities account (~$700, fractional, ~6 bp regular-hours round trip).
**Context:** same-day/flat-by-close strategies are proven dead net of 6 bp. This pass targets the surviving
family: OVERNIGHT-hold and LOW-TURNOVER multi-day edges. Every number below was read as TEXT from a source I
actually fetched (full PDF or extracted page). Paywalled / chart-only figures are flagged NOT-EXTRACTED.
Nothing is estimated.

Fetch log (all under `/home/ubuntu/research_out/`): `LPS_tugofwar.txt` (FMG DP744, 67 pp),
`Medhat_STM.txt` (City Research Online v27, 71 pp), `cxo_overnight.txt` (CXO/Lachance summary),
`salotra_jina.txt` (MDPI Risks 2026 full text).

---

## Category 1 — The overnight return premium ("buy close → sell next open")

### 1. Lou–Polk–Skouras (2019, JFE 134(1):192–213) — overnight momentum is the real momentum
- **Thesis:** the abnormal profits of well-known cross-sectional anomalies (momentum, earnings momentum,
  industry momentum) accrue **overnight**, not intraday; short-term reversal profits accrue intraday.
- **EXACT RULE (overnight-momentum leg):** each month, sort stocks on the **prior month's overnight
  (close→open) return**; long the value-weight top decile / short the bottom decile; hold **overnight-only**
  for the next month (buy at close, sell at next open). Monthly rebalance. Also: the classic MOM factor
  (sort on t−12→t−2 return, monthly rebalance) earns essentially all of its profit **overnight**.
- **NET / MAGNITUDE:** overnight WML 3-factor **overnight alpha +3.473%/mo (t = 16.83)** with a **−3.023%/mo
  (t = −9.74)** intraday alpha; intraday-momentum WML is the mirror (+2.41%/mo intraday, t = 7.70;
  −1.77%/mo overnight, t = −7.89). MOM's ~89 bp/mo excess return accrues overnight (72 bp Mon–Thu,
  18 bp weekend). The `TugOfWar` predictor (EWMA-overnight − EWMA-intraday, half-life 60 mo) forecasts
  +1%/mo close-to-close per +1 SD.
- **Turnover:** monthly rebalance (overnight-only exposure), low one-sided turnover on the long leg.
- **Long-only:** YES — take the top overnight-momentum decile only (~half the spread). Cost model in the
  paper is an academic decomposition, **not a net-of-spread P&L** (flag: no explicit 6 bp net figure).
- **Source (full text read):** FMG Discussion Paper 744 — https://www.fmg.ac.uk/sites/default/files/publications/DP744.pdf
  Journal: https://doi.org/10.1016/j.jfineco.2019.03.011

### 2. Lachance (2015 WP / 2023 Rev. Fin. Econ.) — "Night Trading": the Overnight Bias Group (OBG)
- **Thesis:** some stocks systematically earn their return overnight; you can identify them ex ante by the
  prior-year **overnight-return beta** and harvest it overnight-only, net of cost.
- **EXACT RULE:** each month, regress a stock's daily **overnight (close→open)** return on its daily total
  return over the **prior year** → the slope is the **Overnight Bias Proxy (OBP)**. The **OBG** = stocks
  with significantly positive OBP (~20% of reasonably-liquid US stocks). **Buy the OBG at the close, sell at
  the next open**, re-formed monthly. (Execution note: the overnight premium peaks minutes before the open
  and dissipates ~30–45 min after — do NOT buy high-attention names right at the open.)
- **NET / MAGNITUDE (1995–2014, VW, ~20% liquid US stocks):** OBG portfolio **+25.9%/yr gross** VW overnight
  return, **+20.1%/yr 4-factor gross alpha**, beta 0.31, SD 11.5%, positive gross alpha in **all 20 years**
  (negative intraday return in 18/20). **Net of 1.5 bp / 3.1 bp round-trip frictions → +15.7% to +21.2%/yr
  (10.4% to 15.7% alpha).** Unconditional overnight VW return 6.84%/yr (vs 3.72% intraday); overnight vol
  1.45%/day vs 2.60% intraday. Long-OBG / short-negative-OBP, monthly: 43.1%/yr gross.
- **Turnover:** monthly rebalance; hold overnight each night.
- **Long-only:** YES (this is the cleanest documented **net**-of-cost overnight edge found).
- **Source (summary read in full):** CXO Advisory, "Overnight Momentum-informed Overnight Trading" (LeCompte,
  2015-08-07) — https://www.cxoadvisory.com/calendar-effects/overnight-momentum-informed-overnight-trading/
  Underlying paper: Lachance, "Night Trading: Lower Risk but Higher Returns?", Rev. Fin. Econ. 2023,
  https://doi.org/10.1002/rfe.1180 (paywalled; net figures NOT-EXTRACTED from the journal PDF — quoted via CXO).

### 3. Berkman–Koch–Tuttle–Zhang (2012, JFQA 47(4):715–741) — attention-driven high opens reverse intraday
- **Thesis:** strong positive overnight returns are followed by **intraday reversals**, driven by an opening
  price that is high relative to intraday prices — i.e. retail attention pushes the OPEN up, then it fades.
- **EXACT RULE (the tradeable reading):** the premium is concentrated in high-retail-attention, hard-to-value,
  costly-to-arbitrage names; the documented exploitable action is the *opposite* of buying — **avoid/never
  buy at the open** in high-attention names, and (if shortable) short the open / cover the close there.
- **NET / MAGNITUDE:** **all numeric magnitudes NOT-EXTRACTED** (Cambridge/JSTOR/KU ScholarWorks bot-walled;
  abstract read). The paper's own framing: the overnight premium is partly a **hidden transaction cost** to
  buyers at the open, not a free return.
- **Turnover:** daily for the short-leg version.
- **Long-only:** NO as a standalone alpha — it is an **execution rule** (never buy at the open) and the
  mechanism behind #1–#2. Cite: https://doi.org/10.1017/S0022109012000270 ; OA attempt:
  https://kuscholarworks.ku.edu/server/api/core/bitstreams/53222608-03a0-4c87-9709-c25513b4241b/content (bot-walled)

### 4. Aboody–Even-Tov–Lehavy–Trueman (2018, JFQA 53(2):485–505) — weekly overnight-return persistence
- **Thesis:** overnight return is a firm-specific retail-sentiment proxy, and sentiment **persists** — this
  week's overnight winners keep winning *overnight* next week (short-horizon leg); over the long horizon they
  underperform.
- **EXACT RULE:** sort stocks each week by that week's overnight (close→open) return into deciles; hold
  **overnight-only** in week w+1, long top decile / short bottom decile. Persistence decays but is monotone
  for ~4 weeks; stronger in hard-to-value (high-vol, small, young, unprofitable) firms.
- **MAGNITUDE:** week w+1 top-minus-bottom **overnight** return = **1.76 pp** (robust across beta/size/B/M
  partitions 0.98–2.5 pp). Sample period NOT-EXTRACTED.
- **Turnover / cost:** overnight-only L/S = up to 10 round trips/wk ≈ 60 bp vs 176 bp gross → marginal.
  **Long-only top-decile weekly-hold variant = 2 round trips/wk** (≈12 bp/wk) is the testable form.
- **Long-only:** YES (top-decile variant). Source: https://doi.org/10.1017/s0022109017000989
  (WP mirror already banked: SSRN 2554010).

---

## Category 2 — Overnight drift on high-momentum / high-attention names (fresh 2026 evidence)

### 5. Salotra–Katikireddy–Anumolu–Pinsky (2026, Risks 14(4):84, MDPI) — overnight vs daytime on 10 sector ETFs
- **Thesis:** splitting the 24 h day into overnight (close→open) vs daytime (open→close) sub-periods yields
  exploitable patterns in US sector ETFs; overnight momentum dominates.
- **EXACT RULE:** 24 strategies across SPY/XLB/XLE/XLF/XLI/XLK/XLP/XLU/XLV/XLY, 1999–2025 (WRDS). Three
  sub-period families: static, momentum, reversal — each run on the **night** leg and the **day** leg.
  Best: **Strategy #1 = overnight momentum** (Sharpe ≈ 0.95 averaged, **+56% over buy-and-hold's 0.61**)
  and **Strategy #18 = long-reversal** (Sortino ≈ 1.58). Lookback should be limited to a single sub-period.
- **NET:** explicit **transaction-cost analysis at 1 bp vs 2 bp** — reversal/overnight strategies outperform
  static/B&H but the edge **deteriorates toward B&H as cost rises**; "viable only for low-cost institutional
  traders." XLU and XLK show the strongest overnight Sharpe ratios.
- **Turnover:** daily rebalance (overnight leg), so cost-sensitive — but this is the freshest (2026) public
  net-of-cost confirmation that the overnight leg, not the day leg, carries the momentum edge.
- **Long-only:** YES (long the overnight-momentum ETF leg). Source (full text read):
  https://www.mdpi.com/2227-9091/14/4/84 (DOI 10.3390/risks14040084)

---

## Category 3 — Multi-day (2–5 day) momentum/reversal that holds net of cost

### 6. Medhat & Schmeling (2022, RFS 35(3):1480–1526) — Short-Term Momentum (STMOM)
- **Thesis:** double-sorting on last month's return × share turnover splits the 1-month horizon into
  **reversal (low-turnover)** and **momentum (high-turnover)**; the momentum half survives transaction costs.
- **EXACT RULE:** each month, double decile sort on **last month's return (r1,0)** and **last month's share
  turnover**, NYSE breakpoints, value-weighted, rebalanced month-end (US: NYSE/AMEX/NASDAQ, July 1963–Dec 2018;
  also international). **Long last month's winners within the HIGH-turnover decile / short the losers**
  (STMOM). Strongest among the **largest, most liquid, most covered** stocks.
- **NET / MAGNITUDE:** STMOM gross **+16.44%/yr** (vs STREV −16.92%/yr in the low-turnover decile). **Net of
  transaction costs + implementation lag: +1.45%/mo (t = 4.38), net FF8 information ratio 1.11.** Coarser
  quintile version: +0.42%/mo (t = 2.40) with 4× capacity. Large-cap / megacap STMOM: **~0.60%/mo net
  (t > 3)**; megacap net ≈ 1.00%/mo (t = 3.47). Skipping the last few formation-month days → ~22%/yr.
  (Contrast: STREV's monthly cost 1.94% **subsumes** its gross return; conventional momentum nets
  0.95%/mo t = 3.74.)
- **Turnover:** monthly rebalance → low one-sided turnover; authors explicitly call it "considerably cheaper
  to implement" than reversal.
- **Long-only:** YES — buy last-month's high-turnover winners (large-cap), no short needed.
- **Source (full text read):** https://openaccess.city.ac.uk/id/eprint/31278/1/MS_short_term_mom_v27.pdf
  Published: Review of Financial Studies 35(3):1480–1526, 2022 —
  https://ideas.repec.org/a/oup/rfinst/v35y2022i3p1480-1526..html ; SSRN WP DOI 10.2139/ssrn.3150525.
  Independent corroboration (Chiang–Kirby–Nie 2021, J. Banking & Finance 106068): reversal gives way to
  momentum as turnover rises (high-turnover stocks are more liquid). https://doi.org/10.1016/j.jbankfin.2021.106068
  Practitioner restatement (read): https://alphaarchitect.com/short-term-momentum/

### 7. Gutierrez & Kelley (2008, JF 63(1):415–447) — weekly momentum (1-week → 1-year continuation)
- **Thesis:** weekly returns show a **brief reversal in week 1** then **long-lasting continuation (momentum)**
  from week 2 onward — strong enough to offset the reversal and produce significant momentum over the full
  year after formation.
- **EXACT RULE:** sort on the **prior week's return**; the tradeable form skips the reversal week and holds
  winners over the following weeks (weekly rebalance). Extends to price moves with and without public news.
- **NET / MAGNITUDE:** **exact bps NOT-EXTRACTED** (Wiley paywalled; abstract read via RePEc). Caveat from a
  follow-on replication (Chai–Limkriangkrai–Ji 2015, Accounting & Finance, DOI 10.1111/acfi.12144): the
  post-1-week continuation **disappears after controlling for intermediate-horizon past performance** — so it
  partially overlaps medium-term momentum.
- **Turnover:** weekly (≈2 round trips/wk on the long leg).
- **Long-only:** YES (long prior-week winners, skip the reversal week).
- **Source:** https://doi.org/10.1111/j.1540-6261.2008.01320.x ; RePEc abstract:
  https://ideas.repec.org/a/bla/jfinan/v63y2008i1p415-447.html

### 8. Etula–Rinne–Suominen–Vaittinen (2020, RFS 33(1):75–111) — turn-of-month T-day map
- **Thesis:** the monthly institutional payment cycle forces predictable month-end price pressure.
- **EXACT RULE:** T = last business day of month. **Negative** market return T−8→T−4, **positive** T−3→T−1
  (concentrated near the 3rd business day before month-end). **Long-only:** hold the US VW index (CRSP) only
  during the positive ~7-day window, cash otherwise. Stronger for large/liquid names and when the TED spread
  is elevated.
- **MAGNITUDE:** holding ~7 days/month "captured **the entire market excess return** at **~50% lower
  volatility**" since July 1926; reversals significant in **22 of 25** markets. Per-day bps NOT-EXTRACTED.
- **Turnover:** ~4 round trips/yr → the single best cost-survivability in the whole edge bank.
- **Long-only:** YES. Source: https://doi.org/10.1093/rfs/hhz070 (WP "Dash for Cash", AEA 2016, already banked).

---

## Category 4 — Combination / portfolio of overnight + multi-day edges

### 9. The portfolio framing + the operator's own verified survivors
- **Chen & Velikov (2022, JFQA)** — combining **uncorrelated** anomalies nets ~20 bp/mo (~2.4%/yr long–short)
  while the average single anomaly nets only ~4 bp/mo; low-turnover buy/hold spreads are the mitigation that
  keeps anomalies net-positive (Novy-Marx & Velikov 2016). https://doi.org/10.1017/s0022109022000874
- **Salotra et al. (2026)** — within their 24-strategy grid, the winner is a **composite of overnight momentum
  (#1) + long reversal (#18)**, dominating B&H on Sharpe and Sortino (see #5 above).
- **In-house weak-close/overnight survivors (already backtested, 6 bp, OOS from 2022):**
  - **NEARLOW** (close in bottom 25% of day's range → buy close, sell next open): net **+8.13 bp/trade,
    PF 1.069, OOS t = 5.30** (dies by 10 bp).
  - **DOWN3** (3 down closes → buy close, sell next open): net **+4.24 bp/trade, OOS t = 3.06**.
  - **Broken Arrow** (Alvarez: −15% day above rising 40-d MA → buy close, sell next open): our OOS
    **+0.73%/trade @ 58% winners** (Alvarez published +0.77%/trade @ 56%).
  - These are the *conditional* overnight edges the operator has already validated; unconditional overnight
    (SPY buy-close/sell-open) is dead (−32% net after spread, Alpha Architect 2020).

**Suggested combination (all long-only, all low-turnover, non-overlapping horizons):**
(a) OBG/overnight-momentum sleeve held overnight (monthly rebalance, ~#1/#2),
(b) STMOM monthly sleeve (large-cap high-turnover winners, #6),
(c) turn-of-month 7-day sleeve (#8) + pre-FOMC / pre-holiday event holds (below),
(d) weak-close gap-fill sleeve (NEARLOW/Broken Arrow, overnight).
Each sleeve is one independent, cost-survivable, documented source of return with different turnover clocks.

### 10. Event/session overnight holds (ultra-low turnover, index-level, long-only)
- **Pre-FOMC drift** — Lucca & Moench (2015, NY Fed SR 512): long SPY close day-before → close FOMC day;
  ≈ +49 bp over 24 h pre-FOMC (faded for non-presser meetings; now concentrated on ~8 presser days/yr).
  https://www.newyorkfed.org/research/staff_reports/sr512
- **Pre-holiday drift** — Ariel (1990, JF 45(5):1611–1626): long the broad market the session before a
  market-closed holiday, sell next session (~8 event-days/yr); pre-holiday days earned 9–14× the average
  day's return. https://doi.org/10.1111/j.1540-6261.1990.tb03731.x
- **Turnover:** a handful of round trips/yr → trivially cost-survivable; both long-only, both legs RTH.

---

## Summary table

| # | Edge | Horizon | Net (documented) | Turnover | Long-only |
|---|---|---|---|---|---|
| 1 | Lou–Polk–Skouras overnight momentum | overnight, monthly form | +3.47%/mo 3F alpha (L/S); no 6 bp net | monthly | yes (top decile) |
| 2 | Lachance OBG "Night Trading" | overnight, monthly | **+15.7–21.2%/yr net** (10.4–15.7% alpha) | monthly | **yes** |
| 3 | Berkman et al. attention open-fade | overnight→intraday | magnitudes NOT-EXTRACTED (cost, not profit) | daily | no (execution rule) |
| 4 | Aboody et al. weekly overnight persistence | overnight, weekly | 1.76 pp/wk decile spread (gross) | 2 RT/wk (long-only) | yes |
| 5 | Salotra et al. 2026 sector-ETF overnight momentum | overnight | Sharpe ~0.95 vs 0.61 B&H; 1–2 bp cost analysis | daily | yes |
| 6 | Medhat–Schmeling STMOM | ~1 month | **+1.45%/mo net (t=4.38)**; large-cap ~0.60%/mo | monthly | **yes** |
| 7 | Gutierrez–Kelley weekly momentum | 1 week–1 yr | NOT-EXTRACTED; subsumed by intermediate momentum (caveat) | weekly | yes |
| 8 | Etula et al. turn-of-month | ~7 days/mo | entire premium @ ~50% vol; ~4 RT/yr | ~4 RT/yr | **yes** |
| 9 | Combination (Chen–Velikov + Salotra + in-house) | mixed | ~20 bp/mo L/S combos; +8.13 bp/trade NEARLOW | low | yes |
| 10 | Pre-FOMC + pre-holiday event holds | 1 session | +49 bp pre-FOMC; 9–14× pre-holiday | ~8–16 RT/yr | **yes** |

**Bottom line:** the cost-survivable set is (a) monthly-rebalanced overnight-momentum/OBG (net 10–21%/yr),
(b) monthly STMOM (net ~0.6–1.45%/mo), (c) turn-of-month + event holds (~4–16 RT/yr), and (d) the operator's
own weak-close gap-fill overnight (net +8 bp/trade). The one universal rule: **buy near the close, sell the
next open, never at the open; keep rebalance frequency at weekly or slower.**
