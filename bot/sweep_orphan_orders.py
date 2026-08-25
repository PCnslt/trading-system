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
            held = sym in book
            if held:
                kept += 1
                print(f'  KEEP   {sym:6} {otype:12} {state:12} (book position exists)')
            else:
                orphans.append((sym, o.get('id'), otype, o.get('side'), o.get('quantity'), state))
                print(f'  ORPHAN {sym:6} {otype:12} {state:12} side={o.get("side")} '
                      f'qty={o.get("quantity")} — NO book position')

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
