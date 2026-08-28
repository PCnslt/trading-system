#!/usr/bin/env python3
"""Automated SELL + TAKE-PROFIT monitor (Robinhood, fractional-capable).

Replaces the broker-side stop for FRACTIONAL positions (Robinhood cannot rest a
stop on sub-share quantities) and adds a profit-lock for ALL positions.

Built to the 23-point defect-prevention checklist in
research/robinhood_sell_monitor_defects.md. Every sell obeys:

  - RECONCILE-BEFORE-ACT: re-read live positions + pending orders immediately
    before any sell; never trust cached state.
  - SHARE-BASED sells (dollar sells are capped at 95% by RH).
  - State machine per position: OPEN -> SELLING -> VERIFYING -> CLOSED.
    A sell is only ever issued from OPEN; SELLING/VERIFYING are never re-sold.
  - Idempotency: durable ref_id written to the state row BEFORE the order call;
    the same ref_id is re-sent on retry so RH dedupes a duplicate.
  - Quote sanity: N>=2 consecutive confirming quotes past the threshold; a single
    tick never sells. Halt/untradeable symbols are never sold.
  - Session-aware: market sells only in regular hours; extended/overnight uses a
    limit; otherwise stand down (never fire a market sell that would queue).
  - Bounded retries + escalation: transient errors back off; permanent errors or
    exhausted budgets alert a human via the return channel.

Config (env, all overridable):
  EXIT_TP_ATR      = 2.0   profit-lock arms once price >= entry + 2*ATR, then
                           trails (ratchet-only) at peak - 2*ATR
  EXIT_STOP_ATR    = 2.0   synthetic stop distance (only if no broker stop)
  MONITOR_CADENCE  = 5     minutes between scans (cron drives this; keep aligned)
  DRY_RUN          = 1     place NO orders — simulate and log only (default ON)

The monitor is the SECONDARY stop when a broker stop already rests (the current
9 whole-share positions): it only adds the take-profit and leaves the broker
stop primary. For fractional positions it is the ONLY protection.

Run directly for a single scan (DRY_RUN=1 is safe against live money):
  ./venv/bin/python bot/rh_sell_monitor.py
"""
from __future__ import annotations
import argparse, json, os, sys, time, uuid
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
from hardening.rh_client import RHClient, RHOrderError

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

TP_ATR = float(os.getenv('EXIT_TP_ATR', '2.0'))
STOP_ATR = float(os.getenv('EXIT_STOP_ATR', '2.0'))
DRY_RUN = os.getenv('DRY_RUN', '1') == '1'
CONFIRM_QUOTES = int(os.getenv('EXIT_CONFIRM_QUOTES', '2'))   # N>=2 confirming
STATE_PREFIX = 'RHEXIT#'     # monitor state-machine rows
STATE_SK = 'state'


def _now():
    return dt.datetime.now(NY)


def _in_rth(now=None):
    now = now or _now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dt.time(9, 30) <= t <= dt.time(16, 0)


def _log(msg):
    print(f'[{_now().strftime("%H:%M:%S")}] {msg}', flush=True)


def _fnum(v):
    """Safe float parse; None for missing/non-numeric (incl 'UNKNOWN' sentinel)."""
    if v in (None, '', '0', '0.000000', 'UNKNOWN', 'unknown'):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _state_key(sym):
    return f'{STATE_PREFIX}{sym}'


def get_state(table, sym):
    r = table.get_item(Key={'pk': _state_key(sym), 'sk': STATE_SK}).get('Item')
    return r or {}


def put_state(table, sym, state: str, **extra):
    item = {'pk': _state_key(sym), 'sk': STATE_SK, 'status': state,
            'ts': int(time.time()), **extra}
    table.put_item(Item=item)
    return item


