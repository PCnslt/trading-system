#!/usr/bin/env python3
"""Incremental IBKR daily-bar refresh for the LIVE equity universe.

WHY: bot/live_equities.py was pricing a LIVE money lane off **yfinance**, while we
pay for IBKR. The IBKR archive (s3://<bucket>/ibkr/equities/daily/<SYM>.parquet,
6,548 symbols / 493 MB) existed but was last written 2026-08-15 — nine days stale
— so nothing refreshed it and the bot fell back to Yahoo.

ENTITLEMENT REALITY on U26949861 (measured 2026-08-25):
  - reqHistoricalData daily TRADES  -> WORKS, ~0.1s per symbol
  - reqMktData live L1 quotes       -> Error 10089, NOT subscribed (delayed only)
So IBKR supplies HISTORY; the live tick at entry time comes from Robinhood
(real-time, free, and it is the venue we actually execute on).

PACING: IBKR allows ~60 historical requests / 10 min. 512 symbols cannot be
fetched at 09:32 decision time (that is ~85 min). This therefore runs AFTER THE
CLOSE, when the only bar the strategy needs (today's finalized close) has just
settled, and writes it to the store the bot reads.

PERSISTENCE (everything we fetch is saved, cheaply):
  - full history  -> S3 parquet, one object per symbol (columnar, ~80 KB/sym)
  - latest bar    -> DynamoDB `BAR#<SYM>` sk='latest' via ONE batch_writer pass
                     (512 items in a single batched flush, not 512 PutItems)
"""
from __future__ import annotations
import io
import os
import sys
import json
import time
import datetime as dt

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import boto3
import pandas as pd
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap as _sb
_sb()

from ib_insync import IB, Stock
from data.ibkr_full_backfill import load_bars_df, daily_out, put_parquet, S3_BUCKET

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4001'))
CLIENT_ID = int(os.getenv('IBKR_REFRESH_CLIENT_ID', '51'))
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

PACING_S = float(os.getenv('IBKR_REFRESH_PACING_S', '5'))
TOPUP_DUR = os.getenv('IBKR_REFRESH_DUR', '3 M')   # small window; merged into history
DAILY_TIMEOUT = 120
LIMIT = int(os.getenv('IBKR_REFRESH_LIMIT', '0'))  # 0 = whole universe

s3 = boto3.client('s3', region_name=AWS_REGION)


def log(m):
    print(f'[{dt.datetime.now().isoformat(timespec="seconds")}] {m}', flush=True)


def universe():
    """Tradeable universe. The scanner and live lane now trade the BROAD
    1,459-name universe (incl. blue chips), so the refresh must cover it — not
    just the 524 small-caps. RH_IBKR_REFRESH_UNIVERSE=broad|smallcap|both."""
    mode = os.getenv('RH_IBKR_REFRESH_UNIVERSE', 'broad')
    def load(fn):
        p = os.path.join(_ROOT, 'research', fn)
        return list(dict.fromkeys(json.load(open(p))['symbols']))
    if mode == 'smallcap':
        syms = load('smallcap_universe_full.json')
    elif mode == 'both':
        syms = load('universe_1500.json') + load('smallcap_universe_full.json')
    else:
        syms = load('universe_1500.json')
    syms = list(dict.fromkeys(syms))
    return syms[:LIMIT] if LIMIT else syms


def read_existing(sym):
    """Existing daily parquet from S3 -> DataFrame (empty if absent)."""
    try:
        o = s3.get_object(Bucket=S3_BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        return pd.read_parquet(io.BytesIO(o['Body'].read()))
    except s3.exceptions.NoSuchKey:
        return pd.DataFrame()
    except Exception as e:
        log(f'  {sym}: read existing failed ({e!r}) — treating as empty')
        return pd.DataFrame()


def drop_partial_bar(out):
    """Remove TODAY's in-progress session before the 16:00 ET close.

    IBKR daily bars behave like yfinance here: during the session the CURRENT day
    is returned as a forming bar (verified: F '1 Y' returned last=2026-08-25 at
    10:4x ET). Persisting it would poison every downstream signal, so it is
    dropped until the session is final.
    """
    if out.empty:
        return out
    try:
        from zoneinfo import ZoneInfo
        now_et = dt.datetime.now(ZoneInfo('America/New_York'))
        if str(out['date'].iloc[-1]) == now_et.date().isoformat() and now_et.hour < 16:
            return out.iloc[:-1]
    except Exception:
        pass
    return out


def merge(old, new):
    """Union on `date`, newest values win, sorted ascending."""
    if old.empty:
        return new.reset_index(drop=True)
    if new.empty:
        return old.reset_index(drop=True)
    both = pd.concat([old, new], ignore_index=True)
    both['date'] = both['date'].astype(str)
    both = both.drop_duplicates(subset='date', keep='last').sort_values('date')
    return both.reset_index(drop=True)


def main():
    syms = universe()
    log(f'refreshing {len(syms)} symbols, top-up={TOPUP_DUR}, pacing={PACING_S}s '
        f'(est {len(syms)*PACING_S/60:.0f} min)')
    ib = IB()
    ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=20, readonly=True)
    log(f'connected accounts={ib.managedAccounts()} (READ-ONLY, no orders)')

    latest_rows = []
    ok = gapped = failed = 0
    for i, sym in enumerate(syms):
        try:
            con = Stock(sym, 'SMART', 'USD')
            ib.qualifyContracts(con)
            df = load_bars_df(ib, con, TOPUP_DUR, '1 day', timeout=DAILY_TIMEOUT)
            if df.empty:
                gapped += 1
                log(f'  [{i+1}/{len(syms)}] {sym}: 0 bars (GAPPED)')
                continue
            new = drop_partial_bar(daily_out(df))
            if new.empty:
                gapped += 1
                continue
            out = merge(read_existing(sym), new)
            put_parquet(f'ibkr/equities/daily/{sym}.parquet', out)
            last = out.iloc[-1]
            latest_rows.append({
                'pk': f'BAR#{sym}', 'sk': 'latest', 'symbol': sym,
                'date': str(last['date']), 'open': str(last['open']),
                'high': str(last['high']), 'low': str(last['low']),
                'close': str(last['close']), 'volume': str(last['volume']),
                'bars': str(len(out)), 'source': 'IBKR', 'quality': 'BROKER',
                'ts': int(time.time())})
            ok += 1
            if (i + 1) % 50 == 0:
                log(f'  [{i+1}/{len(syms)}] ok={ok} gapped={gapped} failed={failed} '
                    f'(last {sym} {last["date"]} close={last["close"]})')
        except Exception as e:
            failed += 1
            log(f'  [{i+1}/{len(syms)}] {sym}: FAILED {e!r}')
        time.sleep(PACING_S)
    ib.disconnect()

    # ONE batched flush for every latest bar (cheapest write path)
    if latest_rows:
        table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
        with table.batch_writer(overwrite_by_pkeys=['pk', 'sk']) as bw:
            for r in latest_rows:
                bw.put_item(Item=r)
        log(f'[batch] wrote {len(latest_rows)} BAR# items to DynamoDB in one pass')

    log(f'DONE ok={ok} gapped={gapped} failed={failed}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
