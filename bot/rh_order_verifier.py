#!/usr/bin/env python3
"""Order-verification & reconciliation bot (Robinhood, broker-truth).

Runs AFTER every buy/sell and on a cron cadence. Answers one question with ground
truth: does what we THINK we hold match what the BROKER actually holds? It is the
only defence against the 2026-08-25 failure where 9 positions filled at the broker
but the bot's book never learned about them.

Three-way reconcile, always broker-truth-first:

  1. BROKER position has no matching RHPOS# OPEN row   -> NAKED position (we hold
     something we didn't record). Register it + rest/confirm protection.
  2. RHPOS# OPEN row has no broker position            -> PHANTOM (we think we hold,
     but broker is flat — a fill that was cancelled/reversed, or a sell we missed
     recording). Correct the book to CLOSED.
  3. Resting stop present with no broker position      -> ORPHAN stop (can short the
     account if it triggers). Cancel it.

The verifier NEVER places an entry or a sell on its own. It only:
  - registers a naked broker position into the book (with the broker's own avg price)
  - corrects a phantom book row to CLOSED
  - cancels an orphan sell-stop
  - writes a reconciliation journal row (RHRECON#<date>) and reports mismatches.

Modes:
  --verify   one reconciliation pass (default). Exit 0 = clean, 1 = mismatch found.
  DRY_RUN=1  report-only: log every correction but change nothing (default ON).
"""
from __future__ import annotations
import argparse, json, os, sys, time
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
from hardening.rh_client import RHClient

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
DRY_RUN = os.getenv('DRY_RUN', '1') == '1'


def _log(m):
    print(f'[{dt.datetime.now(NY).strftime("%H:%M:%S")}] {m}', flush=True)


class Verifier:
    def __init__(self, dry_run=True):
        self.rh = RHClient()
        self.acct = self.rh._resolve_account()
        self.table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
        self.dry_run = dry_run
        self.mismatches = []

    def broker_positions(self):
        return [p for p in self.rh.get_positions(self.acct) or []
                if float(p.get('quantity') or 0) > 0]

    def book_open(self):
        out = {}
        lek = None
        while True:
            kw = dict(FilterExpression='begins_with(pk, :p)',
                      ExpressionAttributeValues={':p': 'RHPOS#'})
            if lek:
                kw['ExclusiveStartKey'] = lek
            resp = self.table.scan(**kw)
            for it in resp.get('Items', []):
                if it.get('sk') == 'current' and it.get('status') in ('PENDING', 'OPEN'):
                    out[it['pk'].split('#', 1)[1]] = it
            lek = resp.get('LastEvaluatedKey')
            if not lek:
                break
        return out

    def resting_stops(self):
        """{sym: order} for resting sell-stops (RH: type='market'+stop_price, 'confirmed')."""
        out = {}
        for o in self.rh.list_orders(self.acct) or []:
            if o.get('side') != 'sell':
                continue
            has_stop = (o.get('stop_price') not in (None, '', '0', '0.000000')
                        or o.get('type') in ('stop_market', 'stop_limit'))
            if has_stop and (o.get('state') or '').lower() in (
                    'confirmed', 'queued', 'unconfirmed', 'new', 'partially_filled'):
                out[o.get('symbol', '').upper()] = o
        return out

    def _fill_price(self, sym):
        """Real fill price from the newest BUY order for sym (RH position cost-basis
        is often None; the order object carries average_price). Returns None if unknown."""
        try:
            for o in self.rh.list_orders(self.acct) or []:
                if o.get('side') == 'buy' and (o.get('symbol') or '').upper() == sym.upper():
                    px = o.get('average_price')
                    if px not in (None, '', '0', '0.000000'):
                        return float(px)
        except Exception:
            pass
        return None

    def verify(self):
        broker = {p['symbol']: p for p in self.broker_positions()}
        book = self.book_open()
        stops = self.resting_stops()
        today = str(dt.datetime.now(NY).date())

        # 1. naked: broker holds, book doesn't
        for sym, p in broker.items():
            if sym not in book:
                self.mismatches.append(('NAKED', sym, p))
                _log(f'  NAKED {sym}: broker {p.get("quantity")}sh, book has no OPEN row')
                if not self.dry_run:
                    # RH position objects carry average_price=None; the cost-basis field
                    # is average_buy_price. Fall back to fill-order price; NEVER write an
                    # empty entry_price (breaks the sell-monitor's stop/take-profit calc).
                    ep = p.get('average_buy_price') or p.get('average_price') or None
                    if ep in (None, '', '0', '0.000000'):
                        ep = self._fill_price(sym)
                    self.table.put_item(Item={
                        'pk': f'RHPOS#{sym}', 'sk': 'current', 'status': 'OPEN',
                        'entry_price': str(ep) if ep not in (None, '', '0') else 'UNKNOWN',
                        'size_shares': str(p.get('quantity') or ''),
                        'entry_date': today, 'source': 'reconcile-registered',
                        'ts': int(time.time())})

        # 2. phantom: book OPEN, broker flat
        for sym, row in book.items():
            if sym not in broker:
                self.mismatches.append(('PHANTOM', sym, row))
                _log(f'  PHANTOM {sym}: book OPEN but broker flat')
                if not self.dry_run:
                    self.table.put_item(Item={
                        'pk': f'RHPOS#{sym}', 'sk': 'current', 'status': 'CLOSED',
                        'entry_date': row.get('entry_date', ''),
                        'exit_reason': 'reconcile-phantom',
                        'exit_date': today, 'ts': int(time.time())})

        # 3. orphan stop: stop rests, broker flat (can SHORT the account)
        for sym, o in stops.items():
            if sym not in broker:
                self.mismatches.append(('ORPHAN_STOP', sym, o))
                _log(f'  ORPHAN STOP {sym}: resting sell-stop with no position')
                if not self.dry_run:
                    try:
                        self.rh.cancel_order(o['id'], self.acct)
                    except Exception as e:
                        _log(f'    cancel failed: {e!r}')

        # journal
        if self.mismatches:
            for kind, sym, _ in self.mismatches:
                self.table.put_item(Item={
                    'pk': f'RHRECON#{today}', 'sk': f'{kind}#{sym}',
                    'kind': kind, 'symbol': sym, 'dry_run': self.dry_run,
                    'ts': int(time.time())})
        _log(f'reconcile: {len(broker)} broker, {len(book)} book-open, '
             f'{len(stops)} stops, {len(self.mismatches)} mismatch(es) '
             f'({"DRY" if self.dry_run else "APPLIED"})')
        return 1 if self.mismatches else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true', default=True)
    ap.add_argument('--live', action='store_true')
    a = ap.parse_args()
    if a.live:
        _log('*** LIVE mode — corrections will be APPLIED ***')
    dry = not a.live and DRY_RUN
    sys.exit(Verifier(dry_run=dry).verify())


if __name__ == '__main__':
    main()
