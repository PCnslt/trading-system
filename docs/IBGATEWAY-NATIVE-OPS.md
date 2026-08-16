# IB Gateway — Native Ops (IBC removed)

IBC is retired 2026-09-01. This VPS now runs IB Gateway **natively** (no IBC).
Daily re-login uses IB's first-party auto-restart + token re-use; the weekly
2FA floor is unchanged (one phone approval ~1x/week — an IBKR hard requirement).

## Architecture

- **Launch**: `systemd ibgateway.service` → `/home/ubuntu/ibgateway-native-start.sh`
  → `/home/ubuntu/ibgateway/ibgateway` (install4j launcher, entry point
  `install4j.ibgateway.GWClient`). Xvfb `:99` + openbox are kept (Gateway is a GUI app).
- **Pin build 10.45.1j**: `INSTALL4J_ADD_VM_PARAMS="-Dtwslaunch.autoupdate.serviceImpl=twslaunch.autoupdate.DummyAutoUpdateService"`
  (no-op updater; last `-D` on the java command line wins, so it overrides the
  launcher's `Install4jAutoUpdateService`).
- **Daily restart 04:00 UTC**: Gateway's native "Auto restart" (Global Configuration
  → Lock and Exit → Auto restart + time). Stores an encrypted SOFT session token
  (`AutoRestartDescriptor` / "autorestart file") and re-logs-in without password or 2FA.
- **Weekly cold restart Sunday 13:00 UTC**: `ibgateway-weekly.timer` →
  `ibgateway-weekly.service` (`systemctl restart ibgateway`). IBKR invalidates security
  tokens Sunday ~1:00am ET, so this restart lands AFTER invalidation → full login + 2FA.
- **API**: port 4002, paper account DUR193467. `jts.ini` already has
  `ApiOnly=true`, `AcceptIncomingConnection=1` (persisted, survives restarts).

## Hang-recovery watchdog (alive-but-socket-dead)

**Known failure mode (2026-08-16 — 7h outage):** the 04:00 native auto-restart can
leave the gateway `active (running)` while the API socket (port 4002) never opens.
That is a **HANG, not a crash**. systemd `Restart=always` only fires on process EXIT,
so a hung process sits dead forever without intervention — exactly what happened
(verified: a manual restart at 11:49 brought 4002 up with NO 2FA, i.e. a hung
process, not the weekly token floor).

`ibgateway-hang-watchdog.{timer,service}` + `infra/ibgateway-hang-watchdog.sh` now
auto-recover this. It is a **cheap `ss -ltn` socket check every 2 min** — no IB API
call, no connection attempt.

1. port 4002 closed for **>3 min** (3 consecutive checks) → `systemctl restart
   ibgateway` **ONCE**, then wait 90s.
2. port 4002 back → log `recovered from hang`, reset state, and run
   `gateway_resume.sh` (resumes the IBKR backfill if it is inactive).
3. port 4002 **still** closed → log `likely 2FA`, send a **Telegram alert** to the
   owner, and **STOP** (do NOT restart in a loop — repeated restarts would only spam
   2FA pushes).

State persists in `data/ibgateway_watchdog.state` and resets automatically when 4002
returns. The alert is retried until delivered (never silently dropped), and a slow
post-restart login is tolerated because any later up-transition resets + resumes.
The watchdog **never bypasses 2FA** — it only detects the hang and alerts.

## Weekly 2FA re-login (manual floor — do NOT try to bypass)

Sunday 13:00 UTC the timer restarts the gateway. It lands on the login screen
(username pre-filled). Approve on your phone:

```bash
# from the VPS (or via the telegram bot → ask VPS Hermes to run it):
DISPLAY=:99 /home/ubuntu/ibgateway-login.sh   # types password + clicks "Paper Log In"
# then approve the IB Key 2FA push on the phone.
```

Credentials live in `/home/ubuntu/ibgateway-creds.env` (chmod 600, not committed).
The paper-trading disclaimer ("This is not a brokerage account…") is auto-accepted
by the helper the first time it appears.

If the gateway instead HANGS (running-but-socket-dead), the hang-recovery watchdog
(`ibgateway-hang-watchdog.timer`) restarts it once and alerts you via Telegram only
if 2FA is then required — it never auto-bypasses the phone approval.

## Verification checklist (run after any change)

1. `systemctl is-active ibgateway` → active.
2. `ss -tlnp | grep :4002` → LISTEN.
3. `python3 -c "from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1',4002,clientId=90,timeout=15); print(ib.managedAccounts()); ib.disconnect()"` → `['DUR193467']`.
4. `grep -i "Daily auto-restart" ~/Jts/launcher.log | tail -1` — "not enabled" on a fresh
   login is EXPECTED (that message is about the *current* session's restart context, not
   the global config). Confirm the auto-restart *time* is set: it was configured to
   04:00 AM and persists in the encrypted settings.
5. MES paper round-trip fills only when CME Globex is open (Sun 22:00 → Fri 21:00 UTC).
   `bot/execution_test.py` proves the full path; re-run during market hours for a fill.
6. Weekly timer: `systemctl list-timers ibgateway-weekly.timer` → next = Sunday 13:00 UTC.
7. Pin intact: `pgrep -af GWClient | grep -o 'DummyAutoUpdateService'` → present.
8. Post-restart token re-login: after the 04:00 UTC auto-restart, the one-shot Hermes cron
   check runs `~/.hermes/scripts/ibgw_restart_check.sh` (port 4002 + GWClient process +
   read-only `managedAccounts()==['DUR193467']`) and reports to Telegram. Reuse it to
   verify any restart without re-deriving the checks.
9. Hang watchdog: `systemctl list-timers ibgateway-hang-watchdog.timer` → next fire ≤2 min;
   `journalctl -u ibgateway-hang-watchdog -n 20` → healthy checks are silent, state
   transitions logged; `data/ibgateway_watchdog.state` → all-zero when healthy.

## Standing rule — NEVER DISCARD PAID DATA

Every market-data fetch (bars, ticks, quotes, news, fundamentals, scan results) MUST be
persisted to S3 (`trading-datalake-920641308584`, analytical bucket). Nothing fetched is
ever fetched-and-discarded. Ingest jobs default to persisting; a fetch that does not write
its output is a bug. Current archive paths: `news/`, `crypto/`, `futures-bars/`,
`research/scan-results/`.

## IBC remnant

`/home/ubuntu/ibc/` (IBC.jar, config.ini) is left in place for reference/rollback but is
no longer launched. Rollback: restore the backup at
`/home/ubuntu/ibc-migration-backup_<ts>/` and point the systemd unit back at
`/home/ubuntu/ibc/gatewaystart.sh -inline`.
