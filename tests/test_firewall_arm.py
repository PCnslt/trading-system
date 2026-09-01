import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hardening.order_gate import gate_order, OrderBlockedError

HEALTHY = dict(broker_healthy=True, data_fresh=True, market_open=True,
               realized_daily_pnl=0.0, daily_trade_count=3,
               current_position_qty=0.0, current_position_notional=0.0,
               reference_price=100.0)

def set_auth(system="RUNNING", live="ARMED", risk="APPROVED", emergency=None):
    os.environ["SYSTEM_STATE"] = system
    os.environ["LIVE_AUTHORIZATION"] = live
    os.environ["RISK_PERMISSION"] = risk
    if emergency:
        os.environ["EMERGENCY_AUTHORIZATION"] = emergency
    else:
        os.environ.pop("EMERGENCY_AUTHORIZATION", None)

def clear_auth():
    for k in ("SYSTEM_STATE", "LIVE_AUTHORIZATION", "RISK_PERMISSION",
              "EMERGENCY_AUTHORIZATION"):
        os.environ.pop(k, None)

def attempt(dynamic, **overrides):
    kw = dict(strategy="strat1", broker="robinhood", account="acc",
              symbol="AAPL", side="buy", quantity=1, price=100.0,
              order_type="limit", signal_id="k1")
    kw.update(overrides)
    kw["dynamic"] = dynamic
    gate_order(**kw)

def block(label, dynamic, **overrides):
    try:
        attempt(dynamic, **overrides)
        print(f"BUG   {label}  -> ALLOWED (should block)")
    except OrderBlockedError as e:
        print(f"BLOCK {label}  -> [{e.gate}] {e.reason}")

print("=== 1. INTENDED FUTURE STATE: RUNNING+ARMED+APPROVED+healthy => PASS ===")
set_auth()
try:
    attempt(HEALTHY)
    print("PASS  valid order (armed + healthy) would submit")
except OrderBlockedError as e:
    print(f"FAIL  valid order -> {e}")

print("=== 2. each unsafe condition BLOCKS ===")
set_auth("KILLED");            block("SYSTEM KILLED", HEALTHY)
set_auth("PAUSED");            block("SYSTEM PAUSED", HEALTHY)
set_auth("RUNNING", "OFF");    block("LIVE OFF", HEALTHY)
set_auth("RUNNING", "ARMED", "DENIED"); block("RISK DENIED", HEALTHY)
set_auth();                    block("data stale", {**HEALTHY, "data_fresh": False})
set_auth();                    block("broker unhealthy", {**HEALTHY, "broker_healthy": False})
set_auth();                    block("market closed", {**HEALTHY, "market_open": False})
set_auth();                    block("position limit (7 held, buy 1 -> $800 > $700)",
                                     {**HEALTHY, "current_position_qty": 7.0})
set_auth();                    block("daily loss exceeded", {**HEALTHY, "realized_daily_pnl": -60.0})
set_auth();                    block("oversized notional", HEALTHY, notional=7000.0)
set_auth();                    block("NaN quantity", HEALTHY, quantity=float('nan'))
set_auth();                    block("duplicate signal", HEALTHY, signal_id="k1")

print("=== 3. UNKNOWN state (disarmed, no dynamic) => BLOCK ===")
clear_auth()
block("UNKNOWN everything (disarmed)", None)

print("=== 4. EMERGENCY never authorizes new risk ===")
clear_auth(); os.environ.update(SYSTEM_STATE="KILLED", EMERGENCY_AUTHORIZATION="GRANTED")
block("OPEN_NEW under KILLED+emergency", HEALTHY)
clear_auth()
