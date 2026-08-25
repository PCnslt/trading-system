# Systemd Services (forward-test bots)

The forward-test bots run as **persistent systemd services** (not Hermes cron),
so forward-testing survives Hermes gateway restarts and is visible to
`systemctl is-active` + `ps`.

> ⚠️ **THIS IS NO LONGER A PAPER-ONLY SYSTEM.** Two units trade REAL MONEY.
> The previous version of this file claimed "Every unit is PAPER ONLY … no live
> switch is ever flipped", which was false from 2026-08-20 (Robinhood) and
> 2026-08-24 (IBKR). Verify mode with
> `systemctl show <unit> -p Environment` before believing any table below.

## Services (verified against systemd 2026-08-24)

| Unit | Bot | Schedule | Broker / port | Mode |
|---|---|---|---|---|
| `live-equities.service` | `bot/live_equities.py` (RSI2 dip-buyer) | daily **09:32 ET** (was 19:20; after-hours market orders could not fill) | Robinhood 515821577 | **🔴 LIVE** (`RH_EXECUTION_MODE=LIVE`, `RH_LIVE_ENABLED=true`, 5 pos, $50/day cap, `RH_MAX_POS_PCT=0.15`) |
| `live-equities-ibkr.service` | `bot/live_equities_ibkr.py` (RSI2, whole-share) | daily 09:30 ET | IBKR **U26949861 / 4001** | **🔴 LIVE** (`IBEQ_EXECUTION_MODE=LIVE`, 2 pos, $25/day cap, $150 min notional) |
| `live-index.service` | `bot/live.py` (MES/MNQ/MYM Donchian + RSI2 + REV2) | daily 19:00 ET | IBKR paper 4002 | PAPER — **STOPPED** (paper gateway disabled; one username can't hold 2 sessions) |
| `live-gold.service` | `bot/live_gc.py` (MGC Donchian + TSMOM) | daily 19:10 ET | IBKR paper 4002 | PAPER — **STOPPED** (same) |
| `live-vwap.service` | `bot/live_vwap.py` (VWAP sleeve MES/MNQ) | every 15 min RTH | IBKR paper 4002 | PAPER — **STOPPED** (same) |
| `reconcile-daemon.service` | `bot/reconcile_daemon.py` | continuous 45s | IBKR **4001** (drop-in; follows the account holding risk) | verification |
| `ibgateway-live.service` | IBC live gateway | continuous | IBKR live 4001, display :100 | **ACTIVE** |
| `ibgateway.service` | native paper gateway | continuous | IBKR paper 4002 | **DISABLED** |
| `orderbook-collector.service` | `bot/orderbook_collector.py` (L1 depth) | continuous, RTH-gated | IBKR | read-only |

## Wrapper — `infra/bot_loop.py`

The four one-shot daily/intraday bots (`live.py`, `live_gc.py`, `live_vwap.py`,
`live_equities.py`) are single-pass entrypoints, not event loops. Each is run
under `infra/bot_loop.py` so the service stays `active (running)`:

- run the command **once on start** (first cycle produces fresh data), then
- sleep to the next occurrence (`--daily HH:MM` or `--interval N [--rth-only]`,
  America/New_York).

`orderbook_collector.py` already loops internally (no wrapper).

## Live/paper invariants (as deployed)

- **LIVE:** `live-equities` (Robinhood) and `live-equities-ibkr` (IBKR 4001).
  Both carry a broker-side protective stop on every entry; `account_mode_ok`
  refuses orders on a paper/live account mismatch (fail-closed both directions).
- **PAPER (currently stopped):** `live-index`, `live-gold`, `live-vwap` on port
  4002. `LIVE=false` / `VWAP_EXECUTION=PAPER` still pinned in those units.
- **Cross-broker de-dup** (`bot/cross_broker.py`): the two LIVE lanes run the same
  RSI2 signal, so whichever runs first (IBKR 09:30) owns the name and the other
  (RH 09:32) skips it — otherwise one signal becomes 2x notional with two half-stops.
- **Orphan sweep** (`bot/sweep_orphan_orders.py`, 09:25 + 16:05 ET): cancels any
  resting broker order with no book position. Added after 9 live market orders were
  found queued at Robinhood on 2026-08-24 with no stop and no book row.
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
