#!/usr/bin/env python3
"""Creamer auction signal generator (Phase 4, order-flow lane) — SIGNAL-ONLY.

MNQ 5-min, first 90 min of NY open (09:30–11:00 ET), 20k-contract participation
floor per 5-min candle. Runs the 4-step framework (`data/auction.py`) over the
archived 5-min bars + futures ticks and logs candidate setups to DynamoDB
`AUCTION#<sym>` (one item per setup). **exec=NONE by construction** — no IBKR
orders, no account writes.

Steps (per the reference `orderflow-auction-strategy`):
  1. Environment  — 1h market structure (value up/down/sideways).
  2. Location     — fib golden pocket 0.705/0.788/0.886 from the swing,
                    OUTSIDE the session value area (discount in uptrend /
                    premium in downtrend).
  3. Confirmation — absorption (failed auction) + shift of dominance +
                    bid/ask imbalance (optional; pending until orderbook data).
  4. Execution    — stop below failed sellers / below 0.886; targets at POC
                    and the swing.

Data: `compute_session_features` (microstructure engine) supplies the per-bar
delta / absorption / spread + session POC/VAH/VAL + orderbook imbalance.

Usage:
  python bot/auction_signals.py --symbols MNQ [--date 2026-08-17] [--dry-run]
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
from infra.secrets import bootstrap as _sb
_sb()

from data.auction import (market_structure, find_swings, fib_golden_pocket,
                          auction_setup)
from data.microstructure import bar_absorption, bid_ask_delta
from microstructure_engine import (_load_bars, _load_ticks, _latest_book,
                                   compute_session_features, _list_prefix)

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
SYMBOLS = ['MNQ']
MIN_PARTICIPATION = 20000.0    # contracts per 5-min candle (participation floor)
ENTRY_START = dt.time(9, 30)   # first 90 min of NY open
ENTRY_END = dt.time(11, 0)


def resample_1h(bars):
    """Group 5-min bars into 1h OHLCV buckets (in arrival order)."""
    hourly = {}
    for b in bars:
        ts = b.get('ts')
        try:
            t = dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        except Exception:
            continue
        key = t.replace(minute=0, second=0, microsecond=0)
        h = hourly.setdefault(key, {'high': -1e18, 'low': 1e18, 'volume': 0.0})
        h['high'] = max(h['high'], b.get('high'))
        h['low'] = min(h['low'], b.get('low'))
        h['volume'] += float(b.get('volume') or 0.0)
    keys = sorted(hourly)
    return keys, [hourly[k] for k in keys]


def _load_bars_multi(s3, sym, dates):
    """Load bars for multiple session dates and concatenate (arrival order)."""
    out = []
    for d in dates:
        out.extend(_load_bars(s3, sym, d))
    return out


def generate_setups(sym, structure_bars, target_bars, per_bar, profile, imbalance):
    """Run the 4-step framework over the first 90 min of the TARGET session.

    `structure_bars` is a MULTI-DAY 5-min window (resampled to 1h for the
    environment + swings); `target_bars`/`per_bar`/`profile` are the target
    session's bars + per-bar features + value area. Returns candidate setups.
    """
    _, hourly = resample_1h(structure_bars)
    if len(hourly) < 4:
        return []
    h_highs = [h['high'] for h in hourly]
    h_lows = [h['low'] for h in hourly]
    sh, sl = find_swings(h_highs, h_lows, n=1)
    swing_low = h_lows[sl[-1]] if sl else None
    swing_high = h_highs[sh[-1]] if sh else None

    deltas = [f['delta'] for f in per_bar]
    setups = []
    for i, b in enumerate(target_bars):
        ts = b.get('ts')
        try:
            t = dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        except Exception:
            continue
        if not (ENTRY_START <= t.time() < ENTRY_END):
            continue
        price = b.get('close')
        participation = float(b.get('volume') or 0.0)
        f = per_bar[i]
        absn = {'sell_absorption': f['sell_absorption'],
                'buy_absorption': f['buy_absorption']}
        for side in ('long', 'short'):
            failed = b.get('low') if side == 'long' else b.get('high')
            s = auction_setup(
                side=side, price=price, highs=h_highs, lows=h_lows,
                vah=profile.get('vah'), val=profile.get('val'), poc=profile.get('poc'),
                deltas=deltas[:i + 1], absorption=absn, imbalance=imbalance,
                swing_low=swing_low, swing_high=swing_high, failed_extreme=failed,
                participation=participation, min_participation=MIN_PARTICIPATION)
            if s:
                s['symbol'] = sym
                s['bar_ts'] = ts
                setups.append(s)
    return setups


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
        # multi-day 1h window for the environment (structure + swings)
        all_dates = sorted({k.split('/')[4].replace('.json', '')
                            for k in _list_prefix(s3, f'futures-bars/intraday/{sym}/5min/')})
        idx = all_dates.index(date) if date in all_dates else len(all_dates) - 1
        window = all_dates[max(0, idx - 9):idx + 1]   # up to 10 sessions incl. target
        structure_bars = _load_bars_multi(s3, sym, window)
        per_bar, profile, imbalance = compute_session_features(sym, bars, ticks, book)
        setups = generate_setups(sym, structure_bars, bars, per_bar, profile, imbalance)
        print(f'[{sym}] {date}: {len(bars)} bars, {len(window)}-session 1h window, '
              f'{len(setups)} candidate setups (imbalance={imbalance})')
        for s in setups:
            print(f'  {s["side"]:5s} @ {s["entry"]} stop={s["stop"]} '
                  f't1(POC)={s["target_poc"]} t2(swing)={s["target_swing"]} '
                  f'env={s["environment"]} part={s["participation"]:.0f}')
        if args.dry_run:
            continue
        now = int(time.time())
        for s in setups:
            item = {'pk': f'AUCTION#{sym}', 'sk': s['bar_ts'],
                    'side': s['side'], 'entry': str(round(s['entry'], 2)),
                    'environment': s['environment'], 'ts': now}
            if s['stop'] is not None:
                item['stop'] = str(round(s['stop'], 2))
            for k in ('target_poc', 'target_swing', 'participation'):
                if s.get(k) is not None:
                    item[k] = str(round(s[k], 4))
            item['confirmation'] = json.dumps(s['confirmation'])
            table.put_item(Item=item)
        print(f'[{sym}] wrote {len(setups)} AUCTION# rows')


if __name__ == '__main__':
    main()
