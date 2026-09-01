import sys, math
sys.path.insert(0, 'hardening')
from risk_firewall import (PreTradeRiskFirewall, FirewallContext, OrderIntent, Decision)

fw = PreTradeRiskFirewall()

def ctx(**kw):
    base = dict(
        system_state="RUNNING", live_authorization="ARMED", risk_permission="APPROVED",
        broker_healthy=True, data_fresh=True, market_open=True,
        max_order_notional=700.0, max_position_notional=700.0,
        daily_loss_limit=50.0, max_daily_trades=10,
        current_position_qty=0.0, current_position_notional=0.0,
        realized_daily_pnl=0.0, daily_trade_count=0,
        reference_price=100.0, max_price_deviation=0.10,
        allowed_symbols={"AAPL","MSFT"}, seen_keys=set(),
    )
    base.update(kw)
    return FirewallContext(**base)

def intent(**kw):
    base = dict(strategy="test", broker="RH", account="515821577", symbol="AAPL",
                side="buy", quantity=1.0, price=100.0, order_type="limit",
                signal_id="sig1", session="2026-09-01")
    base.update(kw)
    return OrderIntent(**base)

tests = []
def check(name, i, c, expect_decision, expect_gate=None):
    r = fw.authorize(i, c)
    ok = r.decision is expect_decision and (expect_gate is None or r.gate == expect_gate)
    tests.append((name, ok, r.gate, r.decision.name, r.reason))

# 1. happy path -> PASS
check("happy path", intent(), ctx(), Decision.PASS)

# 2. system KILLED -> FAIL
check("system KILLED", intent(), ctx(system_state="KILLED"), Decision.FAIL, "authorization")

# 3. system state UNKNOWN -> UNKNOWN (blocks)
check("system UNKNOWN", intent(), ctx(system_state="WEIRD"), Decision.UNKNOWN, "authorization")

# 4. live auth OFF -> FAIL
check("live OFF", intent(), ctx(live_authorization="OFF"), Decision.FAIL, "authorization")

# 5. risk denied -> FAIL
check("risk denied", intent(), ctx(risk_permission="DENIED"), Decision.FAIL, "authorization")

# 6. bad symbol -> FAIL
check("bad symbol", intent(symbol="PENNY"), ctx(), Decision.FAIL, "instrument")

# 7. NaN quantity -> FAIL
check("NaN qty", intent(quantity=float('nan')), ctx(), Decision.FAIL, "quantity")

# 8. Inf quantity -> FAIL
check("Inf qty", intent(quantity=float('inf')), ctx(), Decision.FAIL, "quantity")

# 9. zero quantity -> FAIL
check("zero qty", intent(quantity=0), ctx(), Decision.FAIL, "quantity")

# 10. negative quantity -> FAIL
check("neg qty", intent(quantity=-5), ctx(), Decision.FAIL, "quantity")

# 11. price deviation > 10% -> FAIL
check("price dev", intent(price=120.0), ctx(), Decision.FAIL, "price")

# 12. oversized notional (700 account trying $7000) -> FAIL
check("oversized notional", intent(quantity=70, price=100.0), ctx(), Decision.FAIL, "notional")

# 13. daily loss hit -> FAIL
check("daily loss", intent(), ctx(realized_daily_pnl=-50.0), Decision.FAIL, "daily_loss")

# 14. daily loss UNKNOWN -> UNKNOWN (blocks)
check("daily loss unknown", intent(), ctx(realized_daily_pnl=None), Decision.UNKNOWN, "daily_loss")

# 15. daily trade count hit -> FAIL
check("trade count", intent(), ctx(daily_trade_count=10), Decision.FAIL, "daily_count")

# 16. duplicate intent -> FAIL
c = ctx(); c.seen_keys.add(intent().idempotency_key())
check("duplicate", intent(), c, Decision.FAIL, "duplicate")

# 17. stale data -> FAIL
check("stale data", intent(), ctx(data_fresh=False), Decision.FAIL, "data_fresh")

# 18. market closed -> FAIL
check("market closed", intent(), ctx(market_open=False), Decision.FAIL, "session")

# 19. broker unhealthy -> FAIL
check("broker unhealthy", intent(), ctx(broker_healthy=False), Decision.FAIL, "broker_health")

# 20. market order -> notional UNKNOWN -> blocks
check("market order unknown notional", intent(order_type="market", price=None), ctx(), Decision.UNKNOWN, "notional")

# 21. position limit -> FAIL (notional $600 < $700 order cap, but > $500 position cap)
check("position limit", intent(quantity=6, price=100.0), ctx(max_position_notional=500.0), Decision.FAIL, "position")

# ---- operation classification (risk-reducing vs risk-increasing) ----
# 22. OPEN_NEW under KILLED -> FAIL
check("OPEN_NEW KILLED", intent(operation="OPEN_NEW"), ctx(system_state="KILLED"), Decision.FAIL, "authorization")
# 23. EMERGENCY_FLATTEN under KILLED + emergency GRANTED -> PASS
check("FLATTEN KILLED+granted", intent(operation="EMERGENCY_FLATTEN", side="sell"), ctx(system_state="KILLED", emergency_authorization="GRANTED"), Decision.PASS)
# 24. EMERGENCY_FLATTEN under KILLED + no grant -> FAIL
check("FLATTEN KILLED no-grant", intent(operation="EMERGENCY_FLATTEN", side="sell"), ctx(system_state="KILLED"), Decision.FAIL, "authorization")
# 25. CANCEL_ORDER under PAUSED + grant -> PASS
check("CANCEL PAUSED+granted", intent(operation="CANCEL_ORDER", side="sell"), ctx(system_state="PAUSED", emergency_authorization="GRANTED"), Decision.PASS)
# 26. OPEN_NEW under KILLED + grant -> STILL FAIL (emergency NEVER authorizes new risk)
check("OPEN_NEW KILLED+granted", intent(operation="OPEN_NEW"), ctx(system_state="KILLED", emergency_authorization="GRANTED"), Decision.FAIL, "authorization")

# summary
passed = sum(1 for _, ok, *_ in tests if ok)
for name, ok, gate, dec, reason in tests:
    print(f"{'PASS' if ok else 'FAIL'}  {name:28s} -> {gate}:{dec} ({reason[:50]})")
print(f"\n{passed}/{len(tests)} firewall red-team checks correct")
sys.exit(0 if passed == len(tests) else 1)
