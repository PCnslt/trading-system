#!/usr/bin/env python3
"""GAP-AND-GO paper forward-test — journals entries (buy open) and exits (next open).

Matches the validated backtest (research/gap_go_backtest.py): signal = gap-up >= 3%
vs prior close + high dollar volume + above 50-SMA, news-gated; enter at the open,
exit at the NEXT open (the backtest showed next-open >> flat-by-close).

Runs once each morning ~09:35 ET. Two jobs in one pass:
  1. SETTLE yesterday's paper entries at today's open (next-open exit).
  2. OPEN today's paper entries at today's open for fresh gap-ups.

Read-only: places NO orders. Journals to DynamoDB GAP#<sym> (state) + GAPTRADE#<sym>
(round-trips). Entry/exit price = RH live quote at run time (proxy for the open; the
1-min historical bars that would give the exact open are only available post-close).
"""
from __future__ import annotations
import io, os, sys, json, time
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
import pandas as pd
from bot.gap_go_scanner import _daily

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
GAP_PCT = float(os.getenv('GAP_GO_GAP_PCT', '3.0'))
MIN_DV = float(os.getenv('GAP_GO_MIN_DV', '2e7'))
COST = 0.0005  # 5bp/side base (paper records gross and net)


def _table():
    return boto3.resource('dynamodb', region_name=REGION).Table('trading-data')


def _open_rows(tbl):
    """{sym: item} for GAP#<sym> rows still OPEN (awaiting next-open exit)."""
    out = {}
    for it in tbl.scan()['Items']:
        if it['pk'].startswith('GAP#') and it.get('status') == 'OPEN':
            out[it['pk'][4:]] = it
    return out


def _triage_verdict(tbl, sym, today):
    """Agentic verdict from GAPTRIAGE#<sym>, or None if the triage agent hasn't run."""
    try:
        it = tbl.get_item(Key={'pk': f'GAPTRIAGE#{sym}', 'sk': today}).get('Item')
        return (it or {}).get('verdict')
    except Exception:
        return None


def main():
    from hardening.rh_client import RHClient
    from bot.news_gate import check_symbol

    now = dt.datetime.now(NY)
    if not (dt.time(9, 30) <= now.time() <= dt.time(9, 45)):
        print(f'{now:%Y-%m-%d %H:%M} ET — outside 09:30-09:45 window, no-op')
        return

    today = now.date().isoformat()
    tbl = _table()
    s3 = boto3.client('s3', region_name=REGION)
    rh = RHClient()

    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'universe_1500.json')))['symbols']))
    daily = {}
    for s in syms:
        d = _daily(s, s3)
        if d is not None:
            daily[s] = d

    quotes = {}
    for r in rh.get_quotes(list(daily.keys())):
        q = r.get('quote') or {}
        if q.get('symbol') and q.get('last_trade_price'):
            quotes[q['symbol']] = float(q['last_trade_price'])

    # 1) settle yesterday's open entries at today's (next-open) price
    settled = 0
    for sym, row in _open_rows(tbl).items():
        px = quotes.get(sym)
        if not px:
            continue
        entry = float(row.get('entry_price') or 0)
        if entry <= 0:
            continue
        ret = px / entry - 1.0
        gross_bp = ret * 1e4
        net_bp = (ret - 2 * COST) * 1e4
        tbl.put_item(Item={'pk': f'GAPTRADE#{sym}', 'sk': row.get('entry_date', today),
                           'entry_date': row.get('entry_date'), 'entry_price': str(entry),
                           'exit_date': today, 'exit_price': str(px),
                           'gross_bp': str(round(gross_bp, 2)), 'net_bp': str(round(net_bp, 2)),
                           'ts': int(time.time())})
        tbl.put_item(Item={'pk': f'GAP#{sym}', 'sk': 'current', 'status': 'CLOSED',
                           'entry_date': row.get('entry_date'), 'exit_date': today,
                           'entry_price': str(entry), 'exit_price': str(px),
                           'net_bp': str(round(net_bp, 2)), 'ts': int(time.time())})
        print(f'  SETTLE {sym}: {entry:.2f} -> {px:.2f} ({net_bp:+.1f}bp)')
        settled += 1

    # 2) open today's gap-ups at today's (open-proxy) price
    opened = 0
    for sym, px in quotes.items():
        df = daily[sym]
        pc = float(df['close'].iloc[-1])
        sma50 = float(df['sma50'].iloc[-1])
        dv = float(df['dv'].iloc[-1])
        gap = (px / pc - 1.0) * 100 if pc > 0 else 0
        if gap < GAP_PCT or px < sma50 or dv < MIN_DV:
            continue
        verdict, _why, _headlines = check_symbol(sym)
        tri = _triage_verdict(tbl, sym, today)
        if tri == 'CURRENT_NEGATIVE' or verdict.startswith('NEGATIVE'):
            src = f'agent:{tri}' if tri else f'kw:{verdict}'
            print(f'  SKIP {sym} (+{gap:.1f}%) — news gate ({src})')
            continue
        tbl.put_item(Item={'pk': f'GAP#{sym}', 'sk': 'current', 'status': 'OPEN',
                           'entry_date': today, 'entry_price': str(px),
                           'gap_pct': str(round(gap, 2)), 'ts': int(time.time())})
        print(f'  OPEN   {sym}: {px:.2f} (gap +{gap:.1f}%, dv ${dv/1e6:.0f}M)')
        opened += 1

    print(f'[{today}] gap-and-go paper: {settled} settled, {opened} opened')


if __name__ == '__main__':
    main()
