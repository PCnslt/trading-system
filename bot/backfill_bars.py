#!/usr/bin/env python3
"""Comprehensive IBKR futures-bar backfill -> S3 `futures-bars/` (all 12 symbols).

Rollover-aware by construction: daily bars come from the FRONT contract's
continuous series (IBKR auto-rolls on long-duration futures requests) and, for
symbols where that series is shallow, are merged with the CONTFUT continuous
series. The explicit per-expiry rollover schedule is `contracts/<sym>/rollover.json`
(bot/futures_contracts.py). Intraday uses the qualified front contract.

Depth (honest, non-professional entitlement, measured 2026-08-14):
  - Daily:  ~3y for CME index (ES ~742 bars to 2023-08); CBOT rates shallower
            (~8mo front-contract / ~16mo CONTFUT) — merged union archived.
  - 1h/15m/5m: ~1y (to ~2025-07).
  - 1m:      ~30d.

READ-ONLY on the trading side: reqHistoricalData + S3 put_object only.
No orders, no DynamoDB writes, no RUN# markers, no POSITION writes.

Pacing: `PACING_S` (default 10s) between reqHistoricalData calls so the backfill
never starves the 23:00/23:05 daily and */15 RTH intraday bots sharing the
gateway. S3 writes are parallelized (thread pool) — they don't touch the gateway.

Usage:
  python bot/backfill_bars.py                    # full: daily + intraday, all 12
  python bot/backfill_bars.py --symbols ES,NQ    # subset
  python bot/backfill_bars.py --daily-only       # daily only
  python bot/backfill_bars.py --intraday-only    # intraday only
  python bot/backfill_bars.py --dry-run          # fetch + report, no S3 writes
"""
import os
import sys
import math
import time
import json
import argparse
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
import pandas as pd
from dotenv import load_dotenv
from ib_insync import IB, Future, ContFuture, util

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from bot.futures_contracts import SYMBOLS, resolve_front
from bot.intraday_scan import prep_rth, TZ
from data.s3_archive import put_json

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
CLIENT_ID = 73                       # distinct from live.py(70)/bonds(71)/intraday(72)/agent(90)

PACING_S = float(os.getenv('BACKFILL_PACING_S', '10'))
WRITE_WORKERS = int(os.getenv('BACKFILL_WRITE_WORKERS', '16'))
FETCH_TIMEOUT = 120                  # seconds per reqHistoricalData (60s default too short for 5Y daily)
FETCH_RETRIES = 1
DAILY_MIN_BARS = 500                 # below this, also merge CONTFUT for more depth

DAILY_DUR = '5 Y'
INTRA_1H_DUR = '1 Y'
INTRA_15M_DUR = '1 Y'
INTRA_5M_DUR = '1 Y'
INTRA_5M_DUR_FALLBACK = '6 M'
INTRA_1M_DUR = '30 D'

EXCHANGE = {sym: ex for sym, ex in SYMBOLS}


def _f(v):
    """float(v) with NaN -> None (safe JSON)."""
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _session_date(ts):
    """Recover the IBKR session date from the America/New_York index."""
    if ts.tzinfo is None:
        return ts.date()
    return ts.tz_convert('UTC').date()


def _load_bars(ib, con, duration, bar_size, rth=True):
    """reqHistoricalData -> OHLCV DataFrame (NY tz), with long timeout + retry.

    Mirrors intraday_scan.load_ibkr_bars but raises the request timeout (the
    60s default times out on deep daily requests) and retries once on empty.
    """
    bars = None
    for attempt in range(FETCH_RETRIES + 1):
        try:
            bars = ib.reqHistoricalData(con, endDateTime='', durationStr=duration,
                                        barSizeSetting=bar_size, whatToShow='TRADES',
                                        useRTH=rth, formatDate=2, timeout=FETCH_TIMEOUT)
        except Exception as e:
            print(f"      fetch attempt {attempt} err: {e!r}")
        if bars:
            break
        time.sleep(5)
    if not bars:
        return pd.DataFrame()
    df = util.df(bars).rename(columns=str.title)
    df = df.set_index('Date')
    if getattr(df.index, 'tz', None) is None:
        df.index = pd.to_datetime(df.index, utc=True)
    df.index = df.index.tz_convert(TZ)
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]


def _write_parallel(pairs):
    """Parallel S3 put_object (thread pool). Doesn't touch the gateway."""
    if not pairs:
        return
    s3 = boto3.client('s3', region_name=AWS_REGION)

    def _put(kv):
        key, obj = kv
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(obj, default=str))
        return key

    with ThreadPoolExecutor(max_workers=WRITE_WORKERS) as ex:
        list(ex.map(_put, pairs))


def _daily_records(df, sym):
    return [{'date': _session_date(idx).isoformat(), 'symbol': sym,
             'open': _f(r['Open']), 'high': _f(r['High']), 'low': _f(r['Low']),
             'close': _f(r['Close']), 'volume': _f(r.get('Volume'))}
            for idx, r in df.iterrows()]


