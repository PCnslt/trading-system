#!/usr/bin/env python3
"""Close the RETIRED DCA fractional positions (SPY/QQQ) at the open.

Owner retired DCA on 2026-08-21 ("no set-and-hold" — wants intraday/2-3 day swings),
but the two fractional buys from 2026-08-14 were never closed:
    SPY 0.016097 @ 776.5311   QQQ 0.017134 @ 729.5050   (~$25 total)
They are also UNPROTECTED by construction: Robinhood stop orders are whole-share
only, so a 0.016-share position cannot carry a protective stop. A retired strategy's
positions left running is exactly the drift that makes a book dishonest.

Run this DURING market hours (fractional market orders need regular hours). It sells
whatever fraction is actually held — it never assumes the quantity.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TARGETS = ('SPY', 'QQQ')


def main() -> int:
    from hardening.rh_client import RHClient
    dry = '--dry-run' in sys.argv
    c = RHClient(account_number=os.getenv('RH_LIVE_ACCOUNT', '515821577'))

    held = {}
    for p in c.get_positions() or []:
        sym = str(p.get('symbol') or '').upper()
        try:
            q = float(p.get('quantity') or 0)
        except (TypeError, ValueError):
            q = 0.0
        if sym in TARGETS and q > 0:
            held[sym] = q

    if not held:
        print('nothing to close — no SPY/QQQ fractional position held')
        return 0

    print(f'closing retired DCA: {held}')
    rc = 0
    for sym, qty in held.items():
        if dry:
            print(f'  [dry] would SELL {qty} {sym} market')
            continue
        try:
            r = c.place_equity_order(sym, 'sell', 'market', quantity=str(qty),
                                     time_in_force='gfd', market_hours='regular_hours',
                                     client_order_ref=f'dca_retire_{sym}')
            print(f'  SELL {qty} {sym} -> id={r.get("id")} state={r.get("state")}')
        except Exception as e:  # noqa: BLE001
            print(f'  SELL FAILED {sym}: {e!r}')
            rc = 1

    if not dry:
        for p in c.get_positions() or []:
            sym = str(p.get('symbol') or '').upper()
            if sym in TARGETS:
                print(f'  post-check {sym}: qty={p.get("quantity")}')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
