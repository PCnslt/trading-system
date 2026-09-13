# ANALYST-DISPERSION AVOIDANCE SCREEN — verdict: INSUFFICIENT DATA (not point-in-time testable)

Date: 2026-09-09
Candidate: exclude the top-decile analyst-forecast-dispersion names from the long-only
buy universe (Diether–Malloy–Scherbina 2002 JF: high dispersion -> lower future returns,
strongest in small / prior-loser names).
Screen definition (per task): dispersion = (epsHigh − epsLow) / |epsAvg|, rank names,
drop top decile; apply to RSI2 / REV2 / Broken Arrow.

## Data availability (the decisive step — verified against live endpoints)

The screen needs, for each name at each PAST date t, the dispersion of the analyst EPS
estimates OUTSTANDING AT t (a point-in-time series). That series is NOT retrievable free:

1. **FMP `analyst-estimates` — current snapshot only, confirmed.** The free key's only
   working variant is `stable/analyst-estimates?symbol=X&period=annual`. It returns
   epsHigh/epsLow/epsAvg **keyed by fiscal-period-END date** (e.g. AAPL → 2030-09-27 …
   2021-09-25), with NO as-of/publication timestamp. There is no field saying WHEN each
   consensus was current. You therefore cannot build dispersion(t) for any past t.
   - `period=quarter` → `Premium Query Parameter` (paid tier).
   - The legacy `api/v3/analyst-estimates/{SYM}` (which historically DID return a
     publication-dated estimate history) now returns: *"Legacy Endpoint … only available
     for legacy users who have valid subscriptions prior August 31, 2025."* The whole v3/v4
     API is dead for this key (even `v3/quote` 403s the same way).
2. **AlphaVantage — no dispersion function.** `EARNINGS` gives reported EPS + surprise
   (the PEAD signal), not analyst dispersion. No `ANALYST_DISPERSION`/`ESTIMATE_DISPERSION`
   function exists in the free catalog.
3. **IBES (LSEG/Refinitiv) — the academic standard DMS used — is paywalled** (institutional
   WRDS/Refinitiv subscription). **Zacks** — paywalled. **Estimize** — crowdsourced (not
   IBES-style analyst dispersion) and its free API is discontinued.

=> **The exact data gap:** a free point-in-time historical analyst-estimate-dispersion series
does not exist. FMP offers a current consensus snapshot; the point-in-time (publication-dated)
history lives behind a paid subscription, and the free legacy endpoint that once exposed it
was revoked 2025-08-31.

## Why I did NOT run the backtest

Applying today's dispersion snapshot to 2022–2026 trades would be rank-look-ahead
(fabrication), and the task/skill explicitly forbids that. Without dispersion(t) there is no
honest historical screen to run. The harness is ready and trivially adaptable
(`research/short_interest_screen.py` already carries the RSI2 + Broken Arrow lane generators,
the 524-name universe, S3 bars, 6bp cost, and chronological-OOS discipline) — the blocker is
purely the missing point-in-time input series, not the backtest machinery.

## Prior that lowers the prior expectation of value (not a substitute for the test)

- The closely analogous **short-interest avoidance screen** (same "exclude the top-decile
  heavily-X names" shape, same lanes, same 6bp/OOS harness) already returned **EVIDENCE OF NO
  EDGE** on 2026-09-09: it slightly HURT OOS PF (RSI2 1.069→1.030, Broken Arrow 1.278→1.229)
  because the excluded names were the BEST short-horizon reversal performers (short-covering
  fuel), not the worst. See `references/short-interest-data-and-screen.md`.
- **Horizon mismatch:** DMS dispersion (and the short-interest papers) document a ~1-month
  / 20-day DRIFT anomaly, not a 1–5 day reversal. RSI2/REV2/Broken Arrow are 1–5 day
  reversal holds. The mechanism the screen depends on (a slow negative drift) is not the
  horizon the lanes trade.

## Four-way verdict

**INSUFFICIENT DATA** — cannot resolve. (Not "EVIDENCE OF NO EDGE": the screen was never
run because its input is unobtainable free. Not "NO EVIDENCE": there is no free data even to
produce a weak signal. Not "ACTUAL EDGE".) The only path to a real test is a paid
point-in-time estimate history (IBES/Refinitiv via WRDS, or an FMP legacy/paid plan that
still exposes the publication-dated `analyst-estimates` series); at that point the harness
in `short_interest_screen.py` can be re-pointed at a dispersion column in ~1 hour.

## Secondary candidate — 13F institutional-ownership accumulation (feasibility note)

Feasible to BUILD and point-in-time-correct, but a poor fit for these lanes. SEC 13F is free
on EDGAR (institutional managers >$100M file quarterly, within 45 days of quarter-end), so a
point-in-time accumulation series (quarter-over-quarter change in number of holders / shares
held, lagged 45 days) is reconstructable at no data cost. Two structural problems: (1)
**coverage** — 13F only lists long positions in 13F securities, and small/sub-$50 names are
sparsely held by filers, so most of the 524-name universe will have empty/missing 13F data;
(2) **horizon** — a quarterly, 45-day-lagged accumulation signal is a slow quality/momentum
overlay, not a 1–5 day reversal timer, so it would act as a coarse universe tilt (avoid
institutions-dumping names) rather than a trade-timing screen, and the same
"avoidance screens remove the best reversion names" prior applies. Verdict on 13F as a
secondary candidate: buildable on free data but low expected value for the RSI2/REV2/Broken
Arrow reversal family specifically; it is better suited to a monthly-hold momentum/quality
lane. Secondary tier, do not prioritize over validating live sleeves.
