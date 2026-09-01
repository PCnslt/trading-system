"""Order gate — the single enforcement boundary before any broker submission.

Every broker primitive MUST call gate_order() immediately before reaching the
broker API. gate_order() builds a FirewallContext from the current control state
and hard account limits, runs the PreTradeRiskFirewall, and raises
OrderBlockedError unless the decision is PASS.

Fail-closed by default: system_state=KILLED, live_authorization=OFF,
risk_permission=DENIED unless explicitly armed.
"""
from __future__ import annotations

import os
from .risk_firewall import (PreTradeRiskFirewall, FirewallContext, OrderIntent, Decision)


class OrderBlockedError(Exception):
    def __init__(self, gate: str, decision: str, reason: str):
        self.gate, self.decision, self.reason = gate, decision, reason
        super().__init__(f"order blocked at [{gate}] {decision}: {reason}")


_fw = PreTradeRiskFirewall()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def build_context(broker: str, account: str, symbol: str) -> FirewallContext:
    """Build the firewall context from authoritative control state + hard caps.

    Fail-closed: any missing/unknown state defaults to the blocking value
    (KILLED / OFF / DENIED / unhealthy / stale).
    """
    # authoritative system state: prefer the control plane, fall back to env (blocking)
    system_state = os.getenv("SYSTEM_STATE", "KILLED").strip().upper()
    live_auth = os.getenv("LIVE_AUTHORIZATION", "OFF").strip().upper()
    risk = os.getenv("RISK_PERMISSION", "DENIED").strip().upper()

    # hard account caps (independent of strategy config). $700 defaults.
    return FirewallContext(
        system_state=system_state,
        live_authorization=live_auth,
        risk_permission=risk,
        broker_healthy=os.getenv("BROKER_HEALTHY", "false").strip().lower() == "true",
        data_fresh=os.getenv("DATA_FRESH", "false").strip().lower() == "true",
        market_open=os.getenv("MARKET_OPEN", "false").strip().lower() == "true",
        max_order_notional=_env_float("MAX_ORDER_NOTIONAL", 700.0),
        max_position_notional=_env_float("MAX_POSITION_NOTIONAL", 700.0),
        max_portfolio_exposure=_env_float("MAX_PORTFOLIO_EXPOSURE", 700.0),
        daily_loss_limit=_env_float("DAILY_LOSS_LIMIT", 50.0),
        max_daily_trades=int(_env_float("MAX_DAILY_TRADES", 100)),
        current_position_qty=0.0,
        current_position_notional=0.0,
        realized_daily_pnl=None,   # UNKNOWN -> blocks new risk (fail-closed)
        daily_trade_count=0,
        reference_price=None,
        max_price_deviation=_env_float("MAX_PRICE_DEVIATION", 0.10),
        allowed_symbols=_allowed_symbols(),
        seen_keys=set(),
    )


def _allowed_symbols() -> set:
    raw = os.getenv("ALLOWED_SYMBOLS", "")
    if not raw.strip():
        return set()   # empty = allow any (instrument gate passes)
    return {s.strip().upper() for s in raw.split(",") if s.strip()}


def gate_order(strategy: str, broker: str, account: str, symbol: str, side: str,
               quantity, price, order_type: str, signal_id: str = "",
               session: str = "", notional: float | None = None) -> None:
    """Enforce the firewall. Raises OrderBlockedError unless PASS."""
    intent = OrderIntent(
        strategy=strategy, broker=broker, account=account, symbol=symbol,
        side=side, quantity=quantity, price=price, order_type=order_type,
        signal_id=signal_id, session=session, notional=notional,
    )
    ctx = build_context(broker, account, symbol)
    r = _fw.authorize(intent, ctx)
    if r.decision is not Decision.PASS:
        raise OrderBlockedError(r.gate, r.decision.value, r.reason)
