#!/usr/bin/env python3
"""Per-second trailing stop + trailing take-profit monitor (custom, broker-agnostic).

Robinhood has no native option trailing stops, so this polls price every N seconds,
tracks the running peak, and fires a sell when price retraces trail_stop% from the
peak (stop) or trail_tp% from the peak (profit-lock). Reusable for stocks OR options.

Usage:
  python bot/trailing_monitor.py SYM QTY ENTRY --stop 15 --tp 20 --interval 1 --dry-run
"""
import os, sys, time, json, argparse
import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')


def _price(sym, rh):
    q = rh.get_quotes([sym])
    p = q.get(sym, {}).get('last_trade_price') or q.get(sym, {}).get('mark')
    return float(p) if p else None


def _sell(sym, qty, rh, dry):
    if dry:
        return {'dry': True}
    return rh.place_equity_order(symbol=sym, side='sell', order_type='market',
                                 quantity=str(qty))


def run(sym, qty, entry, stop_pct, tp_pct, interval, dry, max_sec):
    sys.path.insert(0, '/home/ubuntu/trading-system')
    os.chdir('/home/ubuntu/trading-system')
    from dotenv import load_dotenv
    load_dotenv('.env')
    from infra.ssm_secrets import bootstrap
    bootstrap()
    from hardening.rh_client import RHClient
    rh = RHClient()

    peak = entry
    start = time.time()
    print(f'[trail] {sym} qty={qty} entry={entry:.4f} stop={stop_pct}% tp={tp_pct}% '
          f'int={interval}s dry={dry}')
    while time.time() - start < max_sec:
        px = _price(sym, rh)
        if px is None:
            time.sleep(interval)
            continue
        if px > peak:
            peak = px
        ret = (px - entry) / entry
        stop = peak * (1 - stop_pct / 100)
        tp = peak * (1 - tp_pct / 100)
        reason = None
        if px <= stop:
            reason = f'STOP  px={px:.4f} <= {stop:.4f} (peak {peak:.4f})'
        elif px >= entry * (1 + tp_pct / 100) and px <= tp:
            reason = f'TRAIL-TP px={px:.4f} <= {tp:.4f} (locked from peak {peak:.4f})'
        if reason:
            r = _sell(sym, qty, rh, dry)
            print(f'[trail] {reason} -> {r}')
            return reason, px, peak
        if int(time.time() - start) % 10 == 0:
            print(f'[trail] {sym} px={px:.4f} peak={peak:.4f} ret={ret*100:+.2f}% '
                  f'stop={stop:.4f} tp={tp:.4f}')
        time.sleep(interval)
    print('[trail] max runtime reached — no trigger')
    return None, None, peak


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('sym'); ap.add_argument('qty', type=float); ap.add_argument('entry', type=float)
    ap.add_argument('--stop', type=float, default=15.0)
    ap.add_argument('--tp', type=float, default=20.0)
    ap.add_argument('--interval', type=float, default=1.0)
    ap.add_argument('--max-sec', type=float, default=3600.0)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    run(a.sym, a.qty, a.entry, a.stop, a.tp, a.interval, a.dry_run, a.max_sec)
