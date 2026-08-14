"""Shared kill-switch / control-plane for all trading bots.

The dashboard (dashboard/app.py) writes a CONTROL/system item to DynamoDB:

    {pk: 'CONTROL', sk: 'system', state: 'RUNNING'|'PAUSED'|'KILLED',
     flatten: 'true'|'false', ts: <epoch>}

Every bot reads it each run and honours it BEFORE placing any order:

  RUNNING  — normal operation.
  PAUSED   — no NEW entries; existing positions are still managed to exit.
  KILLED   — flatten every open position, cancel stops, no entries, halt.
  flatten  — one-shot: flatten every open position now (the dashboard
             'Flatten positions' button). Cleared once a bot honours it.

Fail-closed: callers treat a missing/unreadable control item as RUNNING only
when the read itself returns empty; if get_item raises, the caller must halt.
The helpers here never raise — they return empty on read error so callers can
decide (bots check `control_state` and, on KILLED, flatten and return).
"""
import time

CONTROL_PK = 'CONTROL'
CONTROL_SK = 'system'


def get_control(table):
    """Read CONTROL/system. Returns {} on any error (caller decides fail-closed)."""
    try:
        r = table.get_item(Key={'pk': CONTROL_PK, 'sk': CONTROL_SK})
        return r.get('Item') or {}
    except Exception as e:  # pragma: no cover - network failure
        print(f"[control] get_control read failed (fail-closed): {e}")
        return {}


def control_state(ctrl):
    return ctrl.get('state', 'RUNNING')


def wants_flatten(ctrl):
    return ctrl.get('flatten', 'false') == 'true' or control_state(ctrl) == 'KILLED'


def already_ran_today(table, key, today):
    """Once-per-day dedupe guard. True if RUN#<key>/<today> already exists.

    Protects against double-scheduling (two schedulers firing the same bot the
    same day), which would otherwise double-log signals and race order entry.
    Fail-open on DynamoDB read error so a transient read failure never blocks
    trading.
    """
    try:
        return bool(table.get_item(Key={'pk': f'RUN#{key}', 'sk': today}).get('Item'))
    except Exception as e:
        print(f"[control] already_ran_today read failed (fail-open): {e}")
        return False


def mark_ran_today(table, key, today):
    """Write the RUN#<key>/<today> marker so a same-day re-run is skipped."""
    try:
        table.put_item(Item={'pk': f'RUN#{key}', 'sk': today,
                             'ts': int(time.time()), 'bot': key})
    except Exception as e:
        print(f"[control] mark_ran_today failed (non-fatal): {e}")


def clear_flatten(table):
    """One-shot: reset the flatten flag after a bot honours it. Preserves state."""
    try:
        item = table.get_item(Key={'pk': CONTROL_PK, 'sk': CONTROL_SK}).get('Item')
        if item and item.get('flatten') == 'true':
            item['flatten'] = 'false'
            item['ts'] = int(time.time())
            table.put_item(Item=item)
    except Exception as e:
        print(f"[control] clear_flatten failed (non-fatal): {e}")


def flatten_ibkr(ib, symbols, table, tags, today, mode='PAPER'):
    """Cancel stops + market-close every open position for `symbols`, then reset
    the DynamoDB POSITION state for `tags` so the next run starts flat.

    This is the GLOBAL kill-switch path: flattening a shared symbol (e.g. MES)
    also closes another bot's position in the same account, which is exactly
    what an emergency flatten should do.
    """
    from ib_insync import MarketOrder

    ib.sleep(1)  # let reqPositions populate after connect
    for o in list(ib.openOrders()):
        if o.contract.symbol in symbols and o.order.orderType == 'STP':
            try:
                ib.cancelOrder(o)
            except Exception as e:
                print(f"[control] cancel stop failed ({o.contract.symbol}): {e}")
    for p in list(ib.positions()):
        if p.contract.symbol in symbols and int(p.position) != 0:
            qty = abs(int(p.position))
            action = 'SELL' if p.position > 0 else 'BUY'
            try:
                ib.placeOrder(p.contract, MarketOrder(action, qty, tif='DAY'))
            except Exception as e:
                print(f"[control] close {p.contract.symbol} failed: {e}")
    ib.sleep(1)
    for tag in tags:
        table.put_item(Item={
            'pk': f'POSITION#{tag}', 'sk': 'current',
            'pos': 0, 'side': '', 'stop': '0', 'entry': '0',
            'entry_date': '', 'session_date': today, 'ts': int(time.time()),
        })
    print(f"[control] {mode} flattened symbols={sorted(symbols)} tags={tags}")
