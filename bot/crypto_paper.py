"""SUPERSEDED signal lane (2026-08-19): DONCH200 replaced by crypto_exec.py (MOM20).
Kept as a SHARED HELPER MODULE — live_price / load_yf / merge_live / wilder_atr are
imported by crypto_exec.py. The signal-lane main() below is retired (no cron runs it);
do NOT invoke this file as a script.

Crypto PAPER forward-test — PROMOTED strategy: Donchian-20 + 200d-SMA filter.

Promoted by research/CRYPTO_SWEEP.md as the single best crypto edge:
DONCHIAN_20+200d — full PF 2.35, OOS PF 1.50 (n=79), maxDD -44%, and every cell
of the fee/slip grid holds PF >= 1.9. Entry = close > prior 20d high AND close >
200d SMA (long-only spot); 2*ATR(14) protective-stop distance reported.

FLAG — buy-and-hold proxy, LOWEST live-priority. The 200d SMA is a regime
filter; the edge is essentially "long above the 200d SMA" and its PF is inflated
by secular bull regimes (2017, 2020-21, 2024-25). It is NOT a repeatable
short-term signal and will decay in a multi-year bear. Crypto remains the
LOWEST live-priority lane (owner distrusts it). Signal-only; execution='NONE'.

Universe: BTC-USD/BTCUSDT, ETH-USD/ETHUSDT (history = S3 yf/crypto, live = Binance.US).
Emits SIGNAL#<sym>_DONCH200 to DynamoDB (sk = UTC date, overwritten each cycle =
"current state") and snapshots history to S3 research/scan-results/crypto-paper/.
Runs on the same cadence as crypto_signals (idempotent overwrite).
"""
import argparse
import json
import os
import sys
import time
import datetime as dt

import numpy as np
import pandas as pd
import boto3
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
# --- SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb
_sb()

from data.s3_archive import archive_scan_results  # noqa: E402

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
BINANCE_URL = 'https://api.binance.us/api/v3/ticker/price'

UNIVERSE = [
    {'yf': 'BTC-USD', 'binance': 'BTCUSDT'},
    {'yf': 'ETH-USD', 'binance': 'ETHUSDT'},
]

FAMILY = 'DONCH200'
FLAG = 'buy-and-hold proxy (200d-SMA regime filter); LOWEST live-priority'
MIN_BARS = 220        # enough to compute a 200d SMA
LOOKBACK = 20
STOP_ATR = 2.0


def _s(v):
    try:
        f = float(v)
        return '' if f != f else str(round(f, 6))
    except (TypeError, ValueError):
        return str(v)


def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def live_price(binance_sym):
    r = requests.get(BINANCE_URL, params={'symbol': binance_sym}, timeout=15)
    r.raise_for_status()
    return float(r.json()['price'])


def load_yf(s3, yf_sym):
    key = f'yf/crypto/{yf_sym}.json'
    try:
        o = s3.get_object(Bucket=S3_BUCKET, Key=key)
        d = json.loads(o['Body'].read())
    except Exception as e:
        print(f'  [{yf_sym}] S3 load failed: {e!r}')
        return None
    daily = d.get('daily', [])
    if not daily:
        return None
    df = pd.DataFrame(daily)
    df['ts'] = pd.to_datetime(df['ts'])
    df = df.set_index('ts').sort_index()
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def merge_live(df, px):
    """Append/refresh today's running bar from the live price (UTC daily boundary)."""
    now = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
    if df is None or df.empty:
        df = pd.DataFrame(columns=['open', 'high', 'low', 'close'])
    if len(df) and df.index[-1].normalize() == now:
        df.loc[df.index[-1], 'close'] = px
        df.loc[df.index[-1], 'high'] = max(float(df.iloc[-1]['high']), px)
        df.loc[df.index[-1], 'low'] = min(float(df.iloc[-1]['low']), px)
    else:
        prev = float(df.iloc[-1]['close']) if len(df) else px
        df.loc[now] = {'open': prev, 'high': max(prev, px), 'low': min(prev, px), 'close': px}
    return df


def analyze(df):
    c = df['close']
    last_close = float(c.iloc[-1])
    don_hi = df['high'].rolling(LOOKBACK).max().shift(1).iloc[-1]
    ma200 = c.rolling(200).mean().iloc[-1]
    atr14 = float(wilder_atr(df['high'], df['low'], c, 14).iloc[-1])

    def fin(v):
        return v if (v is not None and not (isinstance(v, float) and v != v)) else np.nan

    don_hi, ma200 = fin(don_hi), fin(ma200)

    # Donchian-20 + 200d-SMA filter: LONG only when BOTH hold.
    if not np.isnan(don_hi) and last_close > don_hi:
        if not np.isnan(ma200) and last_close > ma200:
            return ('LONG',
                    f'close {last_close:.2f} > 20d-high {don_hi:.2f} AND > 200d-SMA {ma200:.2f}',
                    {'don_hi': _s(don_hi), 'ma200': _s(ma200), 'atr': _s(atr14),
                     'stop': _s(last_close - STOP_ATR * atr14)})
        return ('NONE',
                f'close {last_close:.2f} > 20d-high {don_hi:.2f} but <= 200d-SMA {_s(ma200)} (200d filter)',
                {'don_hi': _s(don_hi), 'ma200': _s(ma200), 'atr': _s(atr14)})
    return ('NONE', f'close {last_close:.2f} <= 20d-high {_s(don_hi)}',
            {'don_hi': _s(don_hi), 'ma200': _s(ma200), 'atr': _s(atr14)})


def emit(table, sym, signal, close, reason, extra, today, dry_run):
    sig = {
        'signal': signal, 'strategy': FAMILY, 'close': _s(close), 'reason': reason,
        'ts': int(time.time()), 'promoted': True, 'candidate': False,
        'mode': 'PAPER-SIGNAL', 'execution': 'NONE', 'venue': 'Binance.US (manual/paper)',
        'flag': FLAG,
    }
    sig.update(extra)
    pk = f'SIGNAL#{sym}_{FAMILY}'
    if dry_run:
        print(f'  [dry] {pk}: {signal} — {reason}')
        return
    table.put_item(Item={'pk': pk, 'sk': today, **sig})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    s3 = boto3.client('s3', region_name=AWS_REGION)
    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    today = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')

    payload = {'lane': 'crypto', 'strategy': FAMILY, 'flag': FLAG, 'date': today, 'signals': []}
    fired = []
    for u in UNIVERSE:
        binance_sym = u['binance']
        try:
            px = live_price(binance_sym)
        except Exception as e:
            print(f'  [{binance_sym}] live price failed: {e!r} — skip')
            continue
        df = load_yf(s3, u['yf'])
        df = merge_live(df, px)
        if df is None or len(df) < MIN_BARS:
            print(f'  [{binance_sym}] insufficient history ({0 if df is None else len(df)} bars) — skip')
            continue
        signal, reason, extra = analyze(df)
        emit(table, binance_sym, signal, float(df['close'].iloc[-1]), reason, extra, today, args.dry_run)
        payload['signals'].append({'sym': binance_sym, 'signal': signal, 'reason': reason})
        if signal == 'LONG':
            fired.append(binance_sym)

    if not args.dry_run:
        try:
            archive_scan_results('crypto-paper', payload)
        except Exception as e:
            print(f'  signal archive failed: {e!r}')

    print(f'\ncrypto_paper done: {len(payload["signals"])} signal rows, '
          f'LONG: {", ".join(fired) if fired else "none"}')


if __name__ == '__main__':
    main()

