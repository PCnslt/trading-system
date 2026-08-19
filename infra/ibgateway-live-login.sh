#!/bin/bash
# IB Gateway LIVE login helper — types the live password + submits the LIVE login.
#
# Same mechanism as the paper helper (infra/ibgateway-login.sh) but for the LIVE
# gateway on DISPLAY=:100. tradingMode=l in Jts-live/jts.ini pre-selects the LIVE
# login button, so pressing Enter after the password submits LIVE (mirrors the
# paper finding that "Enter submits the default/only button").
#
# 2FA approval is STILL a phone action (IB Key push) — this only removes the
# manual password typing, NOT the 2FA floor. The FIRST live login always needs
# 2FA; subsequent daily auto-restarts reuse the stored soft token.
#
# Usage:  sudo -u ubuntu DISPLAY=:100 /home/ubuntu/ibgateway-live-login.sh

set -u
export DISPLAY=:100

eval "$(python3 /home/ubuntu/trading-system/infra/ssm_secrets.py --ibkr-shell)"
if [ -z "${IBG_USERNAME:-}" ] || [ -z "${IBG_PASSWORD:-}" ]; then
    echo "no IBG creds from SSM or ~/ibgateway-creds.env"; exit 1
fi

WIN=$(xdotool search --name "IBKR Gateway" 2>/dev/null | head -1)
[ -n "$WIN" ] || { echo "no IBKR Gateway window found on :100"; exit 1; }
xdotool windowactivate "$WIN" 2>/dev/null
sleep 1

# username (clear pre-fill, then type) — same field coords as the paper dialog
xdotool mousemove 700 377 click 1; sleep 1
xdotool key ctrl+a; sleep 0.3
xdotool type --delay 40 "$IBG_USERNAME"; sleep 1

# password
xdotool mousemove 700 415 click 1; sleep 1
xdotool key ctrl+a; sleep 0.3
xdotool type --delay 60 "$IBG_PASSWORD"; sleep 1

# submit — tradingMode=l pre-selects the LIVE "Log In" button, Enter submits it.
# (The LIVE button coordinate is version-specific and UNVERIFIED; if Enter does
# not submit, OCR the screen (DISPLAY=:100 scrot + tesseract) and click the live
# "Log In" button by its actual coordinates instead.)
xdotool key Return

echo "live login helper complete — approve the IB Key 2FA push on your phone,"
echo "then accept any live-trading / brokerage disclaimer that appears."
