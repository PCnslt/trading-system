#!/usr/bin/env python3
"""Run a one-shot trading bot on a repeating schedule as a long-lived daemon.

The forward-test bots (live.py, live_gc.py, live_vwap.py, live_equities.py)
are ONE-SHOT daily/intraday entrypoints, not event loops. To run them as
persistent systemd services (so `systemctl is-active` == active and `ps`
shows a live process), each service wraps its bot in THIS loop.

On start it runs the command ONCE immediately (so the first cycle produces
fresh data right away), then sleeps until the next scheduled occurrence.
The wrapped command's exit code is logged but does NOT kill the loop — a
one-shot bot "completing" with exit 0 is normal. The wrapper only exits
non-zero on an internal error, letting systemd Restart=on-failure relaunch it.

Schedule (America/New_York wall-clock):
  --daily HH:MM             run once per day at HH:MM ET (immediate first)
  --interval N              run every N minutes (immediate first)
  --interval N --rth-only   run every N minutes, but ONLY 09:30-16:00 ET
                            Mon-Fri; sleeps through nights/weekends.
"""
import argparse
import subprocess
import sys
import time
import datetime as dt
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
RTH_OPEN = dt.time(9, 30)
RTH_CLOSE = dt.time(16, 0)


def _in_rth(now: dt.datetime) -> bool:
    return now.weekday() < 5 and RTH_OPEN <= now.time() < RTH_CLOSE


def _next_rth_open(now: dt.datetime) -> dt.datetime:
    # next 09:30 ET strictly in the future — today if before the open,
    # otherwise the next weekday.
    d = now.date()
    target = dt.datetime.combine(d, RTH_OPEN, tzinfo=NY)
    while target <= now or target.weekday() >= 5:
        d += dt.timedelta(days=1)
        target = dt.datetime.combine(d, RTH_OPEN, tzinfo=NY)
    return target


def _next_daily(hh: int, mm: int, now: dt.datetime) -> dt.datetime:
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return target


def run_once(cmd):
    t0 = time.time()
    print(f"[bot_loop] running: {' '.join(cmd)}", flush=True)
    try:
        rc = subprocess.run(cmd).returncode
    except FileNotFoundError as e:
        print(f"[bot_loop] exec failed: {e}", flush=True)
        rc = 127
    print(f"[bot_loop] done rc={rc} in {time.time() - t0:.1f}s", flush=True)
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", help="HH:MM ET daily schedule (e.g. 19:00)")
    ap.add_argument("--interval", type=int, help="minutes between runs")
    ap.add_argument("--rth-only", action="store_true",
                    help="with --interval: gate runs to RTH 09:30-16:00 ET Mon-Fri")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()

    cmd = [c for c in args.cmd if c != "--"]
    if not cmd:
        print("[bot_loop] no command given", flush=True)
        sys.exit(2)
    if args.daily is None and args.interval is None:
        print("[bot_loop] need --daily or --interval", flush=True)
        sys.exit(2)
    if args.daily:
        try:
            hh, mm = (int(x) for x in args.daily.split(":"))
        except Exception:
            print(f"[bot_loop] bad --daily {args.daily!r} (want HH:MM)", flush=True)
            sys.exit(2)

    CATCHUP_MIN = 10  # restart within this many min AFTER the daily time -> run now (catch-up)
    first = True
    while True:
        now = dt.datetime.now(NY)
        if args.rth_only and not _in_rth(now):
            nxt = _next_rth_open(now)
            secs = (nxt - now).total_seconds()
            print(f"[bot_loop] outside RTH — sleeping {secs / 3600:.1f}h "
                  f"to next open {nxt:%Y-%m-%d %H:%M %Z}", flush=True)
            time.sleep(secs)
            continue

        # Daily bots must NOT fire off-hours on service (re)start. A deploy at
        # 02:07 ET ran the 19:00 daily bot immediately, producing spurious
        # off-hours entries (gold fired two LONGs that timed out UNKNOWN).
        # Only run the immediate first cycle within a small catch-up window of
        # the scheduled time; otherwise sleep straight to the next schedule.
        if first and args.daily:
            sched = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            delta = (now - sched).total_seconds()
            if not (0.0 <= delta <= CATCHUP_MIN * 60):
                nxt = _next_daily(hh, mm, now)
                secs = (nxt - now).total_seconds()
                print(f"[bot_loop] daily {args.daily} — off-schedule start, sleeping "
                      f"{secs / 3600:.1f}h to {nxt:%Y-%m-%d %H:%M %Z}", flush=True)
                time.sleep(secs)
                first = False
                continue
        first = False

        run_once(cmd)

        now = dt.datetime.now(NY)
        if args.daily:
            nxt = _next_daily(hh, mm, now)
            secs = (nxt - now).total_seconds()
        else:
            secs = args.interval * 60
        print(f"[bot_loop] next run in {secs / 60:.1f} min "
              f"({(now + dt.timedelta(seconds=secs)):%Y-%m-%d %H:%M %Z})", flush=True)
        time.sleep(secs)


if __name__ == "__main__":
    main()
