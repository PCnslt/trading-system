#!/bin/bash
# Gateway-aware resume trigger for the IBKR full-depth backfill.
# Fired by ibkr-backfill-resume.timer. Starts the backfill ONLY when:
#   - the gateway (port 4002) is listening (user 2FA done), AND
#   - there is actual work left:
#       * daily phases incomplete -> start (ANY day), OR
#       * 1-min phases incomplete AND inside the weekend window
#         (Sat 00:00 - Sun 16:00 ET) AND not explicitly paused.
# Never restarts the gateway itself — that's the user's 2FA action.
set -u

REPO=/home/ubuntu/trading-system
DAILY_FLAG=$REPO/data/ibkr_daily.COMPLETE
COMPLETE_FLAG=$REPO/data/ibkr_full_backfill.COMPLETE
PAUSE_FLAG=$REPO/data/ibkr_1min_paused

# 1. gateway up? (read-only socket check — no connection attempt, no loop)
if ! ss -ltn 2>/dev/null | grep -qE ':4002[[:space:]]'; then
  exit 0
fi

# 2. daily phases incomplete -> start (any day)
if [ ! -f "$DAILY_FLAG" ]; then
  if systemctl is-active --quiet ibkr-backfill.service; then exit 0; fi
  systemctl start --no-block ibkr-backfill.service
  exit 0
fi

# 3. daily done; 1-min only when complete-flag absent, not paused, weekend window
if [ -f "$COMPLETE_FLAG" ]; then exit 0; fi
if [ -f "$PAUSE_FLAG" ]; then exit 0; fi
dow=$(TZ=America/New_York date +%u)
hm=$(TZ=America/New_York date +%H%M)
in_window=0
[ "$dow" = "6" ] && in_window=1
[ "$dow" = "7" ] && [ "$hm" -lt "1600" ] && in_window=1
if [ "$in_window" != "1" ]; then exit 0; fi

# 4. not already running
if systemctl is-active --quiet ibkr-backfill.service; then exit 0; fi

systemctl start --no-block ibkr-backfill.service
