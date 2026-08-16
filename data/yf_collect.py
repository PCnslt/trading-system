#!/usr/bin/env python3
"""yfinance broad-universe collector — FREE historical depth (no IBKR, no clientId).

Fills the DEPTH gap the IBKR entitlement can't: yfinance daily history goes back
~10-16y (vs IBKR daily ~3y index / ~16mo rates) and 1h intraday ~2y. This is an
UNOFFICIAL source (no SLA, symbol/interval quirks) — treat as research-grade
depth, NOT a replacement for the paid IBKR archive (futures-bars/).

Universe (distinct S3 prefix `yf/<asset-class>/<sym>.json`):
  etfs     SPY QQQ IWM DIA VTI
  sectors  XLF XLK XLE XLV XLP XLY XLI XLB XLU XLRE
  futures  ES=F NQ=F YM=F RTY=F CL=F GC=F SI=F NG=F ZN=F ZB=F 6E=F ZC=F ZW=F ZS=F
  fx       EURUSD=X GBPUSD=X USDJPY=X AUDUSD=X USDCAD=X USDCHF=X NZDUSD=X
  crypto   BTC-USD ETH-USD   (Binance.US covers live ticks; yfinance adds spot cross-check)

Idempotent + self-healing: each run overwrites the same <sym>.json key, so a
missed cron tick or a symbol that failed mid-run self-heals on the next run.

Usage:
  python data/yf_collect.py                 # full universe
  python data/yf_collect.py --class etfs    # one asset class
  python data/yf_collect.py --symbols SPY,QQQ
  python data/yf_collect.py --daily-only    # skip 1h intraday
"""
import argparse
import os
import sys
import time
import json
import datetime as dt

import boto3
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
# --- SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb
_sb()

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PACING_S = float(os.getenv('YF_PACING_S', '1.5'))

YF_UNIVERSE = {
    'etfs':     ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI'],
    'sectors':  ['XLF', 'XLK', 'XLE', 'XLV', 'XLP', 'XLY', 'XLI', 'XLB', 'XLU', 'XLRE'],
    'futures':  ['ES=F', 'NQ=F', 'YM=F', 'RTY=F', 'CL=F', 'GC=F', 'SI=F', 'NG=F',
                 'ZN=F', 'ZB=F', '6E=F', 'ZC=F', 'ZW=F', 'ZS=F'],
    'fx':       ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'AUDUSD=X', 'USDCAD=X',
                 'USDCHF=X', 'NZDUSD=X',
                 # key crosses (non-USD pairs of the G7 majors) — 2026-08-15
                 'EURGBP=X', 'EURJPY=X', 'EURCHF=X', 'EURAUD=X', 'EURCAD=X', 'EURNZD=X',
                 'GBPJPY=X', 'GBPCHF=X', 'GBPAUD=X', 'GBPCAD=X', 'GBPNZD=X',
                 'AUDJPY=X', 'AUDCAD=X', 'AUDCHF=X', 'AUDNZD=X',
                 'CADJPY=X', 'CADCHF=X', 'CHFJPY=X',
                 'NZDJPY=X', 'NZDCAD=X', 'NZDCHF=X'],
    'crypto':   ['BTC-USD', 'ETH-USD'],
}


def _f(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _flatten(df):
    """Normalize yfinance output: drop MultiIndex columns, tz-naive index."""
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _records(df):
    out = []
    for idx, r in df.iterrows():
        out.append({
            'ts': idx.isoformat(),
            'open': _f(r.get('Open')), 'high': _f(r.get('High')),
            'low': _f(r.get('Low')), 'close': _f(r.get('Close')),
            'volume': _f(r.get('Volume')),
        })
    return out


def download(sym, interval, period):
    """yfinance download -> flattened OHLCV DataFrame (empty on any failure)."""
    try:
        df = yf.download(sym, period=period, interval=interval,
                         progress=False, auto_adjust=False)
        return _flatten(df)
    except Exception as e:
        print(f"    [{sym}] {interval} download error: {e!r}")
        return pd.DataFrame()


def collect_symbol(s3, asset_class, sym, do_intraday):
    daily = download(sym, '1d', 'max')
    hourly = download(sym, '1h', '730d') if do_intraday else pd.DataFrame()

    if daily.empty and hourly.empty:
        print(f"  [{sym}] NO DATA (bad ticker / rate-limited) — skip")
        return 0

    payload = {
        'symbol': sym,
        'asset_class': asset_class,
        'source': 'yfinance',
        'daily': _records(daily),
        'hourly': _records(hourly),
        'fetchedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    key = f'yf/{asset_class}/{sym}.json'
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=json.dumps(payload, default=str))
    dr = f"{payload['daily'][0]['ts'][:10]}..{payload['daily'][-1]['ts'][:10]}" if payload['daily'] else '-'
    hr = f"{payload['hourly'][0]['ts'][:10]}..{payload['hourly'][-1]['ts'][:10]}" if payload['hourly'] else '-'
    print(f"  [{sym}] daily={len(payload['daily'])} ({dr}) hourly={len(payload['hourly'])} ({hr}) "
          f"-> s3://{S3_BUCKET}/{key}")
    return len(payload['daily']) + len(payload['hourly'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--class', dest='asset_class', default='', help='one asset class (etfs/sectors/futures/fx/crypto)')
    ap.add_argument('--symbols', default='', help='comma subset')
    ap.add_argument('--daily-only', action='store_true')
    args = ap.parse_args()

    s3 = boto3.client('s3', region_name=AWS_REGION)
    do_intraday = not args.daily_only

    targets = []
    for ac, syms in YF_UNIVERSE.items():
        if args.asset_class and ac != args.asset_class:
            continue
        for s in syms:
            if args.symbols and s not in {x.strip() for x in args.symbols.split(',') if x.strip()}:
                continue
            targets.append((ac, s))

    total = 0
    for i, (ac, sym) in enumerate(targets):
        if i > 0:
            time.sleep(PACING_S)
        try:
            total += collect_symbol(s3, ac, sym, do_intraday)
        except Exception as e:
            print(f"  [{sym}] FAILED: {e!r}")
    print(f"\nDONE: {len(targets)} symbols, {total} rows -> S3 yf/ (daily max-history + 1h/2y).")


if __name__ == '__main__':
    main()

