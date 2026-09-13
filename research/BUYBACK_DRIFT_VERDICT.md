# Buyback Announcement Drift — Backtest Verdict (2026-09-09)

## Question
Long-only testable form: buy a liquid name on its buyback ANNOUNCEMENT, hold
+20 trading days. Documented: Ikenberry-Lakonishok-Vermaelen 1995 JF (+12.1%
long-run abnormal, 4y hold, 1980–90 sample); Peyer-Vermaelen 2009 RFS
(~+2.4%/month for VALUE firms, 1991–2001 sample). Is the effect still present
at a 1-month hold in the post-publication sample?

## Source + coverage (stated honestly)
- **Events:** SEC EDGAR full-text search (`efts.sec.gov/LATEST/search-index`),
  query `"repurchase program" AND "authorized"`, form `8-K`, per-year 2006–2026
  (chunked to stay under the 10,000-hit cap), fully paginated → **53,596 hits**.
- **Announcement definition (primary):** 8-K whose full text matches the query
  AND filed under Item **8.01 or 7.01** (press-release / Reg FD) AND **not**
  2.02 (earnings) and not 1.01 (material agreement / ASR). This isolates
  event-disclosure 8-Ks announcing an authorization from routine earnings
  progress reports. → **6,508 events** across 1,709 tickers (after
  ticker/date dedupe + 10-day same-program dedupe).
- **Bars:** S3 `ibkr/equities/daily/*.parquet`, 6,551-name current universe
  (survivorship-biased), close prices only (open field is degraded). 6,338
  events joined to a +20d forward return.
- **Liquidity:** ranked by avg 252-day dollar volume; "liquid" = top-500
  (≈ S&P 500 scale), also tested ≥ $20M/day.
- **Market adjustment:** equal-weight daily return of the top-500 liquid tier.
- **Cost:** 6bp round-trip (long-only), subtracted from each trade.

## Result (announcement-day close → +20 trading days, net of 6bp, market-adj)

| Tier | n | net mean | median | win% | PF | t (date-clust) |
|---|---|---|---|---|---|---|
| ALL events | 6,338 | +8.0bp | −29.4bp | 48.2% | 1.022 | +0.62 |
| **LIQUID (top-500)** | 2,079 | **−39.8bp** | −49.5bp | 46.7% | **0.878** | **−1.94** |
| Liquid ≥ $20M/day | 2,699 | −37.1bp | −56.1bp | 46.7% | 0.886 | −2.22 |
| non-liquid (ex top-500) | 4,259 | +31.3bp | −15.8bp | 49.0% | 1.084 | +1.57 |

**Chronological OOS (liquid top-500, last 40% of entry dates, 2019-01→2026-08):**
net −35.5bp, PF **0.905**, win 47.1%, t(date-clust) −0.92. IS (first 60%):
−42.7bp, PF 0.856, t −1.83.

## Robustness
- Consistent across all 4 item filters (primary / 8.01 / 8.01-ex-2.02 / all):
  liquid net mean ranges −0.4bp … −41bp, PF 0.88 … 1.00, never positive.
- Per-year (liquid): positive only in 2006 (+317bp, n=33), 2011, 2021, 2022;
  negative in 13 of 21 years. No stable positive drift.
- The only positive MEAN is in non-liquid micro-caps (+31bp) — but its MEDIAN
  is −15.8bp and t=+1.57 (insignificant); it is carried by a handful of extreme
  winners (XTIA +152%, RCMT +139%, LASE +117%, CAR +121%, …). This is the
  documented effect's small/value tail, i.e. liquidity compensation a small
  account can't harvest — and it is not significant anyway.
- Gross (unadjusted) liquid return is +90bp/20d — but the equal-weight market
  returned +123bp over the same windows, so the market-adjusted drift is
  NEGATIVE. The +90bp is beta, not buyback alpha.

## Verdict — EVIDENCE OF NO EDGE (long-only, 1-month hold, liquid names)
- Net market-adjusted return is **negative** (−40bp, PF 0.88, date-clustered
  t ≈ −1.9) and OOS PF 0.91 < 1.2. Fail the accept bar on every measure.
- The documented +2.4%/month (Peyer-Vermaelen, value firms, 1991–2001) and
  +12.1% long-run (Ikenberry, 4y, 1980–90) do **not** reproduce at a 1-month
  hold on liquid names in 2006–2026. The effect is **decayed to zero or
  inverted** post-publication, consistent with arbitrage erosion and with the
  effect being a long-run (multi-year) + value/small phenomenon, not a 1-month
  liquid-name drift.

## Caveats
- Survivorship-biased current universe (no delisting returns) → upper bound;
  the true effect is at most what's shown (already negative for liquid).
- Entry at close of announcement day is the OPTIMISTIC convention (if filed
  after hours the true entry is next-day close); the result is still negative,
  so the "no edge" conclusion is safe.
- Point-in-time universe and value-factor conditioning not applied; the value
  tilt is exactly where the literature says the effect lives, so a value-only
  variant is the only untested residual (out of scope for "buy a liquid name").

## Artifacts
- `research/buyback_collect_fts.py` — FTS collector (→ /tmp/buyback_fts_hits.jsonl).
- `research/buyback_drift_backtest.py` — main event study.
- `research/buyback_robustness.py` — filter/liquidity sweep.
- `research/buyback_outlier_diag.py` — outlier + winsorization diagnostic.
- `/tmp/buyback_results.parquet` — per-event results (6,338 rows).
