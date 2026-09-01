import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hardening.order_gate import gate_order, OrderBlockedError
from hardening.state_provider import StateProvider, set_provider, StateUnavailable


class MockProvider(StateProvider):
    """Simulates the authoritative broker + market-data + clock clients."""
    def __init__(self, broker_healthy=True, pnl=0.0, trades=3, pos=(0.0, 0.0),
                 ref=100.0, data_fresh=True, market_open=True):
        self.bh, self.pnl, self.trades = broker_healthy, pnl, trades
        self.pos, self.ref = pos, ref
        self.df, self.mo = data_fresh, market_open

    def broker_healthy(self, broker): return self.bh
    def realized_daily_pnl(self, broker, account): return self.pnl
    def daily_trade_count(self, broker, account): return self.trades
    def position(self, broker, account, symbol): return self.pos
    def reference_price(self, symbol): return self.ref
    def data_fresh(self, symbol): return self.df
    def market_open(self): return self.mo


def set_auth(system="RUNNING", live="ARMED", risk="APPROVED", emergency=None):
    os.environ["SYSTEM_STATE"] = system
    os.environ["LIVE_AUTHORIZATION"] = live
    os.environ["RISK_PERMISSION"] = risk
    if emergency: os.environ["EMERGENCY_AUTHORIZATION"] = emergency
    else: os.environ.pop("EMERGENCY_AUTHORIZATION", None)

def clear_auth():
    for k in ("SYSTEM_STATE", "LIVE_AUTHORIZATION", "RISK_PERMISSION", "EMERGENCY_AUTHORIZATION"):
        os.environ.pop(k, None)

_n = [0]
def attempt(**overrides):
    _n[0] += 1
    kw = dict(strategy="strat1", broker="robinhood", account="acc", symbol="AAPL",
              side="buy", quantity=1, price=100.0, order_type="limit",
              signal_id=f"sig{_n[0]}")
    kw.update(overrides)
    gate_order(**kw)

def block(label, provider, **overrides):
    set_provider(provider)
    try:
        attempt(**overrides)
        print(f"BUG   {label}  -> ALLOWED (should block)")
    except OrderBlockedError as e:
        print(f"BLOCK {label}  -> [{e.gate}] {e.reason}")

print("=== 1. INTENDED FUTURE STATE (provider=healthy, armed) => PASS ===")
set_auth(); set_provider(MockProvider())
try:
    attempt(); print("PASS  valid order (armed + healthy) would submit")
except OrderBlockedError as e:
    print(f"FAIL  valid order -> {e}")

print("=== 2. each unsafe condition BLOCKS ===")
H = MockProvider()
set_auth("KILLED");            block("SYSTEM KILLED", H)
set_auth("PAUSED");            block("SYSTEM PAUSED", H)
set_auth("RUNNING","OFF");     block("LIVE OFF", H)
set_auth("RUNNING","ARMED","DENIED"); block("RISK DENIED", H)
set_auth(); block("data stale", MockProvider(data_fresh=False))
set_auth(); block("broker unhealthy", MockProvider(broker_healthy=False))
set_auth(); block("market closed", MockProvider(market_open=False))
set_auth(); block("position 7 held (broker truth)", MockProvider(pos=(7.0, 700.0)))
set_auth(); block("daily loss exceeded", MockProvider(pnl=-60.0))
set_auth(); block("oversized notional", H, notional=7000.0)
set_auth(); block("NaN quantity", H, quantity=float('nan'))

print("=== 3. NO PROVIDER REGISTERED (UNKNOWN) => BLOCK ===")
set_auth(); set_provider(None)
block("no provider (UNKNOWN)", None)

print("=== 4. provider raises StateUnavailable => BLOCK ===")
class Broken(StateProvider): pass
set_auth(); block("provider broken (all raise)", Broken())

print("=== 5. EMERGENCY never authorizes new risk ===")
clear_auth(); os.environ.update(SYSTEM_STATE="KILLED", EMERGENCY_AUTHORIZATION="GRANTED")
block("OPEN_NEW under KILLED+emergency", H)
clear_auth(); set_provider(None)
