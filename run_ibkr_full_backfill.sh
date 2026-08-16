#!/bin/bash
# IBKR full-depth backfill runner — phases in priority order, resumable.
# Logs to data/ibkr_full_backfill.log. Each phase is checkpointed/resumable.
#
# FATAL-on-failure semantics (owner directive 2026-08-16): any phase that exits
# non-zero ABORTS the whole run with a non-zero exit so systemd
# Restart=on-failure relaunches and the checkpoint resumes. "ALL PHASES
# COMPLETE" is printed ONLY when every phase actually succeeded.
set -u
cd /home/ubuntu/trading-system
PY=./venv/bin/python
LOG=data/ibkr_full_backfill.log
COMPLETE_FLAG=data/ibkr_full_backfill.COMPLETE

# ---- gateway pre-flight ----------------------------------------------------
# If port 4002 is not listening (daily 04:00 restart stuck at the Sunday 2FA
# login), do NOT run phases and do NOT loop. Exit 0 cleanly and wait for the
# user's phone 2FA; ibkr-backfill-resume.timer re-triggers once the port is up.
if ! ss -ltn 2>/dev/null | grep -qE ':4002[[:space:]]'; then
  echo "" >> "$LOG"
  echo "===== GATEWAY NOT UP @ $(date -u +%FT%TZ) =====" >> "$LOG"
  echo "port 4002 not listening — waiting for user phone 2FA (Sunday floor)." >> "$LOG"
  echo "Exiting 0 (no loop); ibkr-backfill-resume.timer re-runs when the port is up." >> "$LOG"
  exit 0
fi

run() {
  echo "" >> "$LOG"
  echo "===== $* @ $(date -u +%FT%TZ) =====" >> "$LOG"
  if ! $PY -u data/ibkr_full_backfill.py "$@" >> "$LOG" 2>&1; then
    echo "" >> "$LOG"
    echo "===== PHASE FAILED: $* @ $(date -u +%FT%TZ) =====" >> "$LOG"
    echo "===== BACKFILL INCOMPLETE — exiting NON-ZERO; systemd Restart=on-failure relaunches and the checkpoint resumes. =====" >> "$LOG"
    exit 1
  fi
}

# 1. futures daily (CONTfut + per-contract, ~56 symbols)  ~20 min
run --mode futures --kind daily
# 2. crypto micros daily (MBT/MET)
run --mode crypto --kind daily
# 3. equities daily (full universe ~6958)  ~10-14 h
run --mode equities --kind daily
# 4. futures 1-min (16 liquid, RTH monthly)  ~8 h
run --mode futures --kind 1min
# 5. crypto micros 1-min (MBT/MET)
run --mode crypto --kind 1min
# 6. equities 1-min (~1000 liquid, monthly)  ~weeks
run --mode equities --kind 1min

echo "" >> "$LOG"
echo "===== ALL PHASES COMPLETE @ $(date -u +%FT%TZ) =====" >> "$LOG"
touch "$COMPLETE_FLAG"
