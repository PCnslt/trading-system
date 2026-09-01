"""Pre-trade risk firewall — broker-independent choke point.

STRATEGY = proposes. RISK FIREWALL = decides. BROKER = executes.

Every order intent must pass every gate before reaching a broker. Each gate
returns PASS / FAIL / UNKNOWN. UNKNOWN is NEVER silently promoted to PASS —
uncertainty blocks new risk (NO NEW RISK).
"""
from __future__ import annotations

import hashlib, math, time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Decision(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass
class GateResult:
    gate: str
    decision: Decision
    reason: str = ""


@dataclass
class OrderIntent:
    strategy: str
    broker: str
    account: str
    symbol: str
    side: str            # buy | sell
    quantity: Any        # shares/contracts (numeric)
    price: Any | None    # limit price or None for market
    order_type: str      # market | limit | stop
    signal_id: str       # deterministic idempotency key component
    session: str = ""    # e.g. date-based session id
    notional: float | None = None   # optional; derived if None

    def idempotency_key(self) -> str:
        raw = f"{self.strategy}|{self.symbol}|{self.signal_id}|{self.session}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


@dataclass
class FirewallContext:
    """All external state the firewall needs. Provided by the caller."""
    system_state: str = "KILLED"      # KILLED | PAUSED | RUNNING
    live_authorization: str = "OFF"   # OFF | ARMED
    risk_permission: str = "DENIED"   # DENIED | APPROVED
    broker_healthy: bool = False
    data_fresh: bool = False
    market_open: bool = False
    # account limits (hard caps, independent of strategy config)
    max_order_notional: float = 0.0
    max_position_notional: float = 0.0
    max_portfolio_exposure: float = 0.0
    daily_loss_limit: float = 0.0
    max_daily_trades: int = 0
    # current account state
    current_position_qty: float = 0.0
    current_position_notional: float = 0.0
    realized_daily_pnl: float | None = None   # None = UNKNOWN
    daily_trade_count: int = 0
    # price reference for sanity check
    reference_price: float | None = None
    max_price_deviation: float = 0.10        # 10%
    # authorized instruments
    allowed_symbols: set = field(default_factory=set)
    # duplicate detection
    seen_keys: set = field(default_factory=set)


def _num(x) -> float:
    return float(x)


def _is_finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


class PreTradeRiskFirewall:
    """Order-intent -> PASS/FAIL/UNKNOWN. Broker-independent."""

    def __init__(self):
        self._gates = [
            ("control", self._g_control),
            ("live_auth", self._g_live_auth),
            ("risk_permission", self._g_risk_permission),
            ("instrument", self._g_instrument),
            ("quantity", self._g_quantity),
            ("price", self._g_price),
            ("notional", self._g_notional),
            ("position", self._g_position),
            ("daily_loss", self._g_daily_loss),
            ("daily_count", self._g_daily_count),
            ("duplicate", self._g_duplicate),
            ("data_fresh", self._g_data_fresh),
            ("session", self._g_session),
            ("broker_health", self._g_broker_health),
        ]

    def authorize(self, intent: OrderIntent, ctx: FirewallContext) -> GateResult:
        for name, fn in self._gates:
            r = fn(intent, ctx)
            if r.decision is not Decision.PASS:
                return r
        return GateResult("firewall", Decision.PASS, "all gates passed")

    # ---- gates -----------------------------------------------------------
    def _g_control(self, i, c):
        if c.system_state == "RUNNING":
            return GateResult("control", Decision.PASS)
        if c.system_state in ("KILLED", "PAUSED"):
            return GateResult("control", Decision.FAIL, f"system_state={c.system_state}")
        return GateResult("control", Decision.UNKNOWN, f"unknown system_state={c.system_state}")

    def _g_live_auth(self, i, c):
        if c.live_authorization == "ARMED":
            return GateResult("live_auth", Decision.PASS)
        if c.live_authorization == "OFF":
            return GateResult("live_auth", Decision.FAIL, "live authorization OFF")
        return GateResult("live_auth", Decision.UNKNOWN, f"unknown live_auth={c.live_authorization}")

    def _g_risk_permission(self, i, c):
        if c.risk_permission == "APPROVED":
            return GateResult("risk_permission", Decision.PASS)
        if c.risk_permission == "DENIED":
            return GateResult("risk_permission", Decision.FAIL, "risk denied")
        return GateResult("risk_permission", Decision.UNKNOWN, "risk permission unknown")

    def _g_instrument(self, i, c):
        if not i.symbol:
            return GateResult("instrument", Decision.FAIL, "empty symbol")
        if c.allowed_symbols and i.symbol not in c.allowed_symbols:
            return GateResult("instrument", Decision.FAIL, f"{i.symbol} not authorized")
        return GateResult("instrument", Decision.PASS)

    def _g_quantity(self, i, c):
        if not _is_finite(i.quantity):
            return GateResult("quantity", Decision.FAIL, f"non-finite quantity={i.quantity!r}")
        q = _num(i.quantity)
        if q <= 0:
            return GateResult("quantity", Decision.FAIL, f"non-positive quantity={q}")
        return GateResult("quantity", Decision.PASS)

    def _g_price(self, i, c):
        if i.order_type != "market" and i.price is not None:
            if not _is_finite(i.price):
                return GateResult("price", Decision.FAIL, f"non-finite price={i.price!r}")
            p = _num(i.price)
            if c.reference_price is not None and c.reference_price > 0:
                dev = abs(p - c.reference_price) / c.reference_price
                if dev > c.max_price_deviation:
                    return GateResult("price", Decision.FAIL,
                                      f"price {p} deviates {dev:.1%} from ref {c.reference_price}")
        return GateResult("price", Decision.PASS)

    def _g_notional(self, i, c):
        notional = i.notional
        if notional is None and i.price is not None and _is_finite(i.price):
            notional = _num(i.quantity) * _num(i.price)
        if notional is None:
            return GateResult("notional", Decision.UNKNOWN, "notional unknown (market order, no price)")
        if not _is_finite(notional):
            return GateResult("notional", Decision.FAIL, f"non-finite notional={notional}")
        if c.max_order_notional > 0 and notional > c.max_order_notional:
            return GateResult("notional", Decision.FAIL,
                              f"notional {notional:.2f} > max {c.max_order_notional:.2f}")
        return GateResult("notional", Decision.PASS)

    def _g_position(self, i, c):
        q = _num(i.quantity)
        new_qty = c.current_position_qty + q if i.side == "buy" else c.current_position_qty - q
        new_notional = abs(new_qty) * (i.price if i.price else 0)
        if c.max_position_notional > 0 and new_notional > c.max_position_notional:
            return GateResult("position", Decision.FAIL,
                              f"new position notional {new_notional:.2f} > max {c.max_position_notional:.2f}")
        return GateResult("position", Decision.PASS)

    def _g_daily_loss(self, i, c):
        if c.realized_daily_pnl is None:
            return GateResult("daily_loss", Decision.UNKNOWN, "daily P&L unknown")
        if c.daily_loss_limit > 0 and c.realized_daily_pnl <= -c.daily_loss_limit:
            return GateResult("daily_loss", Decision.FAIL,
                              f"daily loss {c.realized_daily_pnl:.2f} >= limit {c.daily_loss_limit:.2f}")
        return GateResult("daily_loss", Decision.PASS)

    def _g_daily_count(self, i, c):
        if c.max_daily_trades > 0 and c.daily_trade_count >= c.max_daily_trades:
            return GateResult("daily_count", Decision.FAIL,
                              f"daily trades {c.daily_trade_count} >= max {c.max_daily_trades}")
        return GateResult("daily_count", Decision.PASS)

    def _g_duplicate(self, i, c):
        key = i.idempotency_key()
        if key in c.seen_keys:
            return GateResult("duplicate", Decision.FAIL, f"duplicate intent {key}")
        return GateResult("duplicate", Decision.PASS)

    def _g_data_fresh(self, i, c):
        if not c.data_fresh:
            return GateResult("data_fresh", Decision.FAIL, "data stale")
        return GateResult("data_fresh", Decision.PASS)

    def _g_session(self, i, c):
        if not c.market_open:
            return GateResult("session", Decision.FAIL, "market closed")
        return GateResult("session", Decision.PASS)

    def _g_broker_health(self, i, c):
        if not c.broker_healthy:
            return GateResult("broker_health", Decision.FAIL, "broker unhealthy")
        return GateResult("broker_health", Decision.PASS)


def record_duplicate(ctx: FirewallContext, intent: OrderIntent) -> None:
    """Call after a successful submit so a retry of the same intent is caught."""
    ctx.seen_keys.add(intent.idempotency_key())
