#!/bin/bash
# Gateway-aware resume trigger for the IBKR full-depth backfill.
# Fired by ibkr-backfill-resume.timer. Starts the backfill ONLY when:
#   - the gateway (port 4002) is listening (user 2FA done), AND
#   - the backfill is not already complete (no COMPLETE flag), AND
#   - no backfill is already running.
# Never restarts the gateway itself — that's the user's 2FA action.
set -u

REPO=/home/ubuntu/trading-system
COMPLETE_FLAG=$REPO/data/ibkr_full_backfill.COMPLETE

# 1. gateway up? (read-only socket check — no connection attempt, no loop)
if ! ss -ltn 2>/dev/null | grep -qE ':4002[[:space:]]'; then
  exit 0
fi

# 2. already fully complete?
if [ -f "$COMPLETE_FLAG" ]; then
  exit 0
fi

# 3. backfill already running?
if systemctl is-active --quiet ibkr-backfill.service; then
  exit 0
fi

systemctl start --no-block ibkr-backfill.service
