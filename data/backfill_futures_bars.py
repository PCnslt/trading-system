#!/usr/bin/env python3
"""One-time IBKR historical backfill -> S3 futures-bars archive.

READ-ONLY on the trading side: no orders, no DynamoDB writes, no RUN# markers,
no POSITION writes. Only two side effects, both intentional and safe:
  1) IBKR reqHistoricalData (read-only market data) against IB Gateway :4002.
  2) S3 put_object into the futures-bars/ cold archive.

Reuses the EXACT functions the bots use (true live-path test):
  - bar fetch  : bot.intraday_scan.load_ibkr_bars   (IBKR reqHistoricalData)
  - RTH filter : bot.intraday_scan.prep_rth
  - archive    : data.s3_archive.archive_daily_bar / archive_intraday_bars

Backfill scope:
  - Daily ES/NQ/ZB/ZN via IBKR continuous futures (CONTFUT) ~2y (entitlement-capped).
  - Intraday MES 5m + 15m via front-month Future, 60 D (whatever IBKR returns).
"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ib_insync import IB, Future, ContFuture
from dotenv import load_dotenv

from bot.intraday_scan import load_ibkr_bars, prep_rth
from data.s3_archive import archive_daily_bar, archive_intraday_bars

load_dotenv()
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
CLIENT_ID = 90          # distinct from live.py(70) / bonds(71) / intraday(72)

# Continuous futures (IBKR CONTFUT) — the rolling series, matching the archive
# keys ES/NQ/ZB/ZN that live.py + live_bondsfx.py already write under.
DAILY = [
    {'sym': 'ES', 'cf': ContFuture('ES', 'CME', 'USD')},
    {'sym': 'NQ', 'cf': ContFuture('NQ', 'CME', 'USD')},
    {'sym': 'ZB', 'cf': ContFuture('ZB', 'CBOT', 'USD')},
    {'sym': 'ZN', 'cf': ContFuture('ZN', 'CBOT', 'USD')},
]


def front_month(now=None):
    now = now or dt.date.today()
    for m in (3, 6, 9, 12):
        if now.month <= m:
            return f"{now.year}{m:02d}"
    return f"{now.year + 1}03"


def session_date(idx):
    """Recover the IBKR session date from load_ibkr_bars' tz-shifted index.

    IBKR daily bars carry a date-only 'YYYYMMDD' field. load_ibkr_bars localizes
    that to UTC midnight then converts to America/New_York, so the session date
    is the index converted BACK to UTC (round-trip is DST-safe).
    """
    if getattr(idx, 'tz', None) is not None:
        return idx.tz_convert('UTC').date()
    return idx.date()


def backfill_daily(ib):
    print("\n=== DAILY BACKFILL (ES/NQ/ZB/ZN, 2 Y, CONTFUT) ===")
    for spec in DAILY:
        sym = spec['sym']
        try:
            q = ib.qualifyContracts(spec['cf'])
            if not q:
                print(f"[{sym}] qualify -> EMPTY, skip")
                continue
            con = q[0]
            df = load_ibkr_bars(ib, con, duration='2 Y', bar_size='1 day', rth=True)
            if df is None or df.empty:
                print(f"[{sym}] no daily bars")
                continue
            n = 0
            for idx, r in df.iterrows():
                bar = {
                    'date': session_date(idx).isoformat(),
                    'symbol': sym,
                    'open': float(r['Open']), 'high': float(r['High']),
                    'low': float(r['Low']), 'close': float(r['Close']),
                    'volume': float(r['Volume']) if 'Volume' in df.columns else None,
                }
                archive_daily_bar(sym, bar)
                n += 1
            print(f"[{sym}] archived {n} daily bars "
                  f"{session_date(df.index[0])} .. {session_date(df.index[-1])}")
        except Exception as e:
            print(f"[{sym}] daily FAILED: {e!r}")


def backfill_intraday(ib):
    print("\n=== INTRADAY BACKFILL (MES 5m + 15m, 60 D) ===")
    try:
        con = ib.qualifyContracts(Future('MES', front_month(), 'CME'))[0]
    except Exception as e:
        print(f"[MES] qualify FAILED: {e!r}")
        return
    for barsize, slug in [('5 mins', '5min'), ('15 mins', '15min')]:
        try:
            df = load_ibkr_bars(ib, con, duration='60 D', bar_size=barsize, rth=True)
            if df is None or df.empty:
                print(f"[MES {slug}] no bars")
                continue
            rth = prep_rth(df)
            dates = sorted(rth['date'].unique())
            total = 0
            for d in dates:
                g = rth[rth['date'] == d]
                records = [{'date': idx.isoformat(), 'open': float(r['Open']),
                            'high': float(r['High']), 'low': float(r['Low']),
                            'close': float(r['Close']), 'volume': float(r['Volume'])}
                           for idx, r in g.iterrows()]
                archive_intraday_bars('MES', slug, d.isoformat(), records)
                total += len(records)
            print(f"[MES {slug}] archived {total} bars across {len(dates)} dates "
                  f"{dates[0]} .. {dates[-1]}")
        except Exception as e:
            print(f"[MES {slug}] FAILED: {e!r}")


def main():
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=15)
        print(f"connected to {IBKR_HOST}:{IBKR_PORT} clientId={CLIENT_ID} "
              f"accounts={ib.managedAccounts()} (READ-ONLY: no orders placed)")
        backfill_daily(ib)
        backfill_intraday(ib)
    finally:
        ib.disconnect()
    print("\nDONE. Trading side untouched: no orders, no DynamoDB writes, "
          "no RUN# markers, no POSITION writes.")


if __name__ == '__main__':
    main()

