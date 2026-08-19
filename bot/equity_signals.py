"""Equities paper-SIGNAL lane — momentum + mean-reversion candidates (NO execution).

Robinhood ORDER execution stays MANUAL on the laptop side (owner directs). This
VPS lane RESEARCHES + SIGNALS only: it reads yfinance daily+hourly depth from S3
(`yf/etfs` + `yf/sectors`), computes candidate-family signals on the latest daily
bar, and logs them to DynamoDB under `SIGNAL#<sym>_<FAMILY>` (sk = date). It NEVER
connects to IBKR and NEVER places an order (execution='NONE').

Families (all logged as CANDIDATE until a Gate-1 sweep promotes them):
  Entry candidates (signal = LONG / NONE):
    MOM_DONCHIAN  close > prior 20-day high            (stop 2*ATR)
    MR_RSI2       RSI(2) < 10                          (buy-the-dip)
    MR_BBAND      close < lower Bollinger(20,2)
    MR_REV5       5-day return < -5%
  Trend-state (informational, signal = UP/DOWN / GOLDEN/DEATH):
    MOM_MA200     close vs 200-day MA
    MOM_CROSS     50-day vs 200-day MA

Runs daily after US close (yf refreshes ~18:30 ET). Dedupe: RUN#equity_signals/<date>.
Forward-test history: one S3 snapshot per run under research/scan-results/equity-signals/.

Paper only. LIVE env var is unused here — there is no execution path in this file.
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
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
# --- SSM-first secrets (infra/ssm_secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.ssm_secrets import bootstrap as _sb
_sb()

from data.s3_archive import archive_scan_results  # noqa: E402

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

UNIVERSE = {
    'etfs':    ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI'],
    'sectors': ['XLF', 'XLK', 'XLE', 'XLV', 'XLP', 'XLY', 'XLI', 'XLB', 'XLU', 'XLRE'],
}

# Families promoted to "paper-forward" status by the equities edge sweep
# (research/EQUITIES_SWEEP.md §7 verdict rollup). A promoted entry carries
# promoted=True; everything else stays candidate. Execution stays 'NONE' either
# way (Robinhood manual — owner directs, correct).
#   MR_RSI2       = RSI(2)<10 buy-the-dip (the champion — robust in BOTH regimes)
#                   VALIDATED 11/15 symbols (adds XLY — was missing from the §6
#                   prose list but is P in the per-symbol table: 1.71/1.74 n=109).
#   MOM_DONCHIAN  = 20d breakout, gated by close > 200d MA (regime-conditional)
#                   VALIDATED 9/15 symbols (regime-conditional).
PROMOTED = {
    'MR_RSI2': ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'XLF', 'XLK', 'XLV', 'XLP', 'XLY', 'XLI'],
    'MOM_DONCHIAN': ['SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'XLF', 'XLK', 'XLY', 'XLI'],
}

# thresholds
REV5_THRESHOLD = -0.05     # 5-day return below this -> reversal LONG
MIN_BARS = 60              # minimum daily bars to compute signals at all


def _s(v):
    """Stringify a float for DynamoDB; NaN -> ''."""
    try:
        f = float(v)
        return '' if f != f else str(round(f, 4))
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


def load_yf(s3, sym, asset_class):
    """S3 yf/<class>/<sym>.json -> daily DataFrame (index=ts, lowercase cols), or None."""
    key = f'yf/{asset_class}/{sym}.json'
    try:
        o = s3.get_object(Bucket=S3_BUCKET, Key=key)
        d = json.loads(o['Body'].read())
    except Exception as e:
        print(f'  [{sym}] S3 load failed: {e!r}')
        return None
    daily = d.get('daily', [])
    if not daily:
        print(f'  [{sym}] no daily bars in S3')
        return None
    df = pd.DataFrame(daily)
    df['ts'] = pd.to_datetime(df['ts'])
    df = df.set_index('ts').sort_index()
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def emit(table, sym, family, signal, close, reason, extra, today, dry_run):
    promoted = sym in PROMOTED.get(family, [])
    sig = {
        'signal': signal,
        'strategy': family,
        'close': _s(close),
        'reason': reason,
        'ts': int(time.time()),
        'candidate': not promoted,
        'promoted': promoted,
        'mode': 'PAPER-SIGNAL',
        'execution': 'NONE',
        'venue': 'Robinhood manual (laptop)',
    }
    sig.update(extra)
    pk = f'SIGNAL#{sym}_{family}'
    if dry_run:
        print(f'  [dry] {pk}: {signal} — {reason}')
        return
    table.put_item(Item={'pk': pk, 'sk': today, **sig})


def analyze(df):
    """Latest-bar indicator values + all-family signal decisions. Returns list of dicts."""
    out = []
    c = df['close']
    last_close = float(c.iloc[-1])

    don_hi = df['high'].rolling(20).max().shift(1).iloc[-1]
    don_lo = df['low'].rolling(20).min().shift(1).iloc[-1]
    ma50 = c.rolling(50).mean().iloc[-1]
    ma200 = c.rolling(200).mean().iloc[-1]
    rsi2 = float(rsi(c, 2).iloc[-1])
    atr14 = float(wilder_atr(df['high'], df['low'], c, 14).iloc[-1])
    ma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std(ddof=0)
    bb_lower = (ma20 - 2 * sd20).iloc[-1]
    ret5 = float(c.pct_change(5).iloc[-1])

    def fin(v):
        return v if (v is not None and not (isinstance(v, float) and v != v)) else np.nan

    don_hi, don_lo, ma50, ma200, bb_lower = (fin(x) for x in (don_hi, don_lo, ma50, ma200, bb_lower))

    # ---- entry candidates ----
    # Donchian breakout is regime-conditional: the edge only lives when
    # close > 200d MA (the 2009+ bull regime; it LOST money pre-2009). Gate is
    # mandatory — a breakout below the 200d MA is a no-trade, not a LONG.
    if not np.isnan(don_hi) and last_close > don_hi:
        if not np.isnan(ma200) and last_close > ma200:
            out.append(('MOM_DONCHIAN', 'LONG',
                        f'close {last_close:.2f} > 20d-high {don_hi:.2f} AND > 200d-MA {ma200:.2f}',
                        {'don_hi': _s(don_hi), 'ma200': _s(ma200), 'atr': _s(atr14),
                         'stop': _s(last_close - 2 * atr14)}))
        else:
            out.append(('MOM_DONCHIAN', 'NONE',
                        f'close {last_close:.2f} > 20d-high {don_hi:.2f} but <= 200d-MA {_s(ma200)} (regime gate)',
                        {'don_hi': _s(don_hi), 'ma200': _s(ma200), 'atr': _s(atr14)}))
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

    if not np.isnan(ret5) and ret5 < REV5_THRESHOLD:
        out.append(('MR_REV5', 'LONG', f'5d ret {ret5:.2%} < {REV5_THRESHOLD:.0%}',
                    {'ret5': _s(ret5)}))
    else:
        out.append(('MR_REV5', 'NONE', f'5d ret {_s(ret5):} >= {REV5_THRESHOLD:.0%}',
                    {'ret5': _s(ret5)}))

    # ---- trend state ----
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='compute + print, no DynamoDB/S3 writes')
    args = ap.parse_args()

    s3 = boto3.client('s3', region_name=AWS_REGION)
    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()

    # once-per-day dedupe (fail-open on read error, like control.already_ran_today)
    if not args.dry_run:
        try:
            if table.get_item(Key={'pk': 'RUN#equity_signals', 'sk': today}).get('Item'):
                print(f'[{today}] equity_signals already ran today — skip')
                return
        except Exception as e:
            print(f'[{today}] dedupe read failed (fail-open): {e!r}')

    payload = {'lane': 'equities', 'date': today, 'signals': []}
    fired = []
    for asset_class, syms in UNIVERSE.items():
        for sym in syms:
            df = load_yf(s3, sym, asset_class)
            if df is None or len(df) < MIN_BARS:
                print(f'  [{sym}] insufficient data ({0 if df is None else len(df)} bars) — skip')
                continue
            rows = analyze(df)
            for family, signal, reason, extra in rows:
                emit(table, sym, family, signal, float(df['close'].iloc[-1]), reason, extra, today, args.dry_run)
                payload['signals'].append({'sym': sym, 'family': family, 'signal': signal, 'reason': reason})
                if signal in ('LONG',):
                    fired.append(f'{sym}:{family}')

    # forward-test history snapshot (idempotent per run; timestamped)
    if not args.dry_run:
        try:
            archive_scan_results('equity-signals', payload)
        except Exception as e:
            print(f'  signal archive failed: {e!r}')
        try:
            table.put_item(Item={'pk': 'RUN#equity_signals', 'sk': today, 'ts': int(time.time())})
        except Exception as e:
            print(f'  dedupe marker write failed: {e!r}')

    print(f'\nequity_signals done: {len(payload["signals"])} signal rows, '
          f'{len(fired)} LONG candidates: {", ".join(fired) if fired else "none"}')


if __name__ == '__main__':
    main()

