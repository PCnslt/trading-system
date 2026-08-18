# Systemd Services (forward-test bots)

The forward-test bots run as **persistent systemd services** (not Hermes cron),
so forward-testing survives Hermes gateway restarts and is visible to
`systemctl is-active` + `ps`. Every unit is **PAPER ONLY** — the execution
mode is pinned in the unit and no live switch is ever flipped.

## Services

| Unit | Bot | Schedule | clientId | Mode |
|---|---|---|---|---|
| `live-index.service` | `bot/live.py` (MES/MNQ Donchian + RSI2) | daily 19:00 ET | 70 | PAPER |
| `live-gold.service` | `bot/live_gc.py` (MGC Donchian + TSMOM) | daily 19:10 ET | 78 | PAPER |
| `live-vwap.service` | `bot/live_vwap.py` (VWAP sleeve MES/MNQ) | every 15 min, RTH 09:30–16:00 ET | 79 | PAPER |
| `live-equities.service` | `bot/live_equities.py` (RH RSI2 signal + sim fills) | daily 19:20 ET | — (no IBKR) | PAPER |
| `orderbook-collector.service` | `bot/orderbook_collector.py` (L1 depth) | continuous, RTH-gated | 80 | read-only |

## Wrapper — `infra/bot_loop.py`

The four one-shot daily/intraday bots (`live.py`, `live_gc.py`, `live_vwap.py`,
`live_equities.py`) are single-pass entrypoints, not event loops. Each is run
under `infra/bot_loop.py` so the service stays `active (running)`:

- run the command **once on start** (first cycle produces fresh data), then
- sleep to the next occurrence (`--daily HH:MM` or `--interval N [--rth-only]`,
  America/New_York).

`orderbook_collector.py` already loops internally (no wrapper).

## PAPER-ONLY invariants

- `LIVE=false` pinned on every IBKR bot; `VWAP_EXECUTION=PAPER`;
  `RH_EXECUTION_MODE=PAPER` + `RH_LIVE_ENABLED=false`.
- All IBKR bots hit port 4002 (paper DUR193467); `account_mode_ok` refuses
  orders on a paper/live mismatch.
- `orderbook-collector`: `RH_ENABLED=false` (no Robinhood connection),
  IBKR `readonly=True`.
- Every entry rests a native-bracket protective stop; `submit_entry`
  rejects `stop <= 0` (never naked).

## Logs

`logs/<unit>.log` (append, via `StandardOutput`/`StandardError`).

## Scheduling ownership

Replaces the Hermes cron jobs that formerly fired these bots (paused
2026-08-18 to avoid double-fire):

- "Paper signals — index futures" → `live-index.service`
- "Paper execution — gold momentum" → `live-gold.service`
- "Paper signals — Robinhood equities RSI2" → `live-equities.service`

Still on Hermes cron (unchanged): the equity SIGNAL lane (`equity_signals.py`),
intraday MES (`live_intraday.py`), crypto lanes, and all monitor/watchdog jobs.
