#!/bin/bash
# IB Gateway hang-recovery watchdog (with auto re-login rung).
#
# Detects the "alive-but-socket-dead" failure mode: GWClient is `active (running)`
# but the API socket (port 4002) never opened. systemd `Restart=always` only fires
# on process EXIT — a hung process never exits, so it sat dead for 7h (2026-08-16).
#
# Recovery ladder (each rung tried ONCE per episode, in order):
#   1. `systemctl restart ibgateway` + 90s wait  — fixes a socket-dead/crash-loop.
#   2. auto re-login via ibgateway-login.sh (fired DETACHED via systemd-run) — fixes
#      the DAILY-restart LOGIN hang (JVM up, sitting on the login screen). Paper mode
#      needs NO 2FA, so this is fully automatable. Guarded by an OCR check that the
#      screen still reads PAPER ("SIMULATED TRADING") BEFORE typing credentials, so we
#      can never reach the live account (U26949861) by mistake.
#   3. Telegram alert to the owner, then STOP (no restart/login loop).
#
# Fired every 2 min by ibgateway-hang-watchdog.timer. CHEAP check only: `ss -ltn`
# socket table — no IB API call, no connection attempt.
#
# State machine (persistent in data/ibgateway_watchdog.state):
#   port up                    -> reset state, silent (healthy).
#   port down, <3 checks       -> keep counting (grace window >3 min).
#   port down, >=3 checks      -> restart ibgateway ONCE, wait 90s.
#       port back              -> log recovered, resume backfill, reset.
#       port still down        -> next cycle attempts OCR-guarded auto re-login.
#   port down, login fired     -> wait up to LOGIN_GRACE (240s) for port to return.
#   port down, login+grace     -> Telegram alert, STOP (await human).
set -u

REPO=/home/ubuntu/trading-system
STATE_FILE="$REPO/data/ibgateway_watchdog.state"
NOTIFY="$REPO/infra/telegram_notify.py"
RESUME="$REPO/gateway_resume.sh"
LOGIN_HELPER=/home/ubuntu/ibgateway-login.sh
LOGIN_LOG=/tmp/gw_watchdog_login.log
PORT_RE=':4002[[:space:]]'
LOGIN_GRACE=240   # seconds to give a fired auto-login before alerting the owner

ts() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
port_up() { ss -ltn 2>/dev/null | grep -qE "$PORT_RE"; }

DOWN_COUNT=0
RESTARTED=0
LOGIN_TRIED=0
LOGIN_AT=0
NOTIFIED=0

load_state() {
    [ -f "$STATE_FILE" ] || return 0
    # shellcheck disable=SC1090
    . "$STATE_FILE" 2>/dev/null || true
    case "$DOWN_COUNT"  in ''|*[!0-9]*) DOWN_COUNT=0 ;; esac
    case "$RESTARTED"  in ''|*[!0-9]*) RESTARTED=0 ;; esac
    case "$LOGIN_TRIED" in ''|*[!0-9]*) LOGIN_TRIED=0 ;; esac
    case "$LOGIN_AT"   in ''|*[!0-9]*) LOGIN_AT=0 ;; esac
    case "$NOTIFIED"   in ''|*[!0-9]*) NOTIFIED=0 ;; esac
}

save_state() {
    printf 'DOWN_COUNT=%s\nRESTARTED=%s\nLOGIN_TRIED=%s\nLOGIN_AT=%s\nNOTIFIED=%s\n' \
        "$1" "$2" "$3" "$4" "$5" > "$STATE_FILE"
}

notify_owner() {
    if "$NOTIFY" "$1"; then return 0; fi
    echo "[$(ts)] ERROR: Telegram notify failed (will retry next check)" >&2
    return 1
}

alert_body() {
    local last
    last=$(journalctl -u ibgateway -n 8 --no-pager 2>/dev/null | tail -8)
    cat <<EOF
🚨 IB Gateway HANG — port 4002 not recovered (restart + auto-login both tried)

$(ts)
• gateway "running" but API socket (4002) closed = known hang mode (not a crash)
• issued ONE systemctl restart AND one OCR-guarded auto re-login (paper) — 4002 STILL closed

Likely: weekly 2FA floor or a crash-loop — manual check needed.

Recent ibgateway log:
${last}

Watchdog has STOPPED (no restart/login loop). It auto-resumes everything once 4002 is back.
EOF
}