def backfill_daily(ib, sym, dry_run):
    """Daily bars: front-contract continuous series, merged with CONTFUT if shallow."""
    exchange = EXCHANGE[sym]
    con = resolve_front(ib, sym, exchange)
    if con is None:
        print(f"    [{sym}] daily: NO CONTRACT (gapped?)")
        return 0
    df = _load_bars(ib, con, duration=DAILY_DUR, bar_size='1 day', rth=True)

    merged = {r['date']: r for r in _daily_records(df, sym)} if (df is not None and not df.empty) else {}
    n_front = len(merged)

    # If the front-contract series is shallow (CBOT rates), merge CONTFUT too.
    if n_front < DAILY_MIN_BARS:
        try:
            cf = ib.qualifyContracts(ContFuture(sym, exchange, 'USD'))[0]
            df_cf = _load_bars(ib, cf, duration=DAILY_DUR, bar_size='1 day', rth=True)
            if df_cf is not None and not df_cf.empty:
                cf_records = {r['date']: r for r in _daily_records(df_cf, sym)}
                for d, bar in cf_records.items():       # front-contract wins on overlap
                    merged.setdefault(d, bar)
        except Exception as e:
            print(f"    [{sym}] CONTFUT merge skipped: {e!r}")

    if not merged:
        print(f"    [{sym}] daily: NO BARS")
        return 0

    records = [merged[d] for d in sorted(merged)]
    if not dry_run:
        _write_parallel([(f'futures-bars/daily/{sym}/{r["date"]}.json', r) for r in records])
    dates = sorted(merged)
    print(f"    [{sym}] daily: {len(records)} bars {dates[0]} .. {dates[-1]} "
          f"(front={n_front}, merged={len(records)})")
    return len(records)


def backfill_intraday_tf(ib, sym, con, bar_size, slug, duration, dry_run):
    df = _load_bars(ib, con, duration=duration, bar_size=bar_size, rth=True)
    if df is None or df.empty:
        return 0
    rth = prep_rth(df)
    if rth.empty:
        return 0
    dates = sorted(rth['date'].unique())
    pairs = []
    total = 0
    for d in dates:
        g = rth[rth['date'] == d]
        records = [{'ts': idx.isoformat(), 'open': _f(r['Open']), 'high': _f(r['High']),
                    'low': _f(r['Low']), 'close': _f(r['Close']),
                    'volume': _f(r.get('Volume'))}
                   for idx, r in g.iterrows()]
        pairs.append((f'futures-bars/intraday/{sym}/{slug}/{d.isoformat()}.json',
                      {'sym': sym, 'barsize': slug, 'date': d.isoformat(), 'bars': records}))
        total += len(records)
    if not dry_run:
        _write_parallel(pairs)
    print(f"    [{sym}] {slug}: {total} bars, {len(dates)} dates {dates[0]} .. {dates[-1]}")
    return total


def backfill_intraday(ib, sym, dry_run):
    exchange = EXCHANGE[sym]
    con = resolve_front(ib, sym, exchange)
    if con is None:
        print(f"    [{sym}] intraday: NO CONTRACT (gapped?)")
        return 0
    tot = 0
    tot += backfill_intraday_tf(ib, sym, con, '1 hour', '1h', INTRA_1H_DUR, dry_run)
    tot += backfill_intraday_tf(ib, sym, con, '15 mins', '15min', INTRA_15M_DUR, dry_run)
    # 5m: '1 Y' is near the entitlement cap; fall back to '6 M' if empty.
    df = _load_bars(ib, con, duration=INTRA_5M_DUR, bar_size='5 mins', rth=True)
    if df is None or df.empty:
        df = _load_bars(ib, con, duration=INTRA_5M_DUR_FALLBACK, bar_size='5 mins', rth=True)
    if df is not None and not df.empty:
        rth = prep_rth(df)
        dates = sorted(rth['date'].unique())
        pairs = []
        n5 = 0
        for d in dates:
            g = rth[rth['date'] == d]
            records = [{'ts': idx.isoformat(), 'open': _f(r['Open']), 'high': _f(r['High']),
                        'low': _f(r['Low']), 'close': _f(r['Close']),
                        'volume': _f(r.get('Volume'))}
                       for idx, r in g.iterrows()]
            pairs.append((f'futures-bars/intraday/{sym}/5min/{d.isoformat()}.json',
                          {'sym': sym, 'barsize': '5min', 'date': d.isoformat(), 'bars': records}))
            n5 += len(records)
        if not dry_run:
            _write_parallel(pairs)
        tot += n5
        print(f"    [{sym}] 5min: {n5} bars, {len(dates)} dates {dates[0]} .. {dates[-1]}")
    else:
        print(f"    [{sym}] 5min: NO BARS (even at '6 M')")
    tot += backfill_intraday_tf(ib, sym, con, '1 min', '1m', INTRA_1M_DUR, dry_run)
    return tot


def _pace():
    time.sleep(PACING_S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', default='', help='comma subset, e.g. ES,NQ')
    ap.add_argument('--daily-only', action='store_true')
    ap.add_argument('--intraday-only', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    syms = [s for s, _ in SYMBOLS]
    if args.symbols:
        want = {x.strip().upper() for x in args.symbols.split(',') if x.strip()}
        syms = [s for s in syms if s in want]

    do_daily = not args.intraday_only
    do_intra = not args.daily_only

    ib = IB()
    summary = []
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=15, readonly=True)
        print(f"connected clientId={CLIENT_ID} accounts={ib.managedAccounts()} "
              f"(READ-ONLY; dry_run={args.dry_run}, pacing={PACING_S}s)")
        ib.sleep(2)  # small warm-up so the first deep request doesn't race the handshake
        for sym in syms:
            print(f"\n=== {sym} ===")
            n_daily = n_intra = 0
            if do_daily:
                n_daily = backfill_daily(ib, sym, args.dry_run)
                _pace()
            if do_intra:
                n_intra = backfill_intraday(ib, sym, args.dry_run)
                _pace()
            summary.append((sym, n_daily, n_intra))
    finally:
        ib.disconnect()

    print("\n=== SUMMARY ===")
    for sym, nd, ni in summary:
        print(f"  {sym}: daily={nd} intraday={ni}")
    print(f"\nDONE ({len(syms)} symbols, dry_run={args.dry_run}). "
          "Trading side untouched: no orders, no DynamoDB, no RUN#, no POSITION.")


if __name__ == '__main__':
    main()
