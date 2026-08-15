# Data Engine — a decoupled market-data collection project

> ⛔ **PAUSED 2026-08-15** — US equities collection **pivoted to IBKR** (owner
> directive "IBKR is the source, stop yfinance for broker-available assets").
> The 5 data-engine cron jobs are commented out of the live crontab. The code +
> `crontab.txt` are KEPT for optionality. The **universe** + **liquid-rank**
> modules are still used (by `data/ibkr_full_backfill.py`) to pick the ~6.9k
> common-stock + ~1k liquid symbol lists — but the **bars** now come from IBKR
> (`S3 ibkr/equities/*`, 20y+ daily + 1-min), not yfinance. Re-enable by
> un-commenting the jobs and `crontab data_engine/crontab.txt`.

A **separate, self-contained** data-collection engine for US equities, built to be
**splittable into its own repo later with zero surgery**. It shares only the S3
bucket with the trading system; it does not import from `bot/`, `data/`, or
`hardening/`, and it never touches IBKR, DynamoDB trading state, or clientIds.

- **Source:** yfinance (unofficial, free, no SLA) + Nasdaq Trader listings (free).
- **Scope:** US equities only — daily (full universe) + intraday 1h/1m (liquid subset).
- **Read-only on trading:** no orders, no clientId, no `CONTROL`/`SIGNAL`/`RUN#` writes.
- **Serialize:** own lockfiles (`data_engine/state/*.lock`) so engine runs never
  overlap each other; and the engine never collides with the trading bots by construction.

---

## 1. Package layout (`data_engine/`)

| File | Role |
|---|---|
| `registry.json` | **Single source of truth**: prefixes, intervals, depth, universe source, liquid method, pacing, schedule. |
| `config.py` | Loads the registry + env (`S3_BUCKET`/`AWS_REGION`); lock helper; local path resolution. |
| `s3store.py` | Minimal S3 get/put/list/exists (own namespace — no `data/s3_archive.py`). |
| `universe.py` | Build the ~7k common-stock universe; liquid ranking by dollar volume. |
| `collect_daily.py` | Daily bars, full universe, idempotent + checkpoint resume. |
| `collect_intraday.py` | 1h + 1m bars, liquid subset. |
| `crontab.txt` | The engine's own schedule (splittable; merged into system crontab under a delimiter). |
| `cache/`, `state/`, `logs/` | Runtime artifacts — **gitignored**. |

Decoupling rule: **nothing in `data_engine/` imports from `data/`, `bot/`, or
`hardening/`.** Dependencies are `boto3`, `yfinance`, `pandas`, `requests`,
`python-dotenv` only.

## 2. The registry (`registry.json`)

One config file drives everything: **prefixes** (S3 key templates), **intervals**
(`1d`, `1h`, `1m`), **depth** (period per interval), **universe** (source + filter
rules), **liquid** (ranking method + target count + seed screeners), **pacing**
(rate-limit + backoff), and **schedule** (cron expressions). Change one of these
in the registry — no code edits — and the collectors follow.

## 3. S3 prefix namespace

Owned by the engine; distinct from the trading system's `yf/<class>/<sym>.json`
and `futures-bars/…`:

| Prefix | Shape | Content |
|---|---|---|
| `yf/stocks/daily/<sym>.json` | one object/symbol | full daily history back to IPO |
| `yf/stocks/intraday/<sym>/<interval>/<date>.json` | one object/date/interval | session bars (`1h`≈2y, `1m`≈8d rolling) |
| `data-engine/universe/us_common_stocks.json` | one object | the common-stock universe snapshot |
| `data-engine/meta/liquid_universe.json` | one object | top-~1k liquid list (dollar-volume rank) |
| `data-engine/meta/daily_manifest.json` | one object | collection progress (complete/total) |

## 4. Universe (full US common stocks)

Built from Nasdaq Trader's free listing files (`nasdaqlisted.txt` +
`otherlisted.txt`), filtered to **common stocks only**: excludes ETFs, test
issues, and preferred/warrant/unit/ADR-class tickers (any `.` `-` `=` `^` `/`
suffix). **Measured 2026-08-15: 6,958 symbols.** Cached to
`data_engine/cache/us_common_stocks.json` + mirrored to S3; refreshed weekly.

## 5. Liquid subset (top ~1,000 by dollar volume)

Two layers, so intraday can start immediately and refine as daily data lands:

