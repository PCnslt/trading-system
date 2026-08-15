"""Crypto paper-SIGNAL lane — momentum + mean-reversion candidates (NO execution).

24/7 forward-test on Binance.US (live spot) + yfinance depth (S3 `yf/crypto`).
Execution stays MANUAL/paper — this lane emits SIGNAL#<sym>_<FAMILY> to DynamoDB
(sk = UTC date, overwritten each cycle = "current state") and snapshots history
to research/scan-results/crypto-signals/. No IBKR, no clientId, no orders
(execution='NONE'). Spot is LONG-only; shorts (perp/futures) are out of scope.

Universe:
  BTC-USD/BTCUSDT, ETH-USD/ETHUSDT  -> history = yf/crypto (2014->), live = Binance.US
  SOLUSDT, XRPUSDT                   -> history = crypto-candles/ (forward-collecting,
                                        ~2d today -> thin), live = Binance.US

Families (candidate until Gate-1 sweep promotes):
  MOM_DONCHIAN  close > prior 20d high        (LONG, stop 2*ATR)
  MR_RSI2       RSI(2) < 10                   (buy-dip LONG)
  MR_BBAND      close < lower Bollinger(20,2) (LONG)
  MOM_MA200     close vs 200d MA              (UP/DOWN trend state)
  MOM_CROSS     50d vs 200d MA                (GOLDEN/DEATH state)

Runs every 30 min 24/7 (idempotent: overwrites SIGNAL#/<UTC-date>, no RUN# dedupe).
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

from data.s3_archive import archive_scan_results  # noqa: E402

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
BINANCE_URL = 'https://api.binance.us/api/v3/ticker/price'

# yf_symbol -> binance_symbol; None yf_symbol => forward-collecting (candles only)
UNIVERSE = [
    {'yf': 'BTC-USD', 'binance': 'BTCUSDT', 'history': 'yf'},
    {'yf': 'ETH-USD', 'binance': 'ETHUSDT', 'history': 'yf'},
    {'yf': None,      'binance': 'SOLUSDT', 'history': 'candles'},
    {'yf': None,      'binance': 'XRPUSDT', 'history': 'candles'},
]

PROMOTED = {}          # {family: [sym, ...]} — filled after Gate-1 sweep
MIN_BARS = 25          # enough to compute at least a partial signal


def _s(v):
    try:
        f = float(v)
        return '' if f != f else str(round(f, 6))
    except (TypeError, ValueError):
        return str(v)


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


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


def load_candles(s3, binance_sym):
    r = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=f'crypto-candles/{binance_sym}/')
    rows = []
    for o in r.get('Contents', []):
        try:
            d = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=o['Key'])['Body'].read())
            rows.append(d)
        except Exception:
            continue
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values('date')
    df['ts'] = pd.to_datetime(df['date'])
    df = df.set_index('ts').sort_index()
    for col in ('open', 'high', 'low', 'close'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df[['open', 'high', 'low', 'close']]


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
    out = []
    c = df['close']
    last_close = float(c.iloc[-1])

    don_hi = df['high'].rolling(20).max().shift(1).iloc[-1]
    ma50 = c.rolling(50).mean().iloc[-1]
    ma200 = c.rolling(200).mean().iloc[-1]
    rsi2 = float(rsi(c, 2).iloc[-1])
    atr14 = float(wilder_atr(df['high'], df['low'], c, 14).iloc[-1])
    bb_lower = (c.rolling(20).mean() - 2 * c.rolling(20).std(ddof=0)).iloc[-1]

    def fin(v):
        return v if (v is not None and not (isinstance(v, float) and v != v)) else np.nan
    don_hi, ma50, ma200, bb_lower = (fin(x) for x in (don_hi, ma50, ma200, bb_lower))

    if not np.isnan(don_hi) and last_close > don_hi:
        out.append(('MOM_DONCHIAN', 'LONG', f'close {last_close:.2f} > 20d-high {don_hi:.2f}',
                    {'don_hi': _s(don_hi), 'atr': _s(atr14), 'stop': _s(last_close - 2 * atr14)}))
    else:
        out.append(('MOM_DONCHIAN', 'NONE', f'close {last_close:.2f} <= 20d-high {_s(don_hi)}',
                    {'don_hi': _s(don_hi), 'atr': _s(atr14)}))

    if rsi2 < 10:
        out.append(('MR_RSI2', 'LONG', f'RSI(2) {rsi2:.2f} < 10', {'rsi2': _s(rsi2)}))
    else:
        out.append(('MR_RSI2', 'NONE', f'RSI(2) {rsi2:.2f} >= 10', {'rsi2': _s(rsi2)}))

    if not np.isnan(bb_lower) and last_close < bb_lower:
        out.append(('MR_BBAND', 'LONG', f'close {last_close:.2f} < BB-lower {bb_lower:.2f}',
                    {'bb_lower': _s(bb_lower)}))
    else:
        out.append(('MR_BBAND', 'NONE', f'close {last_close:.2f} >= BB-lower {_s(bb_lower)}',
                    {'bb_lower': _s(bb_lower)}))

    if not np.isnan(ma200):
        st = 'UP' if last_close > ma200 else 'DOWN'
        out.append(('MOM_MA200', st, f'close {last_close:.2f} {"above" if st == "UP" else "below"} 200d-MA {ma200:.2f}',
                    {'ma200': _s(ma200)}))
    else:
        out.append(('MOM_MA200', 'NONE', 'insufficient history for 200d MA', {}))
    if not np.isnan(ma50) and not np.isnan(ma200):
        st = 'GOLDEN' if ma50 > ma200 else 'DEATH'
        out.append(('MOM_CROSS', st, f'50d-MA {ma50:.2f} {"above" if st == "GOLDEN" else "below"} 200d-MA {ma200:.2f}',
                    {'ma50': _s(ma50), 'ma200': _s(ma200)}))
    else:
        out.append(('MOM_CROSS', 'NONE', 'insufficient history for MA cross', {}))
    return out


def emit(table, sym, family, signal, close, reason, extra, today, dry_run):
    promoted = sym in PROMOTED.get(family, [])
    sig = {
        'signal': signal, 'strategy': family, 'close': _s(close), 'reason': reason,
        'ts': int(time.time()), 'candidate': not promoted, 'promoted': promoted,
        'mode': 'PAPER-SIGNAL', 'execution': 'NONE', 'venue': 'Binance.US (manual/paper)',
    }
    sig.update(extra)
    pk = f'SIGNAL#{sym}_{family}'
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

    payload = {'lane': 'crypto', 'date': today, 'signals': []}
    fired = []
    for u in UNIVERSE:
        binance_sym = u['binance']
        try:
            px = live_price(binance_sym)
        except Exception as e:
            print(f'  [{binance_sym}] live price failed: {e!r} — skip')
            continue
        if u['history'] == 'yf':
            df = load_yf(s3, u['yf'])
        else:
            df = load_candles(s3, binance_sym)
        df = merge_live(df, px)
        if df is None or len(df) < MIN_BARS:
            print(f'  [{binance_sym}] insufficient history ({0 if df is None else len(df)} bars) — '
                  f'forward-collecting, live {px:.4f}')
            # still record a thin-history marker so the symbol is visible
            emit(table, binance_sym, 'MOM_DONCHIAN', 'NONE', px,
                 f'insufficient history ({0 if df is None else len(df)} bars), live {px:.4f}',
                 {'live': _s(px)}, today, args.dry_run)
            payload['signals'].append({'sym': binance_sym, 'family': 'MOM_DONCHIAN',
                                       'signal': 'NONE', 'reason': 'insufficient history'})
            continue
        rows = analyze(df)
        for family, signal, reason, extra in rows:
            emit(table, binance_sym, family, signal, float(df['close'].iloc[-1]), reason, extra, today, args.dry_run)
            payload['signals'].append({'sym': binance_sym, 'family': family, 'signal': signal, 'reason': reason})
            if signal == 'LONG':
                fired.append(f'{binance_sym}:{family}')

    if not args.dry_run:
        try:
            archive_scan_results('crypto-signals', payload)
        except Exception as e:
            print(f'  signal archive failed: {e!r}')

    print(f'\ncrypto_signals done: {len(payload["signals"])} signal rows, '
          f'{len(fired)} LONG candidates: {", ".join(fired) if fired else "none"}')


if __name__ == '__main__':
    main()
