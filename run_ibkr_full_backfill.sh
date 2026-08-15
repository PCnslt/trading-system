#!/bin/bash
# IBKR full-depth backfill runner — phases in priority order, resumable.
# Logs to data/ibkr_full_backfill.log. Each phase is checkpointed/resumable.
set -u
cd /home/ubuntu/trading-system
PY=./venv/bin/python
LOG=data/ibkr_full_backfill.log

run() {
  echo "" >> "$LOG"
  echo "===== $* @ $(date -u +%FT%TZ) =====" >> "$LOG"
  $PY -u data/ibkr_full_backfill.py "$@" >> "$LOG" 2>&1
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