# OCR-guarded auto re-login, fired DETACHED (systemd-run) so it runs to completion
# (its dialog-polling can take minutes) without blocking the watchdog or being killed
# by TimeoutStartSec. Returns 0 if fired, 1 if aborted (no window / OCR failed).
auto_login_fire() {
    export DISPLAY=:99
    local shot=/tmp/gw_watchdog_login.png win
    win=$(xdotool search --name "IBKR Gateway" 2>/dev/null | head -1)
    if [ -z "$win" ]; then
        echo "[$(ts)] auto-login: no IBKR Gateway window (JVM not up) — skipping"
        return 1
    fi
    import -window root "$shot" 2>/dev/null || { echo "[$(ts)] auto-login: screenshot failed"; return 1; }
    if ! tesseract "$shot" stdout 2>/dev/null | grep -qi "SIMULATED TRADING"; then
        echo "[$(ts)] auto-login: OCR did NOT confirm PAPER mode — REFUSING to type credentials (manual check needed)"
        rm -f "$shot"
        return 1
    fi
    rm -f "$shot"
    echo "[$(ts)] auto-login: paper mode confirmed (SIMULATED TRADING) — firing login helper detached"
    systemd-run --collect -p User=ubuntu --property=Environment=DISPLAY=:99 \
        /bin/bash -c "$LOGIN_HELPER >> $LOGIN_LOG 2>&1" >/dev/null 2>&1 \
        && echo "[$(ts)] auto-login: login helper launched (log: $LOGIN_LOG)" \
        || echo "[$(ts)] auto-login: systemd-run failed to launch login helper"
    return 0
}

load_state

# ---- healthy: port up -> reset + silent ----
if port_up; then
    if [ "$DOWN_COUNT" -ne 0 ] || [ "$RESTARTED" -ne 0 ] || [ "$LOGIN_TRIED" -ne 0 ] || [ "$NOTIFIED" -ne 0 ]; then
        echo "[$(ts)] port 4002 UP — resetting watchdog state (down=$DOWN_COUNT restarted=$RESTARTED login=$LOGIN_TRIED notified=$NOTIFIED)"
        save_state 0 0 0 0 0
    fi
    exit 0
fi

# ---- port down ----

# Rung 2: restart already issued this episode -> escalate to auto-login, then alert.
if [ "$RESTARTED" -eq 1 ]; then
    if [ "$LOGIN_TRIED" -eq 0 ]; then
        LOGIN_TRIED=1
        LOGIN_AT=$(date +%s)
        auto_login_fire
        save_state "$DOWN_COUNT" "$RESTARTED" "$LOGIN_TRIED" "$LOGIN_AT" "$NOTIFIED"
        exit 0
    fi
    # login already fired — has the grace window elapsed with no recovery?
    if [ "$NOTIFIED" -eq 0 ] && [ $(( $(date +%s) - LOGIN_AT )) -ge "$LOGIN_GRACE" ]; then
        echo "[$(ts)] port 4002 still down $LOGIN_GRACE+s after auto-login — alerting owner"
        if notify_owner "$(alert_body)"; then
            NOTIFIED=1
            echo "[$(ts)] hang alert delivered to owner"
        fi
        save_state "$DOWN_COUNT" "$RESTARTED" "$LOGIN_TRIED" "$LOGIN_AT" "$NOTIFIED"
    else
        echo "[$(ts)] port 4002 down, auto-login in flight (${LOGIN_AT:--} / $LOGIN_GRACE s grace) — waiting"
    fi
    exit 0
fi

# ---- not yet restarted: count through the >3-min grace window ----
DOWN_COUNT=$(( DOWN_COUNT + 1 ))
if [ "$DOWN_COUNT" -lt 3 ]; then
    echo "[$(ts)] port 4002 down — check $DOWN_COUNT/3 (grace window, no action yet)"
    save_state "$DOWN_COUNT" 0 0 0 0
    exit 0
fi

# ---- hang confirmed (>3 min): restart ONCE ----
echo "[$(ts)] HANG DETECTED — port 4002 closed for $DOWN_COUNT checks (>3 min). Restarting ibgateway ONCE."
RESTARTED=1
save_state "$DOWN_COUNT" "$RESTARTED" 0 0 0
if ! systemctl restart ibgateway; then
    echo "[$(ts)] ERROR: systemctl restart ibgateway failed" >&2
fi
sleep 90

if port_up; then
    echo "[$(ts)] RECOVERED FROM HANG — port 4002 back after restart. Nudging backfill resume."
    save_state 0 0 0 0 0
    "$RESUME" || true
    exit 0
fi

# ---- still down 90s after restart: next cycle attempts OCR-guarded auto re-login ----
echo "[$(ts)] still down after restart+90s — will attempt OCR-guarded auto re-login on next check"
save_state "$DOWN_COUNT" "$RESTARTED" 0 0 0
exit 0