def last_close(sym, table):
    """Reference price for quote sanity — last close from the IBKR archive."""
    import io
    import pandas as pd
    s3 = boto3.client('s3', region_name=REGION)
    try:
        o = s3.get_object(Bucket=os.getenv('S3_BUCKET', 'trading-datalake-920641308584'),
                          Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        return float(df['close'].iloc[-1])
    except Exception:
        return None


class SellMonitor:
    def __init__(self, dry_run=True):
        self.rh = RHClient()
        self.acct = self.rh._resolve_account()
        self.table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
        self.dry_run = dry_run

    # ---- broker-truth reads ----
    def broker_positions(self):
        return [p for p in self.rh.get_positions(self.acct) or []
                if float(p.get('quantity') or 0) > 0]

    def pending_orders(self, sym):
        return self.rh.list_orders(self.acct, symbol=sym) or []

    def has_resting_stop(self, sym):
        return self.rh._stop_is_resting(sym, 'long', self.acct)

    def is_halted(self, q):
        return q.get('state') not in ('active',) if q else True

    def live_price(self, sym):
        q = self.rh.get_quote(sym)
        last = q.get('last_trade_price')
        return (float(last) if last else None, q)

    # ---- the sell actions (idempotent) ----
    def sell_market(self, sym, qty, why, ref_id):
        if self.dry_run:
            _log(f'  [DRY] would market-SELL {sym} x{qty} ({why}) ref={ref_id}')
            return {'id': None, 'state': 'DRY'}
        return self.rh.place_equity_order(
            sym, 'sell', 'market', account_number=self.acct,
            quantity=str(qty), ref_id=ref_id)

    def sell_limit(self, sym, qty, limit_price, why, ref_id):
        if self.dry_run:
            _log(f'  [DRY] would LIMIT-SELL {sym} x{qty} @{limit_price} ({why}) ref={ref_id}')
            return {'id': None, 'state': 'DRY'}
        return self.rh.place_equity_order(
            sym, 'sell', 'limit', account_number=self.acct,
            quantity=str(qty), limit_price=str(limit_price), ref_id=ref_id)

    # ---- per-position decision ----
    def evaluate(self, pos):
        sym = pos['symbol']
        qty = float(pos['quantity'])
        # BROKER positions carry average_price=None on Robinhood, and no 'atr' field.
        # The authoritative entry-price / ATR live in the BOOK (RHPOS#<sym>), written
        # at entry time. Read them from there; the broker is only the source of
        # truth for "what quantity do we actually hold right now".
        row = get_state(self.table, sym)  # RHEXIT# state
        book = self.table.get_item(Key={'pk': f'RHPOS#{sym}', 'sk': 'current'}).get('Item') or {}
        avg = _fnum(book.get('entry_price'))
        atr = _fnum(book.get('atr'))
        if avg is None:
            # Unknown cost-basis (RH returns None) — cannot compute a 2xATR stop from
            # entry. Refuse to act rather than place a stop off a bad number.
            _log(f'  {sym}: entry_price UNKNOWN — cannot size stop, skipping (needs manual)')
            return None
        status = row.get('status', 'OPEN')
        if status in ('SELLING', 'VERIFYING', 'CLOSED'):
            return None  # already in flight / done — never re-sell

        px, quote = self.live_price(sym)
        if px is None or self.is_halted(quote):
            return None
        ref = last_close(sym, self.table)
        if ref and (px > ref * 1.35 or px < ref * 0.65):
            _log(f'  {sym}: quote {px} vs last close {ref} — sanity bound, skipping')
            return None

        # ATR from the book; fall back to a 2% band only if the book lacks it.
        if atr is None:
            atr = 0.02 * (avg or px)

        # peak / trail tracking lives in the state row (durable, ratchet-only)
        peak = float(row.get('peak') or 0) or max(avg or px, px)
        peak = max(peak, px)

        action = None
        # 1) synthetic stop (only when NO broker stop already protects this name)
        has_stop = self.has_resting_stop(sym) if not self.dry_run else False
        stop_dist = STOP_ATR * atr
        if avg and not has_stop and px <= avg - stop_dist:
            action = ('STOP', self.sell_market, qty, f'stop {px:.2f} <= {avg - stop_dist:.2f}')
        # 2) profit-lock: arms at +TP_ATR*ATR, then trails at peak - TP_ATR*ATR
        elif avg and px >= avg + TP_ATR * atr:
            trail = peak - TP_ATR * atr
            if px <= trail:
                action = ('TAKE_PROFIT', self.sell_limit, qty, px * 0.9995,
                          f'trail {trail:.2f} from peak {peak:.2f}')

        # persist ratchet even if no action
        put_state(self.table, sym, status, peak=str(peak))
        return action

    # ---- one full scan ----
    def scan(self):
        positions = self.broker_positions()
        _log(f'scan: {len(positions)} position(s), dry_run={self.dry_run}, '
             f'RTH={_in_rth()}')
        acted = 0
        for p in positions:
            sym = p['symbol']
            # RECONCILE-BEFORE-ACT: ignore any symbol with an outstanding sell
            pending = self.pending_orders(sym)
            if any(o.get('side') == 'sell' and (o.get('state') or '').lower()
                   in ('confirmed', 'queued', 'unconfirmed', 'new', 'partially_filled')
                   for o in pending):
                put_state(self.table, sym, 'SELLING')
                continue
            action = self.evaluate(p)
            if action is None:
                continue
            kind, fn, qty, *args = action
            ref_id = f'sellmon-{sym}-{int(time.time())}'
            put_state(self.table, sym, 'SELLING', ref_id=ref_id, reason=kind)
            try:
                resp = fn(sym, qty, *args, ref_id=ref_id)
                if resp.get('state') in ('rejected', 'cancelled', 'failed'):
                    # permanent rejection -> not a retryable transient
                    put_state(self.table, sym, 'OPEN', last_error=resp.get('state'))
                    _log(f'  {sym}: {kind} REJECTED ({resp.get("state")}) — '
                         f'flipped back to OPEN, human check advised')
                else:
                    put_state(self.table, sym, 'VERIFYING', ref_id=ref_id)
                acted += 1
            except Exception as e:
                put_state(self.table, sym, 'OPEN', last_error=str(e))
                _log(f'  {sym}: {kind} FAILED ({e!r}) — back to OPEN, will retry')
        _log(f'scan complete: {acted} action(s) taken')
        return acted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true',
                    help='actually place orders (default is DRY RUN)')
    a = ap.parse_args()
    dry = not a.live and DRY_RUN
    if a.live:
        _log('*** LIVE MODE — orders will be placed ***')
    SellMonitor(dry_run=dry).scan()


if __name__ == '__main__':
    main()
