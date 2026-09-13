# Crypto NEWS / SENTIMENT / EVENT edge research — ranked candidates

Date: 2026-09-09. Subagent pass. Serper out of credits → fallback ladder used (NewsAPI, OpenAlex, arXiv, Crossref, Semantic Scholar, jina.ai, DuckDuckGo). All citations are papers actually fetched (title/abstract/PDF text); magnitudes that live only in paywalled tables are marked NOT-EXTRACTED.

## Cost baseline (used throughout)
- Crypto SPOT taker round-trip ≈ **10 bps** (Binance.US, ~5 bp/side — per repo crypto-lane sweep) to **20 bps** (Binance global 0.1%/side). BTC/ETH deep books: realistic all-in **10–20 bp round trip**.
- Perp taker is similar (~5 bp/side taker, but funding is a separate cost/carry, not a spread).
- Retail execution horizon for EVENT news is minutes-to-hours, not seconds; sub-hour effects are structurally sub-cost for this system.

## Overarching finding (frames every candidate)
**Sentiment/news predicts crypto VOLATILITY, not signed DIRECTION — and directional daily predictability does not robustly survive costs.**
- JEDC 2020 (doi 10.1016/j.jedc.2020.103980, cited 139): BTC volatility/jump component reacts to regulation news, positive-sentiment Google searches, and *most notably* exchange-hack news; "bitcoin is NOT influenced by most scheduled US macro announcements."
- arXiv 2606.00071 (2026 survey, Baquero et al.): *"At short-to-medium horizons, no peer-reviewed study has shown robust superiority over the naive baseline across multiple market regimes. Daily predictability is real but does not extend to hourly or monthly horizons, and may not survive transaction costs."* Strongest NLP-sentiment case = Gurgul et al. 2025 (BART zero-shot, buy-and-hold baseline, NOT naive — flagged weak by the survey).

---

