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

Fail-closed: an unreadable OR missing control item must HALT the caller, never
default to RUNNING (which would let a bot trade blind). `get_control` raises
`ControlUnavailable` in both cases; bots catch it and return before any order.
"""
import os
import time

CONTROL_PK = 'CONTROL'
CONTROL_SK = 'system'

VALID_STATES = {'RUNNING', 'PAUSED', 'KILLED'}
PAPER_ACCOUNT_IDS = set(os.getenv('PAPER_ACCOUNTS', 'DUR193467').split(','))


class ControlUnavailable(Exception):
    """Control state unreadable or missing — callers must HALT (fail-closed)."""


def get_control(table):
    """Read CONTROL/system. RAISES ControlUnavailable on read error OR missing item.

    Callers must treat the exception as a halt — never trade on an unknown
    control state.
    """
    try:
        r = table.get_item(Key={'pk': CONTROL_PK, 'sk': CONTROL_SK})
    except Exception as e:  # pragma: no cover - network failure
        raise ControlUnavailable(f"control read failed: {e}") from e
    item = r.get('Item')
    if not item:
        raise ControlUnavailable("CONTROL/system item missing")
    return item


def control_state(ctrl):
    """Control state, or None if unknown/missing (fail-closed)."""
    s = ctrl.get('state')
    return s if s in VALID_STATES else None


def control_allows_entry(ctrl):
    """True only when the control plane explicitly says RUNNING (fail-closed)."""
    return control_state(ctrl) == 'RUNNING'


def account_mode_ok(mode, account_ids):
    """(ok, reason): refuse orders on account/mode mismatch (paper vs live)."""
    ids = list(account_ids or [])
    if mode == 'LIVE':
        if any(a in PAPER_ACCOUNT_IDS for a in ids):
            return False, f"PAPER account {ids} with LIVE mode — refusing orders"
        return True, "ok"
    # PAPER mode
    if any(a in PAPER_ACCOUNT_IDS for a in ids):
        return True, "ok"
    return False, f"LIVE account {ids} with PAPER mode — refusing orders"


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


def set_control(table, **fields):
    """Read-modify-write CONTROL/system, PRESERVING existing flags.

    Fixes the dashboard bug where a `Pause` click wiped a pending `flatten`
    flag (or vice-versa): only the supplied fields change, everything else
    (state, flatten, acked set, ts) is carried over.
    """
    try:
        existing = table.get_item(Key={'pk': CONTROL_PK, 'sk': CONTROL_SK}).get('Item') or {}
    except Exception as e:
        existing = {}
        print(f"[control] set_control read failed (non-fatal, will overwrite): {e}")
    item = {'pk': CONTROL_PK, 'sk': CONTROL_SK, 'ts': int(time.time())}
    item.update({k: v for k, v in existing.items() if k not in ('pk', 'sk', 'ts')})
    item.update(fields)
    table.put_item(Item=item)
    return item


BOT_KEYS = ('live', 'live_bondsfx', 'live_intraday', 'live_gc')


def ack_flatten(table, bot_key):
    """Record that `bot_key` has honoured the current flatten flag.

    The flatten flag is GLOBAL: it must persist until EVERY bot has flattened,
    not be cleared by the first bot that runs (which would leave the other bots
    blind to it). Each bot acks here after honouring it.
    """
    try:
        item = table.get_item(Key={'pk': CONTROL_PK, 'sk': CONTROL_SK}).get('Item')
        if not item or item.get('flatten') != 'true':
            return
        acked = set(item.get('flatten_acked') or [])
        acked.add(bot_key)
        item['flatten_acked'] = sorted(acked)
        item['ts'] = int(time.time())
        table.put_item(Item=item)
    except Exception as e:
        print(f"[control] ack_flatten failed (non-fatal): {e}")


def clear_flatten(table):
    """Clear the flatten flag ONLY once EVERY bot has acknowledged it."""
    try:
        item = table.get_item(Key={'pk': CONTROL_PK, 'sk': CONTROL_SK}).get('Item')
        if not item or item.get('flatten') != 'true':
            return
        acked = set(item.get('flatten_acked') or [])
        if set(BOT_KEYS) <= acked:
            item['flatten'] = 'false'
            item.pop('flatten_acked', None)
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

    MarketOrder is imported lazily: control.py is also imported by the
    dashboard, whose Streamlit ScriptRunner thread has no asyncio event loop,
    and importing ib_insync there raises at module scope.
    """
    from ib_insync import MarketOrder

    ib.sleep(1)  # let reqPositions populate after connect
    for t in list(ib.openTrades()):
        if t.contract.symbol in symbols and t.order.orderType == 'STP':
            try:
                ib.cancelOrder(t.order)
            except Exception as e:
                print(f"[control] cancel stop failed ({t.contract.symbol}): {e}")
    for p in list(ib.positions()):
        if p.contract.symbol in symbols and int(p.position) != 0:
            qty = abs(int(p.position))
            action = 'SELL' if p.position > 0 else 'BUY'
            try:
                ib.placeOrder(p.contract, MarketOrder(action, qty, tif='DAY'))
            except Exception as e:
                print(f"[control] close {p.contract.symbol} failed: {e}")

    # Never declare FLAT until the broker confirms flat. Poll positions briefly;
    # if anything is still open, leave state intact so the next run retries.
    flat = False
    remaining = []
    for _ in range(10):   # up to ~5s
        remaining = [p for p in ib.positions()
                     if p.contract.symbol in symbols and int(p.position) != 0]
        if not remaining:
            flat = True
            break
        ib.sleep(0.5)
    if not flat:
        print(f"[control] {mode} flatten NOT confirmed by broker — leaving state intact "
              f"(will retry): {[(p.contract.symbol, p.position) for p in remaining]}")
        return

    for tag in tags:
        table.put_item(Item={
            'pk': f'POSITION#{tag}', 'sk': 'current',
            'pos': 0, 'side': '', 'stop': '0', 'entry': '0',
            'entry_date': '', 'session_date': today, 'ts': int(time.time()),
        })
    print(f"[control] {mode} flattened symbols={sorted(symbols)} tags={tags}")
