"""Robinhood trailing-stop manager — universal profit protection for every trade.

Robinhood cannot natively trail a stop (and its stops are market-hours only), so
this bot manages the trailing stop itself. For every OPEN RHPOS# position it:
  1. reads the live quote and tracks the peak price since entry (POSITION 'peak'),
  2. computes a chandelier trail  trail = peak - TRAIL_ATR * ATR,
  3. if the trail is HIGHER than the resting stop, cancels the old stop and rests
     a new stop_market at the trail (TIGHTEN-ONLY — never loosens a stop).

This is the owner's "our own bot doing the trailing stop" — universal, applies to
every trade regardless of strategy. Runs every N minutes during RTH (RH stops are
market-hours only). LIVE account only; a missing/unreadable position or a failed
stop placement leaves the existing stop untouched (fail-safe, never naked).

Usage:
  python bot/rh_trailing.py --dry-run        # report what would tighten, no orders
  python bot/rh_trailing.py                  # trail every open position
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

import boto3
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from infra.ssm_secrets import bootstrap as _sb  # noqa: E402
_sb()

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
RH_LIVE_ACCOUNT = os.getenv('RH_LIVE_ACCOUNT', '515821577')
TRAIL_ATR = float(os.getenv('RH_TRAIL_ATR', '2.0'))  # chandelier distance in ATRs


def _price(q: dict):
    """Robustly extract a float price from a get_quote() dict."""
    for k in ('last_trade_price', 'price', 'close'):
        v = q.get(k)
        if isinstance(v, dict):
            v = v.get('price') or v.get('close')
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return None


def _load_open_positions(table):
    """{sym: item} for RHPOS#* rows with status == OPEN."""
    out = {}
    lek = None
    while True:
        kw = {'FilterExpression': 'begins_with(pk, :p)',
              'ExpressionAttributeValues': {':p': 'RHPOS#'}}
        if lek:
            kw['ExclusiveStartKey'] = lek
        resp = table.scan(**kw)
        for it in resp.get('Items', []):
            if str(it.get('status', '')) == 'OPEN':
                sym = it['pk'].replace('RHPOS#', '')
                out[sym] = it
        lek = resp.get('LastEvaluatedKey')
        if not lek:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    now = dt.datetime.now(ZoneInfo('America/New_York'))
    today = now.date().isoformat()

    # RH stops are market-hours only; trailing outside RTH is pointless.
    if not args.dry_run and (now.weekday() >= 5 or not (dt.time(9, 30) <= now.time() <= dt.time(16, 0))):
        print(f'[{today}] rh_trailing SKIP — outside RTH (09:30–16:00 ET)')
        return

    positions = _load_open_positions(table)
    if not positions:
        print(f'[{today}] rh_trailing: no open positions')
        return

    from hardening.rh_client import RHClient
    client = RHClient(account_number=RH_LIVE_ACCOUNT)

    n_tightened = 0
    for sym, pos in positions.items():
        try:
            q = client.get_quote(sym)
        except Exception as e:
            print(f'  {sym}: quote failed ({e!r}) — skip (stop untouched)')
            continue
        price = _price(q)
        if price is None:
            print(f'  {sym}: no price in quote — skip')
            continue
        entry = float(pos.get('entry_price') or 0)
        atr = float(pos.get('atr') or 0)
        cur_stop = float(pos.get('stop_price') or 0)
        peak = max(float(pos.get('peak') or entry), price)
        trail = peak - TRAIL_ATR * atr if atr > 0 else cur_stop

        tightened = False
        if trail > cur_stop + 0.01 and not args.dry_run:
            try:
                # cancel any resting stop for this symbol, then rest the tighter one
                for o in client.list_orders(symbol=sym, state='open'):
                    if o.get('type') in ('stop_market', 'stop_limit') or o.get('order_type') in ('stop_market', 'stop_limit'):
                        client.cancel_order(o.get('id') or o.get('order_id'))
                shares = int(float(pos.get('size_shares') or 0) or 0)
                if shares <= 0 and entry > 0:
                    shares = int(float(pos.get('size_usd') or 0) / entry)
                if shares >= 1:
                    client.place_stop(sym, 'long', shares, round(trail, 2))
                    tightened = True
                else:
                    print(f'  {sym}: <1 whole share ({shares}) — cannot rest stop (RH whole-share)')
            except Exception as e:
                print(f'  {sym}: tighten failed ({e!r}) — existing stop untouched')

        # persist peak (and the tighter stop) so the next run trails from here
        upd = {'peak': str(round(peak, 2))}
        if tightened:
            upd['stop_price'] = str(round(trail, 2))
            n_tightened += 1
        if not args.dry_run:
            try:
                table.update_item(Key={'pk': f'RHPOS#{sym}', 'sk': 'current'},
                                  UpdateExpression='SET peak=:pk, stop_price=:sp',
                                  ExpressionAttributeValues={':pk': upd['peak'],
                                                             ':sp': upd.get('stop_price', str(round(cur_stop, 2)))},
                                  ConditionExpression='attribute_exists(pk)')
            except Exception as e:
                print(f'  {sym}: persist peak failed ({e!r})')

        flag = 'TIGHTEN' if tightened else ('would-tighten' if (trail > cur_stop + 0.01 and args.dry_run) else 'hold')
        print(f'  {sym:6s} px={price:.2f} peak={peak:.2f} trail={trail:.2f} cur_stop={cur_stop:.2f} [{flag}]')

    print(f'\nrh_trailing done [{today}]: {len(positions)} open, {n_tightened} tightened')


if __name__ == '__main__':
    main()