## CANDIDATE 1 — Funding-rate EXTREME reversal (contrarian)
**Verdict: NO EVIDENCE (academic). Practitioner folklore, UNVERIFIED.**
- Rules (folklore): short when perp funding rate is extreme positive (crowded longs), long when extreme negative (crowded shorts); 8h/1h funding intervals; hold to mean-reversion of funding.
- Evidence FOR: abundant qualitative blogs ("extreme funding readings are one of the more reliable contrarian signals in crypto futures, though never a perfect signal" — DDG result #1). No backtested magnitude/significance in ANY of them.
- Evidence AGAINST: the only academic-adjacent source on funding↔price is a weak preprint (arXiv 1912.03270, 2019, Nimmagadda & Sasanka) that finds Granger-causality implying *continuation* ("extremely high funding rates would causate high prices"), NOT reversal — and reports no significance. "Fundamentals of Perpetual Futures" (arXiv 2212.06888) is a *market-neutral basis arbitrage* (BTC SR 1.62, 2020–24) that REQUIRES shorting; not directional.
- Economic read: funding rate is a crowding/momentum proxy. Crypto momentum is already falsified as beta (repo: shuffled-placebo +160bp ≈ real +163bp). A contrarian-funding claim is a *mean-reversion* claim, and crypto daily mean-reverts with NEGATIVE alpha for long-only (repo: momentum t=−2.2 to −6.4).
- Cost prior: if a reversal effect existed at, say, +15 bp/trade, it sits right at the 10–20 bp round-trip wall → structurally marginal. No published magnitude to compute against.
- **Actionable**: funding-rate history is cheaply backfillable (Binance klines + funding endpoint). This is the single best *forward-test* candidate — but it is an UNTESTED hypothesis, not a verified edge.

## CANDIDATE 2 — Liquidation-cascade BOUNCE (buy the flush)
**Verdict: EVIDENCE OF NO EDGE (long-only).**
- Rules (folklore): after a large forced-liquidation cascade (big negative candle + spike in liquidations), buy the overshoot and ride the bounce.
- Evidence AGAINST (in-house, repo `crypto-momentum-beta-2026.md`): extreme −4% 1h candle → next 4h = **−49.8 bp CONTINUATION** (short-only falling knife, n=45), i.e. crypto mean-reverts in the *long* tail but the immediate post-crash move is continuation, not bounce.
- Academic literature: thin. BitMEX liquidation mechanics described (Towards Understanding BitMEX, 2021) with no directional-edge quantification; "herding/feedback trading" (Annals OR 2021) documents feedback but no tradeable edge.
- Cost prior: an intraday bounce with a 10–20 bp round trip needs a >10–20 bp directional edge in 4h; the observed move is −50 bp *against* the long. Long-only bounce is negative before cost.
- **Actionable**: only a SHORT-side "falling knife continuation" would have captured the −49.8 bp, and shorting is unavailable to a long-only spot account.

## CANDIDATE 3 — Post-announcement drift on major headlines (news underreaction)
**Verdict: INSUFFICIENT DATA.**
- Source: Hashemi Joo, Nishikawa, Dandapani (2020, Applied Economics, cited 65). DOI 10.1080/00036846.2020.1745747.
- Rules: BTC/ETH/XRP major news events; abnormal return on Day 0; CARs continue to *diverge* through (+6) — "information is not fully reflected immediately… information flow in the cryptocurrency market is visibly slow"; negative events produce LARGER CARs than positive; authors explicitly claim "trading opportunities for investors who initiate a trading position even AFTER announcements."
- Magnitude/sample/significance: CAR table values NOT-EXTRACTED (Taylor & Francis paywall; abstract-only). Sample is BTC/ETH/XRP, era ~2015–2018.
- Cost prior: 6-day hold ≈ 2–3 bp/day amortized round-trip — structurally cost-safe *if* the drift is real. But the drift's sign is contested (see Candidate 4) and there is NO independent replication.
- **Actionable**: needs the paper's CAR table (magnitude + t-stats) before any backtest; flagged as the single highest-value paywalled fetch to complete.

## CANDIDATE 4 — "Trade the news-sentiment sign" (positive news → long, negative news → short)
**Verdict: EVIDENCE OF NO EDGE for naive sign-trading on BTC.**
- Source: Rognone, Hyde, Zhang (2020, IRFA, cited 176). DOI 10.1016/j.irfa.2020.101462. Intraday, Jan 2012–Nov 2018.
- Finding: "Bitcoin reacts POSITIVELY to both positive AND negative [unscheduled currency/Bitcoin] news" (enthusiasm effect, stronger in bubbles); only *cyber-attack/hack* and *fraud* news are negative (they dampen returns AND volatility).
- Implication: for BTC, generic news sentiment has the WRONG sign relationship for a naive sentiment-direction strategy — you cannot "short bad news" profitably; you'd be buying enthusiasm on any news. The only directional fragment is hack/fraud → negative (a SHORT signal, unavailable).
- Cost prior: intraday event reaction; sub-day holds at 10–20 bp RT need a >10–20 bp signed move, and the signed move is attention-driven, not sentiment-driven.

## CANDIDATE 5 — Twitter/social sentiment → direction (the flagship sentiment claim)
**Verdict: INSUFFICIENT DATA (statistical predictability ≠ net tradeable edge).**
- Two sources:
  - Garcia & Schweitzer (2015, Royal Society Open Science 2:150288) — the classic. Rules: daily BTC prediction from Twitter valence, polarization + FX exchange volume; four strategies (Valence/Polarization/FXVolume/Combined voting), act next day. Results (their Table 1): Combined **Sharpe 1.7653 annualized, mean daily +0.3229% (+32 bp/day)**; Polarization SR 1.01 (+0.18%/day); Valence SR 0.64 (+0.12%/day); Buy&Hold SR −0.77 (negative — drawdown regime); Random-trader SR −1.66. Cost: "for costs above 0.25% [25 bp/trade] the strategy is no longer profitable." Sample: 2011–2014 analysis, 2014-01→2015-01 backtest.
  - Kraaijeveld & De Smedt (2020, JIFMIM, cited 429). DOI 10.1016/j.intfin.2020.101188. Lexicon sentiment + Granger causality: Twitter sentiment predicts returns of BTC/BCH/LTC (EOS/TRON via bullishness ratio). No backtested net-of-cost strategy; 1–14% of tweets are bots.
- Cost prior: Garcia-Schweitzer's +32 bp/day gross vs their 25 bp/trade ceiling means it cleared a 10–20 bp round trip *in 2014*. But: daily full-turnover, single (2014 bubble/drawdown) regime, pre-institutional market, published 11 years ago, sentiment lexicons now commoditized, and NO modern (post-2015) replication exists.
- **Actionable**: treat as the strongest *historical* evidence that social sentiment once carried directional alpha on BTC; the honest read is it has likely decayed and is unreplicated.

## CANDIDATE 6 — ETF approval event study (regulatory/flow headline)
**Verdict: INSUFFICIENT DATA (one-off, non-repeatable).**
- Source: Borsa Istanbul Review 2025 (doi 10.1016/j.bir.2025.10.002, cited 1, OA). Intraday event study.
- Finding: US spot-BTC ETF approval → significant positive abnormal return + volatility spike; ETH ETF approval → modest effects.
- Sample: essentially n = 1 (BTC) + 1 (ETH) approval event each. Not a standing rule; and reality notes BTC fell after the Jan-2024 approval ("sell the news") — the "buy the approval" trade is already gone.
- Cost prior: N/A (event already past; no repeatable cadence).

## CANDIDATE 7 — Infrastructure-vs-regulatory event asymmetry (the "which headlines move price" question)
**Verdict: EVIDENCE OF NO EDGE (author self-retraction).**
- Source: Farzulla (arXiv 2602.07046, 2026). 50 events, 6 assets, Jan 2019–Aug 2025, GJR-GARCH-X under dependence-robust inference.
- Finding: infrastructure CARs −0.23% vs regulatory CARs −7.42% = +7.19 pp difference; block-bootstrap **p = 0.283**, 95% CI [−5.97%, +20.48%] crosses zero. The author states his own prior "significant fivefold effect… was an inference artefact."
- Implication: even the cleanest event-type split (infra vs regulatory) does not survive correct inference on a heavy-tailed 50-event sample. This is the strongest single piece of evidence that naive headline-direction trading is null.

## CANDIDATE 8 — Whale-transfer / Tether-mint intraday reaction
**Verdict: INSUFFICIENT DATA (real effect, sub-retail horizon).**
- Source: Saggu (2022, FRL, cited 29). DOI 10.1016/j.frl.2022.103096. 2014–2021.
- Finding: "Bitcoin responds POSITIVELY to USDT minting events over 5–30 min windows, declining after 60 min; larger when minting coincides with positive sentiment and a Whale Alert tweet."
- Magnitude: NOT-EXTRACTED (paywalled). 5–30 min reaction window.
- Cost prior: a 5–30 min effect is below retail execution (10–20 bp round trip + news latency). Even a large bp move is un-capturable without sub-minute HFT. Whale-alert tweets are already-public info by the time they can be acted on.

---

## Ranked shortlist (by "worth a backtest slot today")
1. **Funding-rate extreme reversal** — cheapest to test (funding history is backfillable), folklore-hyped, zero rigorous evidence. *Test, don't trust.*
2. **Post-announcement drift (Candidate 3)** — completes with one paywalled CAR table; structurally cost-safe if real; sign is contested (Candidate 4).
3. **Hack/fraud news → negative BTC** (fragment of Candidate 4) — the only clean directional news signal in the literature, but SHORT-side → unavailable long-only.

## Hard rules honored
- Every number has a real citation (DOI/arXiv id) fetched this session; no fabrication.
- Paywalled table magnitudes (Hashemi Joo CARs; Saggu 5–30min bp; Gurgul exact Sharpe) marked NOT-EXTRACTED.
- Four-way verdicts used; "no tested strategy survived" never written as "no edge exists" — the news channel's best-documented effects are VOLATILITY-side and/or sub-cost, while DIRECTIONAL claims are either null (Candidate 7), sign-contested (Candidate 4), unreplicated/decayed (Candidate 5), or folklore (Candidates 1–2).
