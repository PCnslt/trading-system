#!/usr/bin/env python3
"""Microstructure / footprint feature runner (Phase 3, order-flow lane).

Batch job: for a symbol + RTH session, load the archived futures ticks
(`futures-ticks/<sym>/<date>/`) and 5-min bars (`futures-bars/intraday/<sym>/5min/`),
compute the per-bar footprint features (bid-ask delta, absorption, spread) +
the session volume profile (POC/VAH/VAL) + the latest orderbook imbalance, and
persist one `MICRO#<sym>` row per bar to DynamoDB.

Pure computation lives in `data/microstructure.py` (unit-tested); this module is
the I/O layer (S3 load + DynamoDB write). READ-ONLY on the trading side — no
orders, no account writes.

Usage:
  python bot/microstructure_engine.py --symbols MES,MNQ --date 2026-08-17
  (defaults to the most recent archived session)
"""
import os
import sys
import json
import argparse
import datetime as dt
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

from data.microstructure import (bid_ask_delta, bar_absorption, volume_profile,
                                 orderbook_imbalance, spread_and_cost)

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
BAR_MS = 5 * 60 * 1000                       # 5-min bars
SYMBOLS = ['MES', 'MNQ']


def _load_jsonl(s3, key):
    try:
        o = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return [json.loads(l) for l in o['Body'].read().decode().splitlines() if l.strip()]
    except Exception:
        return []


def _list_prefix(s3, prefix):
    keys = []
    pag = s3.get_paginator('list_objects_v2')
    for p in pag.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for o in p.get('Contents', []):
            keys.append(o['Key'])
    return keys


def _load_bars(s3, sym, date):
    key = f'futures-bars/intraday/{sym}/5min/{date}.json'
    try:
        o = s3.get_object(Bucket=S3_BUCKET, Key=key)
        d = json.loads(o['Body'].read())
        return d.get('bars', [])
    except Exception:
        return []


def _load_ticks(s3, sym, date):
    keys = _list_prefix(s3, f'futures-ticks/{sym}/{date}/')
    if not keys:
        return []
    ticks = []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=32) as ex:
        for rows in ex.map(lambda k: _load_jsonl(s3, k), keys):
            ticks.extend(rows)
    return ticks


def _latest_book(s3, sym, date):
    keys = _list_prefix(s3, f'orderbook/{sym}/{date}/')
    if not keys:
        return None
    lines = _load_jsonl(s3, keys[-1])
    return lines[-1] if lines else None


def _floor_bar(ts_epoch):
    return int(ts_epoch // (BAR_MS / 1000)) * (BAR_MS // 1000)


def compute_session_features(sym, bars, ticks, book=None):
    """Per-bar footprint features + session volume profile.

    bars  = [{ts, open, high, low, close, volume}] (5-min, one session)
    ticks = [{ts(epoch s), bid, ask, last, lastSize}]
    book  = optional {bids:[{price,quantity}], asks:[...]} (latest snapshot)
    """
    # map bar -> epoch start for tick bucketing
    bar_epoch = {}
    for b in bars:
        try:
            bar_epoch[b['ts']] = int(
                dt.datetime.fromisoformat(str(b['ts']).replace('Z', '+00:00')).timestamp())
        except Exception:
            bar_epoch[b['ts']] = None

    # bucket ticks into bars by 5-min floor
    tick_buckets = {b['ts']: [] for b in bars}
    for t in ticks:
        ts = t.get('ts')
        if ts is None:
            continue
        k = _floor_bar(ts)
        for bts, ep in bar_epoch.items():
            if ep is not None and k == _floor_bar(ep):
                tick_buckets[bts].append(t)
                break

    per_bar = []
    for b in bars:
        bts = b['ts']
        tk = tick_buckets.get(bts, [])
        d = bid_ask_delta(tk, bar_fn=lambda t: bts).get(
            bts, {'delta': 0.0, 'buys': 0.0, 'sells': 0.0})
        absn = bar_absorption(b, delta=d['delta'], delta_threshold=0.0)
        # spread from the last tick's bid/ask in the bar
        last_tick = tk[-1] if tk else {}
        spread = spread_and_cost(last_tick.get('bid'), last_tick.get('ask'))
        per_bar.append({
            'sym': sym, 'bar_ts': bts,
            'delta': d['delta'], 'buys': d['buys'], 'sells': d['sells'],
            'sell_absorption': absn['sell_absorption'],
            'buy_absorption': absn['buy_absorption'],
            'spread_ticks': spread['spread_ticks'],
        })

    profile = volume_profile(bars, price_step=1.0, value_area=0.70)
    imbalance = None
    if book:
        imbalance = orderbook_imbalance(book.get('bids', []), book.get('asks', []), top_n=5)

    return per_bar, profile, imbalance


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', default=','.join(SYMBOLS))
    ap.add_argument('--date', default=None, help='session date YYYY-MM-DD (default: latest)')
    ap.add_argument('--dry-run', action='store_true', help='compute + print, no DynamoDB write')
    args = ap.parse_args()

    syms = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    s3 = boto3.client('s3', region_name=AWS_REGION)
    table = None if args.dry_run else \
        boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)

    for sym in syms:
        date = args.date
        if not date:
            dates = sorted({k.split('/')[4].replace('.json', '')
                            for k in _list_prefix(s3, f'futures-bars/intraday/{sym}/5min/')})
            date = dates[-1] if dates else None
        if not date:
            print(f'[{sym}] no 5-min archive — skip')
            continue
        bars = _load_bars(s3, sym, date)
        ticks = _load_ticks(s3, sym, date)
        book = _latest_book(s3, sym, date)
        if not bars:
            print(f'[{sym}] {date}: no bars — skip')
            continue
        per_bar, profile, imbalance = compute_session_features(sym, bars, ticks, book)
        print(f'[{sym}] {date}: {len(bars)} bars, {len(ticks)} ticks, '
              f'POC={profile["poc"]} VAH={profile["vah"]} VAL={profile["val"]}, '
              f'book_imbalance={imbalance}')
        if args.dry_run:
            continue
        now = int(time.time())
        for f in per_bar:
            item = {'pk': f'MICRO#{sym}', 'sk': f['bar_ts'],
                    'delta': str(round(f['delta'], 4)),
                    'buys': str(round(f['buys'], 4)),
                    'sells': str(round(f['sells'], 4)),
                    'sell_absorption': str(f['sell_absorption']).lower(),
                    'buy_absorption': str(f['buy_absorption']).lower(),
                    'ts': now}
            if f['spread_ticks'] is not None:
                item['spread_ticks'] = str(round(f['spread_ticks'], 4))
            for k in ('poc', 'vah', 'val'):
                if profile.get(k) is not None:
                    item[k] = str(round(profile[k], 4))
            if imbalance is not None:
                item['book_imbalance'] = str(round(imbalance, 6))
            table.put_item(Item=item)
        print(f'[{sym}] wrote {len(per_bar)} MICRO# rows')


if __name__ == '__main__':
    main()
