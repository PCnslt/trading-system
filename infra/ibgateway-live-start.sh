#!/bin/bash
# IB Gateway LIVE launcher — separate settings dir + live trading mode (U26949861).
#
# Runs a SECOND gateway instance on DISPLAY=:100 with
#   -DjtsConfigDir=/home/ubuntu/Jts-live   (jts.ini has tradingMode=l)
# so paper (:4002, DISPLAY :99, Jts/) and live (live API port, Jts-live/) are
# FULLY ISOLATED — a bot pointed at 4002 can never reach live, and vice versa.
#
# This unit is DISABLED by default (do not enable until the account is funded +
# permissioned + the owner completes the first live 2FA login).
#
# Pin build 10.45.1j: INSTALL4J_ADD_VM_PARAMS overrides the auto-update service
# to the no-op DummyAutoUpdateService AND relocates the settings dir. The
# launcher resolves jtsConfigDir from response.varfile (=/home/ubuntu/Jts); our
# later -D wins (same "last -D wins" mechanism as the pin-build override).

export DISPLAY=:100

# Dedicated Xvfb for the live instance (isolates its window from paper on :99).
if ! pgrep -f "Xvfb :100" >/dev/null; then
    Xvfb :100 -screen 0 1280x800x24 -ac +extension GLX +render -noreset &>/dev/null &
    sleep 3
fi

# A window manager on :100 (openbox) so the login helper can map/activate the
# login window. Check the DISPLAY of any running openbox to avoid duplicating
# paper's :99 openbox or our own.
_openbox_on_100() {
    for pid in $(pgrep -x openbox 2>/dev/null); do
        if tr '\0' '\n' </proc/$pid/environ 2>/dev/null | grep -qx 'DISPLAY=:100'; then
            return 0
        fi
    done
    return 1
}
if ! _openbox_on_100; then
    DISPLAY=:100 openbox &>/dev/null &
    sleep 1
fi

export INSTALL4J_ADD_VM_PARAMS="-Dtwslaunch.autoupdate.serviceImpl=twslaunch.autoupdate.DummyAutoUpdateService -DjtsConfigDir=/home/ubuntu/Jts-live"

exec /home/ubuntu/ibgateway/ibgateway
