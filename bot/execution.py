"""Minimal execution helpers — fill verification (seed of the future execution manager).

A strategy expresses intent; only a CONFIRMED broker fill may be written to state.
These helpers keep the bots from desyncing POSITION on rejection, partial fill,
or market-closed.
"""
import time


def confirm_fill(ib, trade, timeout=8.0):
    """Block until `trade` reaches a terminal state; return (filled_qty, avg_px, status).

    filled_qty=0 means nothing confirmed filled (rejected / cancelled / timeout).
    Callers MUST NOT write a POSITION off an unconfirmed fill.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = trade.orderStatus.status
        if status == 'Filled':
            fills = trade.fills
            qty = int(sum(f.execution.shares for f in fills)) if fills else 0
            if qty:
                avg = sum(f.execution.price * f.execution.shares for f in fills) / qty
            else:
                avg = 0.0
            return qty, avg, status
        if status in ('Cancelled', 'ApiCancelled', 'Inactive', 'Rejected'):
            return 0, 0.0, status
        ib.sleep(0.25)
    return 0, 0.0, getattr(trade.orderStatus, 'status', None) or 'PendingSubmit'
