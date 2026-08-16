#!/bin/bash
# One-shot watcher: stop the ibkr-backfill.service the moment the equities-DAILY
# phase completes, BEFORE the wrapper chains into the 1-min phases (which must
# be PAUSED this weekend — they'd contend with live market hours).
#
# The current in-memory run_ibkr_full_backfill.sh has ALREADY buffered its
# phase 4-6 lines, so editing the script won't stop THIS run. This watcher
# watches the LOG for a NEW `--mode futures --kind 1min` phase header (baseline
# captured at start) — that header is only written AFTER the equities-daily
# python exits 0 (a failed phase aborts the wrapper before phase 4). On detect:
#   - touch data/ibkr_daily.COMPLETE  (ground truth: daily genuinely done)
#   - stop ibkr-backfill.service       (halt before/at the 1-min phases)
# The resume timer is left ACTIVE — the weekend-window + pause-flag gate in
# gateway_resume.sh prevents any unwanted restart.
set -u
REPO=/home/ubuntu/trading-system
LOG=$REPO/data/ibkr_full_backfill.log
DAILY_FLAG=$REPO/data/ibkr_daily.COMPLETE

F1_BASE=$(grep -c "mode futures --kind 1min" "$LOG")
EQFAIL_BASE=$(grep -c "PHASE FAILED: --mode equities" "$LOG")
echo "watcher: baseline futures-1min headers=$F1_BASE, equities-fail=$EQFAIL_BASE @ $(date -u +%FT%TZ)"

for i in $(seq 1 2160); do   # 2160 * 5s = 3 h max
  F1=$(grep -c "mode futures --kind 1min" "$LOG")
  if [ "$F1" -gt "$F1_BASE" ]; then
    echo "PHASE-4 REACHED (futures-1min header $F1_BASE -> $F1) @ $(date -u +%FT%TZ)"
    echo "  -> equities-daily genuinely complete; touching daily COMPLETE flag"
    touch "$DAILY_FLAG"
    if sudo -n systemctl stop ibkr-backfill.service; then
      echo "STOPPED ibkr-backfill.service (1-min paused this weekend)"
      exit 0
    else
      echo "ERROR: systemctl stop failed (rc=$?) — MANUAL STOP REQUIRED: sudo systemctl stop ibkr-backfill.service" >&2
      exit 1
    fi
  fi
  EQFAIL=$(grep -c "PHASE FAILED: --mode equities" "$LOG")
  if [ "$EQFAIL" -gt "$EQFAIL_BASE" ]; then
    echo "EQUITIES-DAILY FAILED AGAIN ($EQFAIL_BASE -> $EQFAIL) @ $(date -u +%FT%TZ) — letting systemd Restart=on-failure resume (checkpoint)"
    EQFAIL_BASE=$EQFAIL
  fi
  sleep 5
done
echo "watcher: timed out after 3 h without seeing phase 4 — CHECK MANUALLY"
exit 1
