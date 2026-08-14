#!/bin/bash
# IB Gateway headless launcher (paper trading)
export DISPLAY=:99
# Start virtual display if needed
if ! pgrep -x Xvfb > /dev/null; then
    Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset &>/dev/null &
    sleep 3
fi
exec /home/ubuntu/ibgateway/ibgateway -Dgateway=true
