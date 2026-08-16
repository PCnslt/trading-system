#!/bin/bash
# IB Gateway headless login helper — types the paper password + clicks "Paper Log In".
# Used for the WEEKLY 2FA re-login (after IBKR invalidates the security token Sunday
# ~1:00am ET) and for any manual full restart. 2FA approval still happens on the phone
# (IB Key push) — this only removes the manual password typing, NOT the 2FA floor.
#
# Coordinates are for the login dialog on DISPLAY=:99 (Xvfb 1280x800, openbox).
# The dialog is centered at (245,95) 790x610. Adjust if the layout changes.
#
# Usage:  DISPLAY=:99 /home/ubuntu/ibgateway-login.sh

set -u
export DISPLAY=:99

# --- SSM-first secrets (source of truth: /trading/ibkr/*, SecureString) ---
# Prefer SSM via infra/secrets.py; fall back to ~/ibgateway-creds.env (the
# file cache) when SSM is unreachable or a key is absent. Never crash on an
# SSM hiccup — the eval emits whatever it can and we only abort if BOTH are
# missing.
eval "$(python3 /home/ubuntu/trading-system/infra/secrets.py --ibkr-shell)"
if [ -z "${IBG_USERNAME:-}" ] || [ -z "${IBG_PASSWORD:-}" ]; then
    echo "no IBG creds from SSM or ~/ibgateway-creds.env"; exit 1
fi

# --- locate the login window ---
WIN=$(xdotool search --name "IBKR Gateway" 2>/dev/null | head -1)
[ -n "$WIN" ] || { echo "no IBKR Gateway window found"; exit 1; }
xdotool windowactivate "$WIN" 2>/dev/null
sleep 1

# --- type username (clear pre-fill, then type) ---
xdotool mousemove 700 377 click 1; sleep 1
xdotool key ctrl+a; sleep 0.3
xdotool type --delay 40 "$IBG_USERNAME"; sleep 1

# --- type password ---
xdotool mousemove 700 415 click 1; sleep 1
xdotool key ctrl+a; sleep 0.3
xdotool type --delay 60 "$IBG_PASSWORD"; sleep 1

# --- click "Paper Log In" ---
xdotool mousemove 660 479 click 1

# --- accept the paper-trading disclaimer if it appears (one-time per account) ---
sleep 6
if xdotool search --name "Warning" 2>/dev/null | grep -q .; then
    xdotool mousemove 639 510 click 1
    sleep 2
fi

echo "login helper complete — approve the IB Key 2FA push on your phone if prompted."
