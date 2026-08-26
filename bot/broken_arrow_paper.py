#!/usr/bin/env python3
"""Broken Arrow PAPER forward-test — zero capital, and it measures its own blocker.

Lane 47 (docs/STRATEGY_PORTFOLIO.md): buy the CLOSE of a stock that fell >= DROP today
while above a RISING 40-day MA; sell the NEXT OPEN. Backtest (research/candidate_backtest.py,
375 syms 2006-2026, sub-$50, 6bp): -8% -> OOS +34.4bp t=3.96; -10% -> OOS +54.0bp t=3.85.
Independently reproduces Alvarez's published +0.77%/trade at -15%.

WHY PAPER: the account is 92% invested in the RSI(2) lane ($643.76 of ~$700), so this
could not take a live trade today even if approved. Paper accumulates real-time signal +
fill evidence at no risk while the live positions resolve.

IT ALSO CLOSES THE ONE BLOCKER. The 1.9bp closing half-spread measured on 2026-08-25 was
on NORMAL names; this strategy deliberately buys names that just fell 8-15%, whose closing
spread will be wider. At scan time we pull the LIVE L2 book for each triggered name and
record the ACTUAL effective half-spread to fill $105 — i.e. the cost measurement is taken
on precisely the names the strategy would have bought, which is the only sample that counts.

MODES
  --scan     run ~15:50 ET. Find triggers, measure their real book cost, record PAPER entry.
  --settle   run ~09:32 ET. Close yesterday's paper entries at today's OPEN, journal P&L.

State: DynamoDB  BAPOS#<SYM> sk='current'   BATRADE#<SYM> sk=<entry_date>
Places NO orders of any kind. Read-only against the broker.
"""
from __future__ import annotations
import argparse, io, json, os, sys, time
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap as _sb
_sb()

import boto3
import numpy as np
import pandas as pd
from hardening.rh_client import RHClient
from research.rh_book_cost import walk

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

DROP = float(os.getenv('BA_DROP', '0.08'))          # -8%: best OOS t on the sweep
MA_LEN = 40
PRICE_LO, PRICE_HI = 2.0, 50.0
MIN_DOLLAR_VOL = 5e6
CLIP_USD = float(os.getenv('BA_CLIP_USD', '105'))   # 15% of a $700 account
MAX_NAMES = int(os.getenv('BA_MAX_NAMES', '5'))


def log(m):
    print(f'[{dt.datetime.now(NY).strftime("%H:%M:%S")}] {m}', flush=True)


def universe():
    p = os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')
    return list(dict.fromkeys(json.load(open(p))['symbols']))


def load_hist(sym, s3):
    """Daily history through the last CLOSED session (archive is refreshed post-close)."""
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < MA_LEN + 5:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        return df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
    except Exception:
        return None


def scan():
    """15:50 ET — find today's triggers using the LIVE quote as today's close."""
    now = dt.datetime.now(NY)
    rh = RHClient()
    acct = rh._resolve_account()
    s3 = boto3.client('s3', region_name=REGION)
    table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
    syms = universe()

    # live prices for the whole universe (chunked)
    live = {}
    for i in range(0, len(syms), 40):
        try:
            for r in rh.get_quotes(syms[i:i + 40]):
                q = r.get('quote') or {}
                if q.get('symbol') and q.get('last_trade_price'):
                    live[q['symbol']] = float(q['last_trade_price'])
        except Exception as e:
            log(f'  quote chunk failed: {e!r}')
    log(f'live prices for {len(live)}/{len(syms)} names')

    cands = []
    for sym, px in live.items():
        if not (PRICE_LO <= px <= PRICE_HI):
            continue
        df = load_hist(sym, s3)
        if df is None:
            continue
        # history must end BEFORE today so 'today' is the live price, not a stored bar
        if str(df.index[-1].date()) == str(now.date()):
            df = df.iloc[:-1]
        if len(df) < MA_LEN + 2:
            continue
        prev_close = float(df['close'].iloc[-1])
        ma = df['close'].rolling(MA_LEN).mean()
        ma_now, ma_prev = float(ma.iloc[-1]), float(ma.iloc[-2])
        dvol = float((df['close'] * df['volume']).rolling(20).mean().iloc[-1])
        ret = px / prev_close - 1.0
        if (ret <= -DROP and prev_close > ma_now and ma_now > ma_prev
                and dvol > MIN_DOLLAR_VOL):
            cands.append({'symbol': sym, 'price': px, 'prev_close': prev_close,
                          'ret': ret, 'ma40': ma_now, 'dollar_vol': dvol})

    log(f'{len(cands)} trigger(s) at drop<=-{DROP*100:.0f}%: '
        f'{[c["symbol"] for c in cands]}')
    if not cands:
        return 0

    # THE BLOCKER MEASUREMENT: real L2 cost on exactly these crashed names
    for ch in [cands[i:i + 4] for i in range(0, len(cands), 4)]:
        try:
            raw = rh._tool('get_equity_price_book', symbols=[c['symbol'] for c in ch])
            books = {b.get('symbol'): b for b in ((raw.get('data') or {}).get('books') or [])}
        except Exception as e:
            log(f'  price_book failed: {e!r}')
            books = {}
        for c in ch:
            b = books.get(c['symbol']) or {}
            bid, ask = b.get('bids') or [], b.get('asks') or []
            if bid and ask:
                try:
                    bb = float(bid[0]['price']); ba = float(ask[0]['price'])
                    mid = (bb + ba) / 2
                    c['quoted_bp'] = round((ba - bb) / mid * 1e4, 1)
                    v, filled, _ = walk(ask, CLIP_USD, 'buy')
                    if v and filled >= CLIP_USD * 0.99:
                        c['buy_half_bp'] = round((v - mid) / mid * 1e4, 1)
                    c['book_ok'] = filled >= CLIP_USD * 0.99
                except Exception:
                    pass

    cands.sort(key=lambda c: c.get('buy_half_bp', 9e9))
    picked = cands[:MAX_NAMES]
    for c in picked:
        shares = int(CLIP_USD / c['price'])
        if shares < 1:
            log(f"  {c['symbol']}: SKIP, ${CLIP_USD:.0f} < 1 whole share @ {c['price']:.2f}")
            continue
        item = {'pk': f'BAPOS#{c["symbol"]}', 'sk': 'current', 'status': 'OPEN',
                'entry_date': str(now.date()), 'entry_price': str(round(c['price'], 4)),
                'shares': str(shares), 'day_ret': str(round(c['ret'], 5)),
                'prev_close': str(round(c['prev_close'], 4)),
                'ma40': str(round(c['ma40'], 4)),
                'quoted_bp': str(c.get('quoted_bp', '')),
                'buy_half_bp': str(c.get('buy_half_bp', '')),
                'mode': 'PAPER', 'lane': 'broken_arrow', 'ts': int(time.time())}
        table.put_item(Item=item)
        log(f"  PAPER BUY {c['symbol']:6} {shares}sh @ {c['price']:.2f} "
            f"(day {c['ret']*100:+.1f}%)  quoted={c.get('quoted_bp','?')}bp "
            f"buy_half={c.get('buy_half_bp','?')}bp")
    return len(picked)


