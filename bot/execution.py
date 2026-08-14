"""Minimal execution helpers — fill verification (seed of the future execution manager).

A strategy expresses intent; only a CONFIRMED broker fill may be written to state.
These helpers keep the bots from desyncing POSITION on rejection, partial fill,
or market-closed.
"""
import time


def _summarize(trade):
    """Return (filled_qty, avg_px) from broker-reported fills (not local state)."""
    fills = trade.fills
    qty = int(sum(f.execution.shares for f in fills)) if fills else 0
    if qty:
        avg = sum(f.execution.price * f.execution.shares for f in fills) / qty
    else:
        avg = 0.0
    return qty, avg


def confirm_fill(ib, trade, timeout=8.0):
    """Block until `trade` reaches a terminal state; return (filled_qty, avg_px, status).

    filled_qty is the broker-confirmed filled quantity (0 if nothing filled).
    Callers MUST NOT write a POSITION off an unconfirmed fill; on partial fill
    write only the actual filled qty.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = trade.orderStatus.status
        if status == 'Filled':
            qty, avg = _summarize(trade)
            return qty, avg, status
        if status in ('Cancelled', 'ApiCancelled', 'Inactive', 'Rejected'):
            # Terminal but may have partially filled first -> report actual qty.
            qty, avg = _summarize(trade)
            return qty, avg, status
        ib.sleep(0.25)
    # Timeout -> UNKNOWN. Report any broker-confirmed partial fill (may be 0).
    qty, avg = _summarize(trade)
    return qty, avg, getattr(trade.orderStatus, 'status', None) or 'PendingSubmit'
