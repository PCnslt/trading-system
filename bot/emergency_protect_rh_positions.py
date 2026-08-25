#!/usr/bin/env python3
"""EMERGENCY: rest a protective stop on every naked Robinhood position.

Context: bot/live_equities.py placed 9 LIVE entries on 2026-08-25 that FILLED at
the broker, but the fill-confirmation path could not read an order id back from
the MCP creation response (state='', order_id=n/a). It therefore treated each
entry as failed, wrote NO POSITION# state, and rested NO protective stop —
leaving 9 real positions naked and invisible to the bot and the reconciler.

This script is idempotent: it only acts on positions that have no resting stop.
Stop = entry_price - 2*ATR14 (the lane's STOP_ATR), whole shares, GTC.
Also writes POSITION# rows so the bot/reconciler can manage the positions.
"""
import os, sys, time, json
import datetime as dt

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
import pandas as pd
import yfinance as yf
from hardening.rh_client import RHClient

STOP_ATR = 2.0
SCOPE = 'live_equities'
DRY = os.getenv('DRY', '0') == '1'
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
REGION = os.getenv('AWS_REGION', 'us-east-1')


def wilder_atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def atr_for(sym):
    df = yf.download(sym, start='2025-01-01', interval='1d',
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    a = wilder_atr(df['high'], df['low'], df['close'], 14)
    v = float(a.iloc[-1])
    return v if v > 0 else None


def main():
    rh = RHClient()
    acct = rh._resolve_account()
    table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)

    positions = rh.get_positions(acct)
    positions = [p for p in positions if float(p.get('quantity') or 0) > 0]
    print(f'positions held: {len(positions)}')

    # Robinhood has NO 'open' order state — a resting order is 'confirmed'. Passing
    # state='open' returns an EMPTY list, which made the first version of this script
    # report "STILL NAKED" for nine positions whose stops were in fact resting.
    RESTING_STATES = ('confirmed', 'queued', 'unconfirmed', 'partially_filled')

    def _resting_sell_stops(all_orders):
        out = {}
        for o in all_orders:
            if (o.get('side') == 'sell'
                    and o.get('stop_price') not in (None, '', '0', '0.000000')
                    and (o.get('state') or '').lower() in RESTING_STATES):
                out.setdefault(o.get('symbol'), []).append(o)
        return out

    resting = _resting_sell_stops(rh.list_orders(acct) or [])
    print(f'existing resting sell-stops: { {k: len(v) for k, v in resting.items()} }')

    total = 0.0
    for p in positions:
        sym = p['symbol']
        qty = int(float(p['quantity']))
        entry = float(p.get('average_buy_price') or 0)
        total += qty * entry
        if sym in resting:
            print(f'  {sym:6} qty={qty} — stop ALREADY resting, skip')
            continue
        atr = atr_for(sym)
        if not atr:
            print(f'  {sym:6} qty={qty} — ATR unavailable, SKIP (manual attention)')
            continue
        stop = round(max(0.01, entry - STOP_ATR * atr), 2)
        pct = (entry - stop) / entry * 100 if entry else 0
        if DRY:
            print(f'  [dry] {sym:6} qty={qty} entry={entry:.2f} atr={atr:.3f} -> stop={stop:.2f} (-{pct:.1f}%)')
            continue
        try:
            res = rh.place_stop(sym, 'long', qty, stop, account_number=acct,
                                time_in_force='gtc',
                                client_order_ref=f'emergency-protect-{sym}-{dt.date.today()}')
            oid = str(res.get('id') or res.get('order_id') or '')
            print(f'  {sym:6} qty={qty} entry={entry:.2f} -> STOP {stop:.2f} (-{pct:.1f}%) id={oid or "?"}')
            table.put_item(Item={
                'pk': f'POSITION#{SCOPE}:{sym}', 'sk': 'current',
                'status': 'OPEN', 'entry_date': str(dt.date.today()),
                'entry_price': str(entry), 'stop_price': str(stop),
                'size_shares': str(qty), 'pos': str(qty),
                'atr': str(round(atr, 4)), 'side': 'LONG',
                'size_usd': str(round(qty * entry, 2)),
                'source': 'emergency_protect_rh_positions.py',
                'ts': int(time.time())})
        except Exception as e:
            print(f'  {sym:6} STOP FAILED: {e!r}  <-- STILL NAKED, MANUAL ACTION')
        time.sleep(1.0)

    print(f'\ntotal long exposure ~= ${total:,.2f}')
    # verify
    if not DRY:
        time.sleep(3)
        oo = rh.list_orders(acct) or []
        got = sorted(_resting_sell_stops(oo))
        held = sorted({p['symbol'] for p in positions})
        print(f'VERIFY resting stops: {got}')
        print(f'VERIFY positions    : {held}')
        naked = [s for s in held if s not in got]
        print(f'*** STILL NAKED: {naked} ***' if naked else '*** ALL POSITIONS PROTECTED ***')


if __name__ == '__main__':
    main()
