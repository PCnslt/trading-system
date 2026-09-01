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

# Process-persistent idempotency set. A retry of the same intent (signal_id +
# session + symbol + side) within this process is caught here. Cross-process /
# cross-restart dedup requires the broker-side idempotency (client_order_ref /
# intent_id) + the DynamoDB order-state store — the firewall layer is a
# defense-in-depth check, not the sole duplicate authority.
_SEEN_KEYS: set = set()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def build_context(broker: str, account: str, symbol: str,
                  dynamic: dict | None = None) -> FirewallContext:
    """Build the firewall context from authoritative control state + hard caps.

    STATIC (config) vs DYNAMIC (live state) separation:

    - SYSTEM_STATE / LIVE_AUTHORIZATION / RISK_PERMISSION / limits / allowed
      symbols are *static*: read from the authoritative control plane (env or
      DynamoDB), fail-closed (KILLED/OFF/DENIED) when absent.

    - broker_healthy / data_fresh / market_open / realized_daily_pnl /
      daily_trade_count / current_position / reference_price are *dynamic*:
      supplied by the live broker + market-data clients via `dynamic`.
      When `dynamic` is absent, they stay UNKNOWN/false -> BLOCK (fail-closed).
      When `dynamic` is present (real clients), they carry real values and a
      valid order can PASS. This is what makes the system tradeable when
      deliberately armed WITHOUT weakening the safe-when-disabled default.
    """
    d = dynamic or {}

    def _dyn(key, default):
        return d.get(key, default)

    system_state = os.getenv("SYSTEM_STATE", "KILLED").strip().upper()
    live_auth = os.getenv("LIVE_AUTHORIZATION", "OFF").strip().upper()
    risk = os.getenv("RISK_PERMISSION", "DENIED").strip().upper()

    return FirewallContext(
        system_state=system_state,
        live_authorization=live_auth,
        risk_permission=risk,
        emergency_authorization=os.getenv("EMERGENCY_AUTHORIZATION", "NONE").strip().upper(),
        # dynamic live state — UNKNOWN/false unless a real client supplies it
        broker_healthy=bool(_dyn("broker_healthy", False)),
        data_fresh=bool(_dyn("data_fresh", False)),
        market_open=bool(_dyn("market_open", False)),
        realized_daily_pnl=_dyn("realized_daily_pnl", None),
        daily_trade_count=int(_dyn("daily_trade_count", 0) or 0),
        current_position_qty=float(_dyn("current_position_qty", 0.0) or 0.0),
        current_position_notional=float(_dyn("current_position_notional", 0.0) or 0.0),
        reference_price=_dyn("reference_price", None),
        # static hard caps (independent of strategy config). $700 defaults.
        max_order_notional=_env_float("MAX_ORDER_NOTIONAL", 700.0),
        max_position_notional=_env_float("MAX_POSITION_NOTIONAL", 700.0),
        max_portfolio_exposure=_env_float("MAX_PORTFOLIO_EXPOSURE", 700.0),
        daily_loss_limit=_env_float("DAILY_LOSS_LIMIT", 50.0),
        max_daily_trades=int(_env_float("MAX_DAILY_TRADES", 100)),
        max_price_deviation=_env_float("MAX_PRICE_DEVIATION", 0.10),
        allowed_symbols=_allowed_symbols(),
        seen_keys=_SEEN_KEYS,
    )


def _allowed_symbols() -> set:
    raw = os.getenv("ALLOWED_SYMBOLS", "")
    if not raw.strip():
        return set()   # empty = allow any (instrument gate passes)
    return {s.strip().upper() for s in raw.split(",") if s.strip()}


def gate_order(strategy: str, broker: str, account: str, symbol: str, side: str,
               quantity, price, order_type: str, signal_id: str = "",
               session: str = "", notional: float | None = None,
               operation: str = "OPEN_NEW", dynamic: dict | None = None) -> None:
    """Enforce the firewall. Raises OrderBlockedError unless PASS."""
    intent = OrderIntent(
        strategy=strategy, broker=broker, account=account, symbol=symbol,
        side=side, quantity=quantity, price=price, order_type=order_type,
        signal_id=signal_id, session=session, notional=notional,
        operation=operation,
    )
    ctx = build_context(broker, account, symbol, dynamic=dynamic)
    r = _fw.authorize(intent, ctx)
    if r.decision is not Decision.PASS:
        raise OrderBlockedError(r.gate, r.decision.value, r.reason)
    # Record the idempotency key so a duplicate intent is caught on the next call.
    _SEEN_KEYS.add(intent.idempotency_key())
