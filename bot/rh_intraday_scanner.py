#!/usr/bin/env python3
"""LIVE intraday oversold scanner (paper first — places NO orders).

Why: the owner is right that we shouldn't be locked to the open/close. The validated
RSI(2) signal is computed on a close; this scanner approximates "today's close so far"
with the LIVE quote appended to the daily series, then recomputes RSI(2) and SMA200.
A name whose live RSI(2) just dropped into oversold is a mid-day dip — tradeable
throughout the session, and mid-session cost is 3.6bp (vs 12.1bp at the open).

Signal (all must hold on the LIVE quote):
  rsi2 < THRESH        (oversold)
  price > SMA200       (uptrend filter)
  price >= $2, dollar-vol >= $5M
  RTH only (9:30-16:00 ET), weekday

Output: a ranked list of live oversold candidates + a PAPER signal log
(RHSIG#... mode=PAPER, signal=LIVE_OVERSOLD). DRY_RUN=1 default -> never places.

Config: INTRADAY_RSI_THRESH (default 5), INTRADAY_SCAN_LIMIT (default 400 names).
"""
from __future__ import annotations
import io, os, sys, time, json
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

NY = ZoneInfo('America/New_York')
REGION = os.getenv('AWS_REGION', 'us-east-1')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

THRESH = float(os.getenv('INTRADAY_RSI_THRESH', '5'))
SCAN_LIMIT = int(os.getenv('INTRADAY_SCAN_LIMIT', '400'))
STALE_MAX_DAYS = int(os.getenv('INTRADAY_STALE_MAX_DAYS', '4'))
MIN_DV = 5e6
PRICE_LO = 2.0


def rsi(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50.0)


def in_rth(now=None):
    now = now or dt.datetime.now(NY)
    if now.weekday() >= 5:
        return False
    return dt.time(9, 30) <= now.time() <= dt.time(16, 0)


def universe():
    p = os.path.join(_ROOT, 'research', 'universe_1500.json')
    return list(dict.fromkeys(json.load(open(p))['symbols']))


def daily_tail(sym, s3, n=260):
    """Last n daily closes + SMA200/ATR context from the IBKR archive."""
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        return df.iloc[-n:]
    except Exception:
        return None


def main():
    if not in_rth():
        print('outside RTH — no intraday scan')
        return
    rh = RHClient()
    table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
    s3 = boto3.client('s3', region_name=REGION)
    syms = universe()[:SCAN_LIMIT]
    print(f'scanning {len(syms)} names live (RTH, {dt.datetime.now(NY).strftime("%H:%M")} ET)…')

    live = {}
    for i in range(0, len(syms), 60):
        try:
            for r in rh.get_quotes(syms[i:i + 60]):
                q = r.get('quote') or {}
                if q.get('symbol') and q.get('last_trade_price'):
                    live[q['symbol']] = float(q['last_trade_price'])
        except Exception as e:
            print(f'  quote chunk failed: {e!r}')
    print(f'  live quotes: {len(live)}')

    hits = []
    stale_skipped = 0
    for sym, px in live.items():
        if px < PRICE_LO:
            continue
        df = daily_tail(sym, s3)
        if df is None or len(df) < 250:
            continue
        # FRESHNESS GUARD: never compute a signal on a stale bar. The IBKR archive
        # must end within STALE_MAX_DAYS of today, else the RSI/SMA are lies.
        last_date = df.index[-1].date()
        age_days = (dt.datetime.now(NY).date() - last_date).days
        if age_days > STALE_MAX_DAYS:
            stale_skipped += 1
            continue
        closes = list(df['close'].values)
        sma200 = float(np.mean(closes[-200:]))
        if px <= sma200:
            continue
        dv = float((df['close'] * df['volume']).rolling(20).mean().iloc[-1])
        if dv < MIN_DV:
            continue
        # append live price as today's forming close, recompute RSI2
        series = pd.Series(closes + [px])
        r2 = float(rsi(series).iloc[-1])
        if r2 < THRESH:
            hits.append((sym, px, r2, sma200, dv))

    hits.sort(key=lambda x: x[2])  # most oversold first
    print(f'\n{len(hits)} live oversold candidate(s):')
    print(f'{"sym":8}{"price":>9}{"rsi2":>7}{"sma200":>9}{"$vol(M)":>9}')
    for sym, px, r2, m200, dv in hits:
        print(f'{sym:8}{px:>9.2f}{r2:>7.1f}{m200:>9.2f}{dv/1e6:>9.1f}')
        table.put_item(Item={
            'pk': f'RHSIG#{sym}', 'sk': f"intraday-{int(time.time())}",
            'action': 'SIGNAL', 'signal': 'LIVE_OVERSOLD', 'strategy': 'RSI2-intraday',
            'rsi2': str(round(r2, 2)), 'close': str(px), 'sma200': str(round(m200, 2)),
            'mode': 'PAPER', 'execution': 'NONE', 'ts': int(time.time())})
    print(f'\nlogged {len(hits)} paper signal(s). No orders placed (PAPER).')


if __name__ == '__main__':
    main()
