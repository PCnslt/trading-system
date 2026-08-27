#!/usr/bin/env python3
"""Intraday BUY (fractional-capable) — news-gated, fill-price-verified, protected.

The correct live buy path. Fixes the 2026-08-27 defects:
  1. NEWS GATE first: skip any name with a SEVERE catalyst (bot/news_gate.py).
  2. POLL the real fill: RH order-creation returns average_price=0.0; we poll the
     order until filled and read the REAL average_price before writing the book.
  3. WRITE the book with entry_price + atr + stop (2xATR) + take_profit (+2xATR),
     so the sell-monitor has correct levels (it reads them from the book).

Usage:
  ./venv/bin/python bot/rh_intraday_buy.py SYM SIZE_USD [SYM SIZE_USD ...]
  e.g.  ... AMAT 58 XOM 105
Sizes are risk-sized by the caller (1% risk / 15% cap). DRY_RUN=1 (default) prints
the plan and places NOTHING; pass --live to place real orders.
"""
from __future__ import annotations
import argparse, io, os, sys, time
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
import numpy as np
import pandas as pd
from hardening.rh_client import RHClient
from bot.news_gate import check_symbol

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
STOP_ATR = float(os.getenv('EXIT_STOP_ATR', '2.0'))
TP_ATR = float(os.getenv('EXIT_TP_ATR', '2.0'))


def atr14(df, n=14):
    h, l, c = df['high'], df['low'], df['close']
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])


def daily_atr(sym):
    s3 = boto3.client('s3', region_name=REGION)
    o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
    df = pd.read_parquet(io.BytesIO(o['Body'].read()))
    df.index = pd.to_datetime(df['date'].astype(str))
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
    return atr14(df), float(df['close'].iloc[-1])


def poll_fill(rh, acct, sym, side, oid, state, timeout=12.0):
    """Poll until terminal; ALWAYS re-read the order to get the real average_price.

    Bug fixed 2026-08-27: the old loop broke immediately when the creation response
    already said 'filled', so average_price stayed None and the book got entry_price=0.
    We now always do a final list_orders read so the fill price is captured.
    """
    ep = None
    t0 = time.time()
    while time.time() - t0 < timeout:
        if state in ('cancelled', 'rejected', 'failed'):
            break
        time.sleep(0.6)
        orders = rh.list_orders(acct, order_id=oid) if oid else []
        if orders:
            state = (orders[0].get('state') or '').lower()
            ep = orders[0].get('average_price')
            if state in ('filled', 'partially_filled') and ep:
                break
    # final read if still no price but state is filled
    if state in ('filled', 'partially_filled') and not ep and oid:
        for o in (rh.list_orders(acct, order_id=oid) or []):
            ep = o.get('average_price') or ep
    return state, ep, oid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true')
    ap.add_argument('pairs', nargs='+', help='SYM SIZE_USD pairs')
    a = ap.parse_args()
    if len(a.pairs) % 2:
        raise SystemExit('provide SYM SIZE_USD pairs')

    rh = RHClient()
    acct = rh._resolve_account()
    table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
    today = str(dt.datetime.now(NY).date())

    for i in range(0, len(a.pairs), 2):
        sym = a.pairs[i].upper()
        size_usd = float(a.pairs[i + 1])
        print(f'\n=== {sym}  \${size_usd:.2f} ===')

        # 1. news gate
        verdict, why, _ = check_symbol(sym)
        print(f'  news: {verdict} — {why}')
        if verdict == 'NEGATIVE':
            print(f'  SKIP {sym}: negative catalyst')
            continue

        # 2. ATR + reference
        atr, lastc = daily_atr(sym)
        print(f'  last_close={lastc:.2f}  ATR={atr:.2f}')

        # 3. buy
        if not a.live:
            print(f'  [DRY] would buy {sym} \${size_usd:.2f} (news {verdict})')
            continue
        fill = rh.place_equity_order(sym, 'buy', 'market', account_number=acct,
                                     dollar_amount=f'{size_usd:.2f}',
                                     client_order_ref=f'rh_{today}_{sym}',
                                     ref_id=f'buy-{sym}-{int(time.time())}')
        oid = fill.get('id')
        state = (fill.get('state') or '').lower()
        if not oid:
            for _ in range(5):
                recent = rh.list_orders(acct, symbol=sym) or []
                cands = [o for o in recent if o.get('side') == 'buy'
                         and o.get('stop_price') in (None, '', '0', '0.000000')]
                if cands:
                    cands.sort(key=lambda o: o.get('created_at') or '', reverse=True)
                    oid = cands[0].get('id'); state = (cands[0].get('state') or '').lower()
                    if oid:
                        break
                time.sleep(0.6)
        state, ep, oid = poll_fill(rh, acct, sym, 'buy', oid, state)
        if state not in ('filled', 'partially_filled') or not ep:
            print(f'  !!! {sym} NOT confirmed filled (state={state}, avg={ep}) — book NOT written')
            continue
        ep = float(ep)
        qty = size_usd / ep
        stop = ep - STOP_ATR * atr
        tp = ep + TP_ATR * atr
        print(f'  FILLED {sym}: avg={ep:.4f}  qty~{qty:.6f}  stop={stop:.2f}  tp={tp:.2f}')
        table.put_item(Item={
            'pk': f'RHPOS#{sym}', 'sk': 'current', 'status': 'OPEN',
            'entry_date': today, 'entry_price': str(round(ep, 4)),
            'stop_price': str(round(stop, 2)), 'atr': str(round(atr, 2)),
            'take_profit': str(round(tp, 2)), 'size_usd': str(size_usd),
            'size_shares': str(round(qty, 6)), 'fractional': '1',
            'monitor_stop': '1', 'strategy': 'RSI2-intraday',
            'news_verdict': verdict, 'ts': int(time.time())})
        print(f'  book written: entry={ep:.4f} stop={stop:.2f} tp={tp:.2f}')

    print('\nDONE')


if __name__ == '__main__':
    main()
