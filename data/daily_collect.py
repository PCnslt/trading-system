#!/usr/bin/env python3
"""DAILY DELTA COLLECTOR — never miss a day of paid futures data.

Runs once/day (system crontab, data layer). Independently of the trading bots,
it fetches the last few days of IBKR bars for all 12 futures symbols and
archives them to S3 `futures-bars/` (idempotent, date-keyed overwrites). This
is the safety net that guarantees a day's daily + intraday bars are captured
even if a bot's archive step fails or is redeployed.

Contract: READ-ONLY on the trading side — reqHistoricalData + S3 put_object
only. No orders, no DynamoDB, no RUN#/POSITION/SIGNAL writes. Uses clientId 75
(distinct from live.py 70 / bonds 71 / intraday 72 / backfill 73 / tick_recorder
74 / agent 90).

Depth (delta window): daily '1 W', intraday 15m/5m '2 D'. Idempotent — re-runs
overwrite the same date keys, so a missed cron tick self-heals on the next one.

Usage:
  python data/daily_collect.py                 # daily + 15m + 5m, all 12 symbols
  python data/daily_collect.py --symbols ES,NQ  # subset
  python data/daily_collect.py --dry-run       # fetch + report, no S3 writes
"""
import argparse
import os
import sys
import time
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from ib_insync import IB, Future, ContFuture

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from bot.futures_contracts import SYMBOLS, resolve_front        # noqa: E402
from bot.intraday_scan import load_ibkr_bars, prep_rth        # noqa: E402
from data.s3_archive import archive_daily_bar, archive_intraday_bars  # noqa: E402

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
CLIENT_ID = 75                      # daily collector (74 = tick_recorder)
EXCHANGE = {sym: ex for sym, ex in SYMBOLS}
DAILY_DUR = os.getenv('DAILY_COLLECT_DUR', '1 W')
INTRA_DUR = os.getenv('INTRADAY_COLLECT_DUR', '2 D')
PACING_S = float(os.getenv('DAILY_COLLECT_PACING_S', '3'))


def _session_date(ts):
    if ts.tzinfo is None:
        return ts.date()
    return ts.tz_convert('UTC').date()


def _daily_records(df, sym):
    out = []
    for idx, r in df.iterrows():
        out.append({'date': _session_date(idx).isoformat(), 'symbol': sym,
                    'open': _f(r['Open']), 'high': _f(r['High']),
                    'low': _f(r['Low']), 'close': _f(r['Close']),
                    'volume': _f(r.get('Volume'))})
    return out


def _f(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def collect_daily(ib, sym, dry_run):
    exchange = EXCHANGE[sym]
    con = resolve_front(ib, sym, exchange)
    if con is None:
        print(f"  [{sym}] daily: NO CONTRACT (gapped?)")
        return 0
    df = load_ibkr_bars(ib, con, duration=DAILY_DUR, bar_size='1 day', rth=True)
    records = _daily_records(df, sym) if (df is not None and not df.empty) else []
    if not records:
        print(f"  [{sym}] daily: NO BARS")
        return 0
    if not dry_run:
        for r in records:
            archive_daily_bar(sym, r)
    dates = sorted(r['date'] for r in records)
    print(f"  [{sym}] daily: {len(records)} bars {dates[0]} .. {dates[-1]}")
    return len(records)


def collect_intraday_tf(ib, sym, con, bar_size, slug, dry_run):
    df = load_ibkr_bars(ib, con, duration=INTRA_DUR, bar_size=bar_size, rth=True)
    if df is None or df.empty:
        return 0
    rth = prep_rth(df)
    if rth.empty:
        return 0
    total = 0
    for d in sorted(rth['date'].unique()):
        g = rth[rth['date'] == d]
        records = [{'ts': idx.isoformat(), 'open': _f(r['Open']), 'high': _f(r['High']),
                    'low': _f(r['Low']), 'close': _f(r['Close']),
                    'volume': _f(r.get('Volume'))} for idx, r in g.iterrows()]
        if not dry_run:
            archive_intraday_bars(sym, slug, d.isoformat(), records)
        total += len(records)
    print(f"  [{sym}] {slug}: {total} bars")
    return total


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
        print(f"[daily_collect] connected clientId={CLIENT_ID} accounts={ib.managedAccounts()} "
              f"(dry_run={args.dry_run})")
        ib.sleep(1)
        for sym in syms:
            nd = ni = 0
            exchange = EXCHANGE[sym]
            if do_daily:
                nd = collect_daily(ib, sym, args.dry_run)
                time.sleep(PACING_S)
            if do_intra:
                try:
                    con = resolve_front(ib, sym, exchange)
                    if con is None:
                        print(f"  [{sym}] intraday: NO CONTRACT (gapped?)")
                    else:
                        ni += collect_intraday_tf(ib, sym, con, '15 mins', '15min', args.dry_run)
                        time.sleep(PACING_S)
                        ni += collect_intraday_tf(ib, sym, con, '5 mins', '5min', args.dry_run)
                except Exception as e:
                    print(f"  [{sym}] intraday FAILED: {e!r}")
                time.sleep(PACING_S)
            summary.append((sym, nd, ni))
    finally:
        ib.disconnect()

    print("\n=== daily_collect SUMMARY ===")
    for sym, nd, ni in summary:
        print(f"  {sym}: daily={nd} intraday={ni}")
    print(f"DONE ({len(syms)} symbols, dry_run={args.dry_run}). Trading side untouched.")


if __name__ == '__main__':
    main()
