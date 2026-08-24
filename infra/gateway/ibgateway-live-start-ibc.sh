#!/bin/bash
# IB Gateway LIVE launcher via IBC — WITH LOGIN-FAILURE CIRCUIT BREAKER.
#
# WHY IBC AND NOT THE NATIVE LAUNCHER:
#   The native launcher shows a login dialog whose "Trading Mode" is a Swing
#   JComboBox. Driving it headlessly with xdotool/OCR does NOT work: the label
#   changes to "Live Trading" but the selection model never commits, so the
#   session authenticates as PAPER. Patching tradingMode=l in jts.ini does not
#   override it either. IBC sets the mode inside the JVM (TRADING_MODE=live) —
#   verified working: "IBC: Setting Trading mode = live".
#
# WHY THE CIRCUIT BREAKER (learned the hard way 2026-08-24):
#   IBC's own script cold-restarts on login failure AND systemd Restart=always
#   restarts the unit. With bad/locked credentials this produced 106 failed
#   IBKR login attempts in ~7 minutes, which risks an IBKR username lockout.
#   Now: the FIRST "Login failed" writes LOGIN_FAILED.lock and aborts. A human
#   must fix the credential and delete the lock file before any retry.
#     clear with:  rm /home/ubuntu/ibc-live/LOGIN_FAILED.lock
#
# Isolation from the paper gateway:
#   display :100 (paper :99) | settings ~/Jts-live (paper ~/Jts)
#   config ~/ibc-live/config.ini | API port 4001 (paper 4002)
#   username mushfiqrhmn1-live  <-- IBKR forbids 2 concurrent sessions per username
#
# MEMORY NOTE: t3.small (2GB) cannot host BOTH gateways. The live JVM could not
# even render its login dialog until the paper gateway was stopped (available RAM
# went 268MB -> 863MB). Running both permanently needs a bigger instance.

set -uo pipefail

LOCK=/home/ubuntu/ibc-live/LOGIN_FAILED.lock
LOGDIR=/home/ubuntu/ibc-live/logs

if [ -f "$LOCK" ]; then
    echo "REFUSING TO START: $LOCK exists — a previous live login FAILED."
    echo "Fix the credential, then: rm $LOCK"
    cat "$LOCK"
    exit 78   # EX_CONFIG
fi

export DISPLAY=:100

if ! pgrep -f "Xvfb :100" > /dev/null; then
    Xvfb :100 -screen 0 1280x800x24 -ac +extension GLX +render -noreset &>/dev/null &
    sleep 3
fi
if ! pgrep -f "openbox --display :100" > /dev/null; then
    DISPLAY=:100 openbox --display :100 &>/dev/null &
    sleep 1
fi

export INSTALL4J_ADD_VM_PARAMS="-DjtsConfigDir=/home/ubuntu/Jts-live -Dtwslaunch.autoupdate.serviceImpl=twslaunch.autoupdate.DummyAutoUpdateService"

# --- watchdog: trip the breaker on the first login failure -------------------
(
  while true; do
    sleep 5
    LOG=$(ls -t "$LOGDIR"/* 2>/dev/null | head -1)
    [ -z "$LOG" ] && continue
    if tail -40 "$LOG" 2>/dev/null | grep -q "IBC: Login failed"; then
        {
          echo "tripped_at=$(date -Is)"
          echo "reason=IBC reported 'Login failed' for username in /home/ubuntu/ibc-live/config.ini"
          echo "action=verify the username/password can log in at https://www.interactivebrokers.com/sso/Login"
          echo "note=IBKR locks a username after repeated failures; do NOT loop retries"
        } > "$LOCK"
        echo "CIRCUIT BREAKER TRIPPED — killing live gateway to protect the IBKR username"
        pkill -f "ibcsessionid" 2>/dev/null
        pkill -f "ibcalpha.ibc.IbcGateway" 2>/dev/null
        exit 0
    fi
  done
) &
WATCHDOG=$!
trap 'kill $WATCHDOG 2>/dev/null' EXIT

/home/ubuntu/ibc-live/gatewaystart-live.sh -inline
RC=$?

# if the breaker tripped, fail loudly so systemd StartLimit stops us
[ -f "$LOCK" ] && exit 1
exit $RC
