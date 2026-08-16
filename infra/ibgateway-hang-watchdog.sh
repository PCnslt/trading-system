#!/bin/bash
# IB Gateway hang-recovery watchdog.
#
# Detects the "alive-but-socket-dead" failure mode: GWClient is `active (running)`
# but the API socket (port 4002) never opened. systemd `Restart=always` only fires
# on process EXIT — a hung process never exits, so it sat dead for 7h (2026-08-16).
# This watchdog force-restarts the gateway on that hang, and escalates to a Telegram
# alert when the restart does NOT restore the socket (weekly 2FA floor / crash-loop).
#
# Fired every 2 min by ibgateway-hang-watchdog.timer. CHEAP check only: `ss -ltn`
# socket table — no IB API call, no connection attempt.
#
# State machine (persistent in data/ibgateway_watchdog.state):
#   port up                -> reset state, silent (healthy).
#   port down, <3 checks   -> keep counting (grace window >3 min).
#   port down, >=3 checks  -> restart ibgateway ONCE, wait 90s.
#       port back          -> log "recovered from hang", resume backfill, reset.
#       port still down    -> log "likely 2FA", Telegram alert, STOP (no restart
#                             loop — restarting again would only spam 2FA pushes).
#   port down, restarted   -> retry the alert until delivered, then await human.
#                             Never restart again this episode. Resets on port-up.
set -u

REPO=/home/ubuntu/trading-system
STATE_FILE="$REPO/data/ibgateway_watchdog.state"
NOTIFY="$REPO/infra/telegram_notify.py"
RESUME="$REPO/gateway_resume.sh"
PORT_RE=':4002[[:space:]]'

ts() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
port_up() { ss -ltn 2>/dev/null | grep -qE "$PORT_RE"; }

DOWN_COUNT=0
RESTARTED=0
NOTIFIED=0

load_state() {
    [ -f "$STATE_FILE" ] || return 0
    # shellcheck disable=SC1090
    . "$STATE_FILE" 2>/dev/null || true
    case "$DOWN_COUNT" in ''|*[!0-9]*) DOWN_COUNT=0 ;; esac
    case "$RESTARTED" in ''|*[!0-9]*) RESTARTED=0 ;; esac
    case "$NOTIFIED"  in ''|*[!0-9]*) NOTIFIED=0 ;; esac
}

save_state() {
    printf 'DOWN_COUNT=%s\nRESTARTED=%s\nNOTIFIED=%s\n' "$1" "$2" "$3" > "$STATE_FILE"
}

notify_owner() {
    if "$NOTIFY" "$1"; then
        return 0
    fi
    echo "[$(ts)] ERROR: Telegram notify failed (will retry next check)" >&2
    return 1
}

alert_body() {
    local last
    last=$(journalctl -u ibgateway -n 8 --no-pager 2>/dev/null | tail -8)
    cat <<EOF
🚨 IB Gateway HANG — port 4002 not recovered

$(ts)
• gateway "running" but API socket (4002) closed = known hang mode (not a crash)
• issued ONE systemctl restart, waited 90s — 4002 STILL closed

Likely: weekly 2FA floor (login screen) — approve the IB Key push on your phone — or a crash-loop.

Recent ibgateway log:
${last}

Watchdog has STOPPED auto-restarting (no 2FA-push spam). It auto-resumes everything once 4002 is back.
EOF
}

load_state

# ---- healthy: port up -> reset + silent ----
if port_up; then
    if [ "$DOWN_COUNT" -ne 0 ] || [ "$RESTARTED" -ne 0 ] || [ "$NOTIFIED" -ne 0 ]; then
        echo "[$(ts)] port 4002 UP — resetting watchdog state (down=$DOWN_COUNT restarted=$RESTARTED notified=$NOTIFIED)"
        save_state 0 0 0
    fi
    exit 0
fi

# ---- port down ----
if [ "$RESTARTED" -eq 1 ]; then
    # The single restart for this episode was already issued (possibly in a prior,
    # interrupted invocation). Do NOT restart again. Just ensure the owner is told.
    if [ "$NOTIFIED" -eq 0 ]; then
        if notify_owner "$(alert_body)"; then
            NOTIFIED=1
            echo "[$(ts)] 2FA/outage alert delivered to owner"
        fi
        save_state "$DOWN_COUNT" "$RESTARTED" "$NOTIFIED"
    else
        echo "[$(ts)] port 4002 down, already alerted — awaiting human/2FA (no auto-restart, no spam)"
    fi
    exit 0
fi

# ---- not yet restarted this episode: count through the >3-min grace window ----
DOWN_COUNT=$(( DOWN_COUNT + 1 ))
if [ "$DOWN_COUNT" -lt 3 ]; then
    echo "[$(ts)] port 4002 down — check $DOWN_COUNT/3 (grace window, no action yet)"
    save_state "$DOWN_COUNT" 0 0
    exit 0
fi

# ---- hang confirmed (>3 min): restart ONCE ----
echo "[$(ts)] HANG DETECTED — port 4002 closed for $DOWN_COUNT consecutive checks (>3 min). Restarting ibgateway ONCE."
RESTARTED=1
save_state "$DOWN_COUNT" "$RESTARTED" 0
if ! systemctl restart ibgateway; then
    echo "[$(ts)] ERROR: systemctl restart ibgateway failed" >&2
fi
sleep 90

if port_up; then
    echo "[$(ts)] RECOVERED FROM HANG — port 4002 back after restart. Nudging backfill resume."
    save_state 0 0 0
    "$RESUME" || true
    exit 0
fi

# ---- still down 90s after one restart: likely 2FA floor or crash-loop. Alert, then STOP ----
echo "[$(ts)] STILL down after restart+90s — likely 2FA needed (weekly floor) or crash-loop. Alerting owner; no restart loop."
if notify_owner "$(alert_body)"; then
    NOTIFIED=1
fi
save_state "$DOWN_COUNT" "$RESTARTED" "$NOTIFIED"
exit 0