def settle():
    """09:32 ET — close yesterday's paper entries at today's OPEN."""
    now = dt.datetime.now(NY)
    rh = RHClient()
    table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
    resp = table.scan(FilterExpression='begins_with(pk, :p) AND #s = :o',
                      ExpressionAttributeValues={':p': 'BAPOS#', ':o': 'OPEN'},
                      ExpressionAttributeNames={'#s': 'status'})
    open_pos = [i for i in resp.get('Items', []) if i.get('sk') == 'current']
    if not open_pos:
        log('no open paper positions')
        return 0
    syms = [i['pk'].split('#', 1)[1] for i in open_pos]
    live = {}
    try:
        for r in rh.get_quotes(syms):
            q = r.get('quote') or {}
            if q.get('symbol') and q.get('last_trade_price'):
                live[q['symbol']] = float(q['last_trade_price'])
    except Exception as e:
        log(f'quote failed: {e!r}')
        return 1
    tot = 0.0
    for it in open_pos:
        sym = it['pk'].split('#', 1)[1]
        px = live.get(sym)
        if px is None:
            log(f'  {sym}: no quote, leaving OPEN')
            continue
        entry = float(it['entry_price'])
        sh = int(it['shares'])
        gross_bp = (px / entry - 1.0) * 1e4
        buy_half = float(it['buy_half_bp']) if it.get('buy_half_bp') not in (None, '', 'None') else 3.0
        net_bp = gross_bp - buy_half - 3.0          # entry half + assumed open sell half
        pnl = (px - entry) * sh
        tot += pnl
        table.put_item(Item={
            'pk': f'BATRADE#{sym}', 'sk': it['entry_date'],
            'entry_date': it['entry_date'], 'exit_date': str(now.date()),
            'entry_price': it['entry_price'], 'exit_price': str(round(px, 4)),
            'shares': it['shares'], 'day_ret': it.get('day_ret', ''),
            'gross_bp': str(round(gross_bp, 1)), 'net_bp': str(round(net_bp, 1)),
            'buy_half_bp': it.get('buy_half_bp', ''), 'pnl_usd': str(round(pnl, 4)),
            'mode': 'PAPER', 'lane': 'broken_arrow', 'ts': int(time.time())})
        table.put_item(Item={**it, 'status': 'CLOSED',
                             'exit_date': str(now.date()),
                             'exit_price': str(round(px, 4)),
                             'net_bp': str(round(net_bp, 1))})
        log(f'  PAPER SELL {sym:6} @ {px:.2f} (entry {entry:.2f})  '
            f'gross {gross_bp:+.1f}bp  net {net_bp:+.1f}bp  ${pnl:+.2f}')
    log(f'settled {len(open_pos)} paper position(s), total ${tot:+.2f}')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', action='store_true')
    ap.add_argument('--settle', action='store_true')
    a = ap.parse_args()
    if a.scan:
        scan()
    elif a.settle:
        settle()
    else:
        print('use --scan (15:50 ET) or --settle (09:32 ET)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
