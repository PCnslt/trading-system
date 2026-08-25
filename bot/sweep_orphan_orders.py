#!/usr/bin/env python3
"""Pre-open ORPHAN ORDER SWEEP — cancel broker orders the book doesn't own.

WHY THIS EXISTS (2026-08-24, real incident):
    The old place_equity_entry raised RHOrderError as soon as the creation response
    was not already 'filled' — WITHOUT cancelling the order it had just sent. So on
    2026-08-24 nine live market BUY orders (VSH, ESI, FHN, ONB, BB x4, COLB, FNB,
    BLZE x2, EBC — ~$254 notional on a $700 account) sat QUEUED at Robinhood with:
      * no protective stop (the code raised before the stop was placed), and
      * no POSITION/RHPOS row (so no bot would ever manage or exit them).
    They would have filled at the next open as untracked, unprotected longs.

    place_equity_entry now cancels on timeout, so that specific path is closed. This
    sweep is the belt-and-braces: ANY resting entry order with no book row is an
    unmanaged position waiting to happen, whatever produced it.

WHAT IT DOES
    For every live/resting equity order on the account:
      * keep protective stop orders that match an OPEN book position
      * keep entry orders that match an OPEN/PENDING book position
      * CANCEL everything else, loudly
    Read-only unless it finds an orphan. Safe to run repeatedly.

USAGE
    python bot/sweep_orphan_orders.py --dry-run     # report only
    python bot/sweep_orphan_orders.py               # cancel orphans
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESTING = ('queued', 'confirmed', 'new', 'partially_filled', 'pending', 'unconfirmed')
STOP_TYPES = ('stop_market', 'stop_limit')


def load_open_book(table) -> dict:
    """{SYM: item} for Robinhood positions the system believes it holds."""
    book = {}
    lek = None
    while True:
        kw = dict(FilterExpression='begins_with(pk, :p)',
                  ExpressionAttributeValues={':p': 'RHPOS#'})
        if lek:
            kw['ExclusiveStartKey'] = lek
        resp = table.scan(**kw)
        for it in resp.get('Items', []):
            if it.get('sk') == 'current' and str(it.get('status', '')).upper() in ('PENDING', 'OPEN'):
                book[it['pk'].split('#', 1)[1].upper()] = it
        lek = resp.get('LastEvaluatedKey')
        if not lek:
            break
    return book


def load_broker_positions(client) -> dict:
    """{SYM: qty} for positions the BROKER actually reports (qty > 0).

    This is the authoritative held-check. The bot's RHPOS# book is NOT: on
    2026-08-25 nine entries filled at the broker while the confirm path failed, so
    the book was EMPTY while nine real positions existed. Deciding "orphan" from the
    book would have cancelled all nine protective stops and left the positions naked.
    """
    out = {}
    for p in (client.get_positions() or []):
        try:
            q = float(p.get('quantity') or 0)
        except (TypeError, ValueError):
            q = 0.0
        if q > 0 and p.get('symbol'):
            out[str(p['symbol']).upper()] = q
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--account', default=os.getenv('RH_LIVE_ACCOUNT', '515821577'))
    ap.add_argument('--symbols', default='',
                    help='comma list to check; default = book symbols + todays signals')
    args = ap.parse_args()

    import boto3
    from hardening.rh_client import RHClient

    table = boto3.resource('dynamodb', region_name=os.getenv('AWS_REGION', 'us-east-1')) \
        .Table(os.getenv('DYNAMODB_TABLE', 'trading-data'))
    client = RHClient(account_number=args.account)

    book = load_open_book(table)
    print(f'book: {len(book)} open/pending RH positions {sorted(book) if book else ""}')
    try:
        broker = load_broker_positions(client)
    except Exception as e:  # noqa: BLE001
        # FAIL-CLOSED: without the authoritative position list we cannot tell an
        # orphan from a protective stop. Cancelling blind could strip every stop.
        print(f'BROKER POSITION READ FAILED ({e!r}) — refusing to cancel anything')
        return 1
    print(f'broker: {len(broker)} real positions {sorted(broker) if broker else ""}')
    only_broker = sorted(set(broker) - set(book))
    if only_broker:
        print(f'  NOTE: held at broker but MISSING from the bot book: {only_broker} '
              f'— their stops are PROTECTIVE, not orphans')

    # Which symbols to inspect: the book, plus anything the account has a position
    # row for (Robinhood creates a 0-qty row for every symbol it has ever ordered).
    syms = set(s.strip().upper() for s in args.symbols.split(',') if s.strip())
    if not syms:
        syms |= set(book)
        try:
            for p in client.get_positions() or []:
                if p.get('symbol'):
                    syms.add(str(p['symbol']).upper())
        except Exception as e:  # noqa: BLE001
            print(f'position read failed: {e!r}')
    print(f'inspecting {len(syms)} symbols')

    orphans, kept = [], 0
    for sym in sorted(syms):
        try:
            orders = client.list_orders(symbol=sym) or []
        except Exception as e:  # noqa: BLE001
            print(f'  {sym}: order read FAILED {e!r} — skipping (not cancelling blind)')
            continue
        for o in orders:
            state = str(o.get('state') or '').lower()
            if state not in RESTING:
                continue
            otype = str(o.get('type') or '')
            is_stop = (o.get('stop_price') not in (None, '', '0', '0.000000')
                       or otype in STOP_TYPES)
            # AUTHORITATIVE held-check = the broker. A resting stop on a symbol we
            # really own is PROTECTION; cancelling it strips the never-naked
            # guarantee. The bot book is advisory only (it can be empty while real
            # positions exist — see load_broker_positions docstring).
            held_broker = sym in broker
            held_book = sym in book
            if held_broker:
                kept += 1
                tag = '' if held_book else ' [broker-only: book is stale]'
                print(f'  KEEP   {sym:6} {otype:12} {state:12} '
                      f'(REAL broker position{tag})')
            elif held_book:
                # book says we hold it, broker says we do not: do NOT cancel on a
                # possibly-stale book, but make the divergence loud.
                kept += 1
                print(f'  KEEP   {sym:6} {otype:12} {state:12} — DIVERGENCE: in book '
                      f'but NOT at broker; investigate before cancelling')
            elif is_stop and o.get('side') == 'sell':
                orphans.append((sym, o.get('id'), otype, o.get('side'),
                                o.get('quantity'), state))
                print(f'  ORPHAN {sym:6} {otype:12} {state:12} side=sell '
                      f'stop={o.get("stop_price")} qty={o.get("quantity")} — no position '
                      f'anywhere; a trigger here would SHORT the account')
            else:
                orphans.append((sym, o.get('id'), otype, o.get('side'),
                                o.get('quantity'), state))
                print(f'  ORPHAN {sym:6} {otype:12} {state:12} side={o.get("side")} '
                      f'qty={o.get("quantity")} — NO position at broker or in book')

    print(f'\nkept={kept} orphans={len(orphans)}')
    if not orphans:
        print('clean: no unmanaged resting orders')
        return 0
    if args.dry_run:
        print('DRY-RUN: would cancel the orphans above')
        return 0

    failed = []
    for sym, oid, otype, side, qty, state in orphans:
        try:
            client.cancel_order(oid)
            print(f'  cancelled {sym} {otype} {oid}')
        except Exception as e:  # noqa: BLE001
            failed.append((sym, oid, repr(e)))
            print(f'  CANCEL FAILED {sym} {oid}: {e!r}')
        time.sleep(0.3)

    # verify
    still = []
    for sym, oid, *_ in orphans:
        try:
            for o in client.list_orders(symbol=sym) or []:
                if str(o.get('id')) == str(oid) and str(o.get('state') or '').lower() in RESTING:
                    still.append((sym, oid))
        except Exception:  # noqa: BLE001
            still.append((sym, oid))
    if still or failed:
        print(f'\nSTILL RESTING AFTER CANCEL: {still} failed={failed}')
        return 1
    print('\nverified: all orphans cancelled, zero unmanaged exposure')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
