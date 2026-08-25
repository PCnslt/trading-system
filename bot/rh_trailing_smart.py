#!/usr/bin/env python3
"""Robinhood SMART trailing stop — activation-gated ratchet, verify-first.

WHY THE OLD ONE WAS DISABLED
bot/rh_trailing.py trailed a chandelier (peak - 2*ATR) from the moment of entry.
Measured WORSE than a fixed 2xATR stop (PF 1.269 vs 1.319 @5bps), because RSI(2)
mean-reversion holds 1-5 days and needs room: tightening during the initial
drawdown exits the trade right before the reversion it is betting on.

WHAT IS DIFFERENT HERE
The stop is left EXACTLY as the validated fixed 2xATR until the trade has actually
earned the right to be protected, then it ratchets in stages and never loosens:

  stage 0  INITIAL   : untouched fixed 2xATR stop           (preserves the edge)
  stage 1  BREAKEVEN : once profit >= ARM_ATR * ATR  ->  stop = entry + fee buffer
  stage 2  TRAIL     : once profit >= TRAIL_START_ATR * ATR ->
                       stop = peak - TRAIL_ATR * ATR
Ratchet-only-up, and a move must improve the stop by >= MIN_STEP_ATR * ATR to be
worth an order (prevents churn and RH order spam).

VERIFY-FIRST (owner requirement: "make sure something is trading before applying
a stop loss"). Before touching any stop, every one of these must hold:
  * the broker reports a LONG position for the symbol with quantity >= 1
  * whole-share quantity (RH stops are whole-share only)
  * the position's shares are actually there (available + held_for_sells >= qty)
A symbol with no confirmed position is NEVER given a stop, and an ORPHAN stop
(resting stop, no position) is CANCELLED — an untriggered orphan sell-stop can
short the account.

Stop detection uses the REAL Robinhood shape: type='market' + trigger='stop' +
stop_price, state='confirmed'. Matching type=='stop_market' finds nothing.

  python bot/rh_trailing_smart.py --dry-run    # report only
  python bot/rh_trailing_smart.py             # place/replace stops
"""
from __future__ import annotations
import argparse, os, sys, time
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap as _sb
_sb()

import boto3
from hardening.rh_client import RHClient

NY = ZoneInfo('America/New_York')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

ARM_ATR = float(os.getenv('RH_TRAIL_ARM_ATR', '1.0'))          # profit to lock breakeven
TRAIL_START_ATR = float(os.getenv('RH_TRAIL_START_ATR', '2.0'))  # profit to begin trailing
TRAIL_ATR = float(os.getenv('RH_TRAIL_ATR', '2.0'))            # trail distance from peak
MIN_STEP_ATR = float(os.getenv('RH_TRAIL_MIN_STEP_ATR', '0.25'))
FEE_BUFFER_BP = float(os.getenv('RH_TRAIL_FEE_BP', '5'))       # breakeven incl. costs
RESTING = ('confirmed', 'queued', 'unconfirmed', 'partially_filled')


def log(m):
    print(f'[{dt.datetime.now(NY).strftime("%H:%M:%S")}] {m}', flush=True)


def is_resting_stop(o):
    return (o.get('side') == 'sell'
            and o.get('stop_price') not in (None, '', '0', '0.000000')
            and (o.get('state') or '').lower() in RESTING)


def _f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def verify_tradeable(p):
    """(ok, reason, qty) — is this a REAL, stoppable long position?"""
    if (p.get('type') or 'long') != 'long':
        return False, f"not long (type={p.get('type')})", 0
    qty = _f(p.get('quantity'), 0.0) or 0.0
    if qty < 1:
        return False, f'qty {qty} < 1 whole share (RH stops are whole-share only)', 0
    if qty != float(int(qty)):
        return False, f'fractional qty {qty} cannot carry a whole-share stop', 0
    avail = _f(p.get('shares_available_for_sells'), 0.0) or 0.0
    heldfs = _f(p.get('shares_held_for_sells'), 0.0) or 0.0
    if avail + heldfs < qty - 1e-9:
        return False, (f'shares unaccounted (avail {avail} + held_for_sells {heldfs} '
                       f'< qty {qty})'), 0
    return True, 'ok', int(qty)


