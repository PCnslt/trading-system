"""Gold (GC) momentum paper-SIGNAL lane — futures, signal-only (NO execution).

SUPERSEDED 2026-08-16: this lane was promoted to paper EXECUTION — see
`bot/live_gc.py`. The `paper_gc_signals.sh` cron is retired; `live_gc.py` writes
the SAME `SIGNAL#GC_DONCHIAN` / `SIGNAL#GC_TSMOM` keys plus `TRADE#`/`POSITION#`
and routes orders to IBKR paper (GC contract, clientId 78). This file is kept for
reference/optionality (it still runs correctly if invoked by hand).

Original purpose below.

Promoted by research/EDGE_SWEEP.md: the single strongest, best-confirmed futures
edge is GOLD MOMENTUM — Donchian long/short (full PF 1.45, OOS 1.81, IBKR ~3y
1.31, 3-tick 1.42) and TSMOM sign-of-12m-return (1.37 / 1.73 / 1.99 / 1.35).
Both agree across yfinance (16y) and IBKR futures-bars on the SAME direction and
survive 3-tick slippage.

This lane forward-tests those signals on GC daily (yfinance GC=F — same % action
as the GC contract) at EOD, daily like live.py (19:00 ET cadence). It writes
SIGNAL#GC_DONCHIAN / SIGNAL#GC_TSMOM to DynamoDB (sk = UTC date, overwritten each
cycle) and snapshots history to S3 research/scan-results/gc-signals/.

Signal-only: execution='NONE'. No IBKR, no clientId, no orders. (GC COMEX L1 is
DELAYED on paper — metals — so paper execution would be wrong-footed anyway; a
signal lane is the correct first step. Paper execution is a later gate.)

Strategies:
  DONCHIAN     close > prior 20d high -> LONG ; close < prior 20d low -> SHORT
               (2*ATR(14) protective-stop distance reported per side)
  TSMOM        sign of 12-month return -> LONG (>0) / SHORT (<0)
               (monthly rebalance in backtest; reported here as current direction)

Runs daily after US close (yf refreshes ~18:30 ET). Dedupe: RUN#gc_signals/<date>.
"""
import argparse
import os
import sys
import time
import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf
import boto3
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from data.s3_archive import archive_scan_results  # noqa: E402

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

DATA_TICKER = 'GC=F'       # COMEX gold continuous (yfinance) — % action == GC contract
SYMBOL = 'GC'
MIN_BARS = 260             # >= 1y so TSMOM's 12m return is computable
LOOKBACK = 20
TSMOM_LOOKBACK = 252       # ~12 months of trading days
STOP_ATR = 2.0


def _s(v):
    try:
        f = float(v)
        return '' if f != f else str(round(f, 4))
    except (TypeError, ValueError):
        return str(v)


def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def fetch():
    df = yf.download(DATA_TICKER, period='3y', interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def analyze(df):
    h, l, c = df['High'], df['Low'], df['Close']
    last_close = float(c.iloc[-1])
    don_hi = h.rolling(LOOKBACK).max().shift(1).iloc[-1]
    don_lo = l.rolling(LOOKBACK).min().shift(1).iloc[-1]
    atr14 = float(wilder_atr(h, l, c, 14).iloc[-1])
    ret_12m = float(c.iloc[-1] / c.iloc[-TSMOM_LOOKBACK] - 1.0)

    def fin(v):
        return v if (v is not None and not (isinstance(v, float) and v != v)) else np.nan

    don_hi, don_lo = fin(don_hi), fin(don_lo)

    out = []
    # Donchian long/short breakout
    if not np.isnan(don_hi) and last_close > don_hi:
        out.append(('DONCHIAN', 'LONG',
                    f'close {last_close:.2f} > 20d-high {don_hi:.2f}',
                    {'don_hi': _s(don_hi), 'atr': _s(atr14),
                     'stop': _s(last_close - STOP_ATR * atr14)}))
    elif not np.isnan(don_lo) and last_close < don_lo:
        out.append(('DONCHIAN', 'SHORT',
                    f'close {last_close:.2f} < 20d-low {don_lo:.2f}',
                    {'don_lo': _s(don_lo), 'atr': _s(atr14),
                     'stop': _s(last_close + STOP_ATR * atr14)}))
    else:
        out.append(('DONCHIAN', 'NONE',
                    f'close {last_close:.2f} within [{_s(don_lo)}, {_s(don_hi)}]',
                    {'don_hi': _s(don_hi), 'don_lo': _s(don_lo), 'atr': _s(atr14)}))

    # TSMOM — sign of 12-month return
    if ret_12m > 0:
        out.append(('TSMOM', 'LONG', f'12m return {ret_12m:.2%} > 0',
                    {'ret_12m': _s(ret_12m)}))
    elif ret_12m < 0:
        out.append(('TSMOM', 'SHORT', f'12m return {ret_12m:.2%} < 0',
                    {'ret_12m': _s(ret_12m)}))
    else:
        out.append(('TSMOM', 'NONE', f'12m return {ret_12m:.2%} flat',
                    {'ret_12m': _s(ret_12m)}))
    return out, last_close


def emit(table, family, signal, close, reason, extra, today, dry_run):
    sig = {
        'signal': signal, 'strategy': family, 'close': _s(close), 'reason': reason,
        'ts': int(time.time()), 'promoted': True, 'candidate': False,
        'mode': 'PAPER-SIGNAL', 'execution': 'NONE', 'venue': 'futures (GC) — manual/paper',
    }
    sig.update(extra)
    pk = f'SIGNAL#{SYMBOL}_{family}'
    if dry_run:
        print(f'  [dry] {pk}: {signal} — {reason}')
        return
    table.put_item(Item={'pk': pk, 'sk': today, **sig})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='compute + print, no DynamoDB/S3 writes')
    args = ap.parse_args()

    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()

    # once-per-day dedupe (fail-open on read error, like equity_signals)
    if not args.dry_run:
        try:
            if table.get_item(Key={'pk': 'RUN#gc_signals', 'sk': today}).get('Item'):
                print(f'[{today}] gc_signals already ran today — skip')
                return
        except Exception as e:
            print(f'[{today}] dedupe read failed (fail-open): {e!r}')

    df = fetch()
    if df is None or df.empty or len(df) < MIN_BARS:
        print(f'[{today}] insufficient data ({0 if df is None else len(df)} bars) — skip')
        return

    rows, last_close = analyze(df)
    payload = {'lane': 'futures', 'symbol': SYMBOL, 'date': today, 'signals': []}
    fired = []
    for family, signal, reason, extra in rows:
        emit(table, family, signal, last_close, reason, extra, today, args.dry_run)
        payload['signals'].append({'family': family, 'signal': signal, 'reason': reason})
        if signal in ('LONG', 'SHORT'):
            fired.append(family)

    if not args.dry_run:
        try:
            archive_scan_results('gc-signals', payload)
        except Exception as e:
            print(f'  signal archive failed: {e!r}')
        try:
            table.put_item(Item={'pk': 'RUN#gc_signals', 'sk': today, 'ts': int(time.time())})
        except Exception as e:
            print(f'  dedupe marker write failed: {e!r}')

    print(f'\ngc_signals done: {len(rows)} signal rows, fired: {", ".join(fired) if fired else "none"}')


if __name__ == '__main__':
    main()
