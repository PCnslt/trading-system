#!/bin/bash
# IB Gateway native launcher — NO IBC.
#
# Launches IB Gateway via IB's own install4j launcher (/home/ubuntu/ibgateway/ibgateway,
# entry point install4j.ibgateway.GWClient) instead of IBC's ibcalpha.ibc.IbcGateway.
# Daily re-login is handled by the Gateway's NATIVE auto-restart (token reuse), which
# stores an encrypted SOFT session token and re-authenticates without a password or 2FA.
#
# Pin build 10.45.1j: INSTALL4J_ADD_VM_PARAMS overrides the auto-update service to the
# no-op DummyAutoUpdateService, so the "stable" channel never upgrades to an untested build.

export DISPLAY=:99

if ! pgrep -x Xvfb > /dev/null; then
    Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset &>/dev/null &
    sleep 3
fi
if ! pgrep -x openbox > /dev/null; then
    openbox &>/dev/null &
    sleep 1
fi

export INSTALL4J_ADD_VM_PARAMS="-Dtwslaunch.autoupdate.serviceImpl=twslaunch.autoupdate.DummyAutoUpdateService"

exec /home/ubuntu/ibgateway/ibgateway