def target_stop(entry, peak, atr, cur_stop):
    """Staged ratchet -> (new_stop, stage). Never below the initial/current stop."""
    initial = cur_stop
    profit = peak - entry
    stage, want = 'INITIAL', initial
    if atr > 0 and profit >= TRAIL_START_ATR * atr:
        stage, want = 'TRAIL', peak - TRAIL_ATR * atr
    elif atr > 0 and profit >= ARM_ATR * atr:
        stage, want = 'BREAKEVEN', entry * (1 + FEE_BUFFER_BP / 1e4)
    return max(want, initial), stage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    rh = RHClient()
    acct = rh._resolve_account()
    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)

    positions = {p['symbol']: p for p in rh.get_positions(acct)}
    orders = rh.list_orders(acct)
    stops = {}
    for o in orders:
        if is_resting_stop(o):
            stops.setdefault(o['symbol'], []).append(o)

    # ---- orphan stops first: resting stop with NO position can short the account
    for sym, olist in sorted(stops.items()):
        ok = False
        if sym in positions:
            ok, _, _ = verify_tradeable(positions[sym])
        if not ok:
            for o in olist:
                if a.dry_run:
                    log(f'{sym}: [dry] ORPHAN stop {o["id"]} — would CANCEL')
                else:
                    try:
                        rh.cancel_order(o['id'], account_number=acct)
                        log(f'{sym}: ORPHAN stop CANCELLED ({o["id"]}) — no position')
                    except Exception as e:
                        log(f'{sym}: orphan stop cancel FAILED {e!r}')

    live = [s for s, p in positions.items() if verify_tradeable(p)[0]]
    if not live:
        log('no verified positions — nothing to trail (and no stops placed)')
        return 0
    quotes = {r['quote']['symbol']: r['quote'] for r in rh.get_quotes(live) if r.get('quote')}

    log(f'{"sym":6}{"qty":>4}{"entry":>8}{"last":>8}{"peak":>8}{"atr":>7}'
        f'{"stop":>8}{"->new":>8}  stage / action')
    for sym in sorted(live):
        p = positions[sym]
        ok, why, qty = verify_tradeable(p)
        if not ok:
            log(f'{sym:6} SKIP — {why}')
            continue
        entry = _f(p.get('average_buy_price'), 0.0) or 0.0
        last = _f(quotes.get(sym, {}).get('last_trade_price'), 0.0) or 0.0
        if entry <= 0 or last <= 0:
            log(f'{sym:6} SKIP — no price (entry={entry} last={last})')
            continue

        item = table.get_item(Key={'pk': f'RHPOS#{sym}', 'sk': 'current'}).get('Item') or {}
        atr = _f(item.get('atr'), 0.0) or 0.0
        cur = _f(item.get('stop_price'), 0.0) or 0.0
        if stops.get(sym):
            cur = max(cur, max(_f(o['stop_price'], 0.0) or 0.0 for o in stops[sym]))
        peak = max(_f(item.get('peak'), 0.0) or 0.0, last, entry)
        if atr <= 0:
            log(f'{sym:6} SKIP — no ATR on RHPOS# (cannot size a trail)')
            continue

        new, stage = target_stop(entry, peak, atr, cur)
        improve = new - cur
        act = f'{stage}: hold (improve {improve:+.2f} < {MIN_STEP_ATR*atr:.2f})'
        do = improve >= MIN_STEP_ATR * atr and new < last  # never place a stop at/above last
        if do:
            act = f'{stage}: TIGHTEN {cur:.2f} -> {new:.2f}'
        log(f'{sym:6}{qty:>4}{entry:>8.2f}{last:>8.2f}{peak:>8.2f}{atr:>7.2f}'
            f'{cur:>8.2f}{new:>8.2f}  {act}')

        if a.dry_run:
            continue
        # always persist the peak we saw (cheap, one update)
        try:
            table.update_item(Key={'pk': f'RHPOS#{sym}', 'sk': 'current'},
                              UpdateExpression='SET peak = :p, trail_stage = :s, trail_ts = :t',
                              ExpressionAttributeValues={':p': str(round(peak, 4)),
                                                         ':s': stage, ':t': int(time.time())})
        except Exception as e:
            log(f'  {sym}: peak persist failed (non-fatal) {e!r}')
        if not do:
            continue
        # replace the stop: cancel old THEN rest new. Order matters — RH reserves
        # shares for a resting stop (shares_available_for_sells goes to 0), so a new
        # stop is rejected while the old one holds the shares.
        for o in stops.get(sym, []):
            try:
                rh.cancel_order(o['id'], account_number=acct)
            except Exception as e:
                log(f'  {sym}: cancel {o["id"]} FAILED {e!r} — leaving old stop, skip')
                break
        else:
            time.sleep(1.5)
            try:
                rh.place_stop(sym, 'long', qty, round(new, 2), account_number=acct,
                              time_in_force='gtc',
                              client_order_ref=f'trail-{sym}-{dt.date.today()}-{stage}')
                time.sleep(1.5)
                if rh._stop_is_resting(sym, 'long', account_number=acct):
                    table.update_item(
                        Key={'pk': f'RHPOS#{sym}', 'sk': 'current'},
                        UpdateExpression='SET stop_price = :s',
                        ExpressionAttributeValues={':s': str(round(new, 4))})
                    log(f'  {sym}: stop now {new:.2f} ({stage}) — VERIFIED resting')
                else:
                    log(f'  {sym}: *** STOP NOT RESTING after replace — NAKED, '
                        f'run bot/emergency_protect_rh_positions.py ***')
            except Exception as e:
                log(f'  {sym}: place_stop FAILED {e!r} — *** POSITION MAY BE NAKED, '
                    f'run bot/emergency_protect_rh_positions.py ***')
    return 0


if __name__ == '__main__':
    sys.exit(main())