1. **Seed** — union of Yahoo predefined screeners (`most_actives`, `day_gainers`,
   `day_losers`, `undervalued_large_caps`, `growth_technology_stocks`, …),
   intersected with the common-stock universe, ranked by
   `avgDailyVolume10d × price`. Available before any bars are collected.
   (Measured: ~985 symbols; `most_shorted` is not a valid query and is skipped.)
2. **Ranked** — top-N by **average dollar volume** (`mean(close × volume)` over the
   last 20 sessions), computed from the daily collector's metrics JSONL
   (`data_engine/cache/daily_metrics.jsonl`) as the daily batch progresses. This is
   the authoritative liquidity ranking; it replaces the seed once enough symbols
   have daily bars.

## 6. Daily collection (`collect_daily.py`)

- Full universe (~6,958), full history (`period='max'`, back to IPO), one JSON
  object per symbol.
- **Idempotent + self-healing:**
  - A checkpoint (`data_engine/state/daily_checkpoint.json`) records each symbol's
    `done`/`lastDate`. Re-runs **skip** completed symbols and **resume** from the
    checkpoint.
  - Failed symbols are left incomplete → retried next run.
  - `--all` re-processes completed symbols with an **incremental merge** (last ~5d
    merged by date), healing recent gaps and catching new bars.
  - `--full` forces a full `period='max'` re-download for deep gap healing.
- **Rate-limit aware:** paced (default 1.2 s/symbol) with exponential backoff on
  429/rate-limit errors; `--limit N` bounds a single run so cron can do steady
  increments. `max_symbols_per_run=0` means "no cap" (continuous batch).

## 7. Intraday collection (`collect_intraday.py`)

- Liquid subset only (top-~1k). Date-partitioned, idempotent writes.
- **Honest measured depth (yfinance 1.6.0, 2026-08-15):**
  - `1h` → `period='730d'` ≈ **2 years** of session bars.
  - `1m` → `period='7d'` = **8 calendar days only**. Yahoo hard-caps 1m at ~8 days
    ("Only 8 days worth of 1m granularity data are allowed"). Requests for 30d/60d
    **fail**. This corrects the earlier assumption of "~30–60d" — treat 1m as a
    rolling ~1-week window, refreshed daily by cron.

## 8. Scheduling (own crontab)

`data_engine/crontab.txt` is the engine's self-contained schedule, merged into the
system crontab under the `# ---- DATA ENGINE ----` delimiter (trading entries are
untouched). It is **data ingestion** → system crontab, per the trading convention
(never Hermes cron, which is bot execution only).

| Cron (UTC) | Job |
|---|---|
| `0 12 * * 0` | universe refresh (weekly) |
| `15 1 * * *` | daily bars — bounded batch `--limit 2000` |
| `0 2 * * *` | liquid ranking (top-1000) |
| `30 2 * * *` | intraday `1h` (liquid subset) |
| `45 2 * * *` | intraday `1m` (liquid subset) |

The bounded daily batch completes the initial ~7k backfill in ~4 days and then
keeps it fresh incrementally.

## 9. Splitting into its own repo (zero surgery)

The whole `data_engine/` directory is portable:
- Self-contained (only `boto3`/`yfinance`/`pandas`/`requests`/`dotenv`).
- Reads AWS/S3 config from `DATA_ENGINE_ENV_FILE` (or a `.env` one dir up) — no
  trading secrets required.
- `crontab.txt` installs standalone with `crontab data_engine/crontab.txt`.
- Own S3 namespace (`yf/stocks/…`, `data-engine/…`) — no dependency on trading keys.

To split: copy `data_engine/` to a new repo, `pip install` the 5 deps, point
`.env` at the same bucket, install the crontab. Nothing else moves.

## 10. Subscription gaps (future-project inventory)

These are **NOT purchased** — recorded here so a future project can buy them if and
only if it actually needs them:

| Gap | Why needed | Tag |
|---|---|---|
| **Tick-level / consolidated-tape US equities data** (every-second) | yfinance gives bars only; "every-second" stock ticks need a paid real-time feed (e.g. consolidated tape / polygon / IQFeed). NOT in the futures subscription. | **Needed only if a future project needs tick-level stock data.** Do NOT buy. |
| yfinance 1m intraday depth | capped at ~8 days; deeper 1m needs a paid intraday archive. | Research-grade only; buy only if a project needs deep 1m. |

`1h`/`daily` free depth is adequate for most research; the gaps above are honest
free-source limits, not silently substituted.
