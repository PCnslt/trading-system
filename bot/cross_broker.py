"""Cross-broker position de-duplication.

The Robinhood lane (`RHPOS#<SYM>`) and the IBKR lane (`POSITION#<SYM>_RSI2`) run the
same RSI(2) signal over overlapping universes, so without a shared check they will
BOTH buy the same name on the same morning and silently double the intended exposure.
Observed 2026-08-24: BB was simultaneously a Robinhood signal (rsi2=0.40) and the #2
IBKR pick.

Same signal on two brokers is not diversification — it is one position at 2x size,
with two separate stops that each protect only their own half. Whichever lane runs
first wins the name; the second skips it.

Cheap by design: point get_item lookups (no scans) so it can be called per symbol
inside the entry loop.
"""
from __future__ import annotations

OPEN_STATES = ('PENDING', 'OPEN')

RH_KEY = 'RHPOS#{sym}'
IBKR_KEY = 'POSITION#{sym}_RSI2'


def _is_open(item: dict | None) -> bool:
    if not item:
        return False
    status = str(item.get('status') or '').upper()
    # IBKR rows historically omit 'status' and are deleted on exit; treat a
    # present row as open unless it explicitly says CLOSED.
    return status in OPEN_STATES or (status == '' and bool(item))


def _get(table, pk: str) -> dict | None:
    try:
        return table.get_item(Key={'pk': pk, 'sk': 'current'}).get('Item')
    except Exception:  # noqa: BLE001 - a read failure must not fake "free to trade"
        raise


def held_by_rh(table, sym: str) -> bool:
    return _is_open(_get(table, RH_KEY.format(sym=sym.upper())))


def held_by_ibkr(table, sym: str) -> bool:
    return _is_open(_get(table, IBKR_KEY.format(sym=sym.upper())))


def blocked_by_other_broker(table, sym: str, lane: str) -> tuple[bool, str]:
    """(blocked, reason) — True when the OTHER broker already holds this symbol.

    ``lane`` is 'rh' or 'ibkr': the caller's own lane, which is never self-blocking.
    FAIL-CLOSED: if the lookup raises, report blocked rather than risk doubling up.
    """
    lane = lane.lower()
    if lane not in ('rh', 'ibkr'):
        raise ValueError(f"lane must be 'rh' or 'ibkr', got {lane!r}")
    try:
        if lane == 'rh' and held_by_ibkr(table, sym):
            return True, f'{sym} already held by the IBKR lane — cross-broker de-dup'
        if lane == 'ibkr' and held_by_rh(table, sym):
            return True, f'{sym} already held by the Robinhood lane — cross-broker de-dup'
    except Exception as e:  # noqa: BLE001
        return True, f'{sym} cross-broker check failed ({e!r}) — skipping (fail-closed)'
    return False, ''
