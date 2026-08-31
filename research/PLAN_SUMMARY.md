# Trading System — Full Research Summary & Plan
**For independent verification. Every claim below is the measured result, with the source of truth.**

---

## 1. What we tested, and the results

### A. Same-day / intraday strategies — ALL DEAD (honest cost, real data)
| strategy | result | note |
|---|---|---|
| RSI2/RSI14 mean-reversion | OOS PF 0.75–0.92, t −1.66 | after fixing survivorship bias + date-clustered t-stat |
| ORB / momentum breakout | negative net | — |
| Gap-and-go flat-by-close | dies at honest cost | only survives overnight (next-open) |
| Market Intraday Momentum (Gao 2018) | decayed to ~0 | post-publication decay |
| VWAP reversion | +3.1bp OOS (marginal) | dies at 8bp cost |
| Scalping | impossible | cost 6–12bp > scalp profit 1–5bp; no L2/tick; multi-second latency |

### B. What SURVIVES (positive, honest)
- **Short-Term Momentum (STMOM, 20-day hold, monthly):** OOS PF 1.55, +232bp, t +1.86. SLOW — insignificant at 2 days (t +1.27), significant at 10 days (t +3.08).
- **Overnight momentum (close→next-open):** marginal +4.4bp, PF 1.08.
- **PEAD (post-earnings-announcement drift):** preliminary positive — surprise quintile +3.7%→+5.9% over 20d. Full backtest pending (data collection).

### C. Options (latest)
- **Buying 0–1 DTE options = NEGATIVE EV.** Vol risk premium (IV > RV 2–4pts, 83–87% of windows); theta (59% decayed by 3pm); lottery options −10% to −50%/week.
- **The playbook's "trailing stop" is FALSE** — RH options have no trailing stop (only market/limit/stop-limit/stop-market).
- **The edge is on the SELLING side** (collecting the vol risk premium — Bakshi-Kapadia 2003, Coval-Shumway 2001).
- **BUT the structural wall:** RH Level 3 (spreads/condors/butterflies/calendars) = **margin-only ($2,000 min)**. At $700 cash, blocked.
- **Only reachable positive-EV structure at $700 RH:** cash-secured puts (and covered calls/wheel) on sub-$7 underlyings — thin, spread-fragile.

## 2. The meta-conclusion

**Edge strength is inversely proportional to trade frequency.** The market pays you for holding LONGER, not trading MORE:
- Same-day → dead (measured, ~15 strategies)
- Overnight → marginal
- 20-day momentum / quarterly earnings drift → the real edges

## 3. Current system state
- Account: **flat (~$700 cash), no positions.**
- Infrastructure built: 5-min monitoring, Market Light regime filter, free-RSS news layer, kill-switch + external dead-man's switch, cross-position correlation guard, vol-scaled sizing, per-second trailing-stop monitor.
- Paper forward-tests: STMOM (14-day settle), gap-and-go, RSI14, Broken Arrow.
- Data: IBKR daily + 1-min bars (free), AlphaVantage earnings surprise (collecting, 25/day).

## 4. The plan (before any real money)
1. **Backtest cash-secured puts** — the only positive-EV option structure reachable at $700 RH. Free data, honest cost, tail-risk-aware.
2. **Complete PEAD full backtest** (data cache fills ~Tuesday).
3. **Forward-test** STMOM (running) + CSP + PEAD on paper.
4. **Commit real money only after:** honest backtest (survivorship-aware, honest cost, date-clustered t-stat) → positive paper forward-test → then live.

## 5. Key sources (verification anchors)
- Bakshi & Kapadia 2003 (RFS) — negative vol risk premium (sellers collect it)
- Coval & Shumway 2001 (JF) — negative expected option returns
- Medhat & Schmeling 2022 (RFS) — short-term momentum
- Bernard & Thomas 1989 — PEAD
- McLean & Pontiff 2016 — post-publication decay (58%)
- Lou, Polk & Skouras 2019 (JFE) — overnight returns
- Israelov & Nielsen 2015 (FAJ) — covered calls = short-vol overlay, not free lunch
- Robinhood Options Knowledge Center — Level 2/3 approval scheme (Level 3 = margin-only)
