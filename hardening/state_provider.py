"""Authoritative state provider — the ONLY source of dynamic firewall state.

The firewall must not trust the strategy (or any caller) to claim
broker_healthy=True, data_fresh=True, market_open=True, pnl=0, etc.

Those values must originate from authoritative infrastructure:

    BROKER / MARKET DATA / CLOCK  ->  AUTHORITATIVE STATE  ->  FIREWALL  ->  ORDER

This module defines the interface and a process-wide singleton. The live
broker client + market-data client + session calendar register themselves via
set_provider(). Until a real provider is registered, every value is UNKNOWN ->
the firewall fails closed.

A caller (strategy) can NEVER pass dynamic state to the firewall. It only
passes the order intent. The firewall pulls state from this provider.
"""

from __future__ import annotations


class StateUnavailable(Exception):
    """Raised by a provider method when it cannot authoritatively answer."""


class StateProvider:
    """Abstract authoritative state source. Every method may raise
    StateUnavailable -> the firewall treats that as UNKNOWN -> BLOCK."""

    # ---- broker connectivity ----
    def broker_healthy(self, broker: str) -> bool:
        raise StateUnavailable(f"no broker health source for {broker}")

    # ---- account-level realized P&L (daily loss) ----
    def realized_daily_pnl(self, broker: str, account: str) -> float:
        raise StateUnavailable("no account P&L source")

    def daily_trade_count(self, broker: str, account: str) -> int:
        raise StateUnavailable("no trade-count source")

    # ---- broker-truth position ----
    def position(self, broker: str, account: str, symbol: str) -> tuple[float, float]:
        """Return (quantity, notional). Broker is the source of truth."""
        raise StateUnavailable("no broker position source")

    # ---- market data ----
    def reference_price(self, symbol: str) -> float:
        raise StateUnavailable("no market-data source")

    def data_fresh(self, symbol: str) -> bool:
        raise StateUnavailable("no data-freshness source")

    # ---- session / clock ----
    def market_open(self) -> bool:
        raise StateUnavailable("no session/calendar source")


# Process-wide authoritative provider. None until a real client registers.
_provider: StateProvider | None = None


def set_provider(p: StateProvider) -> None:
    """Register the authoritative state provider (broker + data + clock clients)."""
    global _provider
    _provider = p


def get_provider() -> StateProvider | None:
    return _provider


def _safe(fn):
    """Call a provider method; convert any failure/absence to None (UNKNOWN)."""
    if _provider is None:
        return None
    try:
        return fn(_provider)
    except StateUnavailable:
        return None
    except Exception:
        return None


def query_dynamic(broker: str, account: str, symbol: str) -> dict:
    """Build the dynamic-state dict from the authoritative provider.

    Every value is None/false unless the provider authoritatively supplies it.
    """
    return {
        "broker_healthy": bool(_safe(lambda p: p.broker_healthy(broker))),
        "realized_daily_pnl": _safe(lambda p: p.realized_daily_pnl(broker, account)),
        "daily_trade_count": _safe(lambda p: p.daily_trade_count(broker, account)) or 0,
        "market_open": bool(_safe(lambda p: p.market_open())),
        "reference_price": _safe(lambda p: p.reference_price(symbol)),
        "data_fresh": bool(_safe(lambda p: p.data_fresh(symbol))),
        # position: broker truth. (qty, notional) or None.
        "_position": _safe(lambda p: p.position(broker, account, symbol)),
    }
