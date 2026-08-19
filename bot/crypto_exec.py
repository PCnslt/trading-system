"""Crypto PAPER-EXECUTION — 24/7 forward-test with simulated fills + P&L ledger.

Momentum strategy (the documented crypto edge — see research + web: time-series
momentum is the one family that survives realistic cost on crypto, while
mean-reversion dies). Pure Donchian-20 channel breakout, LONG-only spot:

  entry  = close > prior 20-day high   (fresh-high breakout)
  exit   = close < prior 20-day low    (channel breakdown) OR 2*ATR(14) stop

No 200d-SMA filter — the prior DONCH200 variant's 200d-SMA "regime filter" is
what made it a buy-and-hold proxy (long during every bull), inflating its PF.
The sweep's honest momentum numbers: BTC 1.17 / ETH 1.35 (marginal) but
SOL 2.30 / XRP 3.23 (strong). So the universe is BTC/ETH (deep history) + SOL/XRP
(strong momentum, forward-collecting candles).

Fill model (honest, from the crypto sweep cost convention):
  entry = live price * (1 + slippage); exit = live price * (1 - slippage)
  slippage = 5 bps/side, taker fee = 10 bps round-trip
  position size = 1% of a $10k paper sleeve / stop distance (capped at full sleeve)

Ledger (DynamoDB, same conventions as the futures bots):
  POSITION#<sym>_MOM20  sk='current'   — the open paper position
  TRADE#<sym>_MOM20     sk=<epoch>     — every simulated fill
  RISK#<date>/crypto    sk='summary'   — daily realized P&L + trade count

PAPER ONLY — no Binance.US account, no real orders, no money at risk.
"""
import os
import sys
import time
import argparse
import datetime as dt

import boto3
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, '.env'))

from bot.crypto_paper import live_price, load_yf, merge_live, wilder_atr  # noqa: E402
from bot.crypto_signals import load_candles  # noqa: E402

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

PAPER_CAPITAL = float(os.getenv('CRYPTO_PAPER_CAPITAL', '10000'))  # paper sleeve ($)
RISK_PCT = 0.01          # 1% risk per trade
SLIP_BPS = 0.0005        # 5 bps per side
FEE_BPS = 0.001          # 10 bps round-trip taker fee

FAMILY = 'MOM20'         # pure Donchian-20 momentum (replaces DONCH200)
LOOKBACK = 20
STOP_ATR = 2.0
MIN_BARS = 25            # enough for a Donchian-20 channel (vs 220 for the old 200d-SMA)

UNIVERSE = [
    {'yf': 'BTC-USD', 'binance': 'BTCUSDT', 'history': 'yf'},
    {'yf': 'ETH-USD', 'binance': 'ETHUSDT', 'history': 'yf'},
    {'yf': None,      'binance': 'SOLUSDT', 'history': 'candles'},
    {'yf': None,      'binance': 'XRPUSDT', 'history': 'candles'},
]


def _s(v):
    try:
        f = float(v)
        return '' if f != f else str(round(f, 6))
    except (TypeError, ValueError):
        return str(v)


def _f(v, default=0.0):
    try:
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def analyze_momentum(df):
    """Pure Donchian-20 channel: 'LONG' (breakout) / 'BREAKDOWN' / 'NONE'."""
    c = df['close']
    last_close = float(c.iloc[-1])
    don_hi = df['high'].rolling(LOOKBACK).max().shift(1).iloc[-1]
    don_lo = df['low'].rolling(LOOKBACK).min().shift(1).iloc[-1]
    atr14 = float(wilder_atr(df['high'], df['low'], c, 14).iloc[-1])

    def fin(v):
        return v if (v is not None and not (isinstance(v, float) and v != v)) else float('nan')

    don_hi, don_lo = fin(don_hi), fin(don_lo)
    import math
    if not math.isnan(don_hi) and last_close > don_hi:
        return ('LONG',
                f'close {last_close:.2f} > 20d-high {don_hi:.2f}',
                {'don_hi': _s(don_hi), 'don_lo': _s(don_lo), 'atr': _s(atr14),
                 'stop': _s(last_close - STOP_ATR * atr14)})
    if not math.isnan(don_lo) and last_close < don_lo:
        return ('BREAKDOWN',
                f'close {last_close:.2f} < 20d-low {don_lo:.2f}',
                {'don_hi': _s(don_hi), 'don_lo': _s(don_lo), 'atr': _s(atr14)})
    return ('NONE',
            f'close {last_close:.2f} inside 20d channel [{don_lo:.2f}, {don_hi:.2f}]',
            {'don_hi': _s(don_hi), 'don_lo': _s(don_lo), 'atr': _s(atr14)})


def get_state(table, tag):
    r = table.get_item(Key={'pk': f'POSITION#{tag}', 'sk': 'current'})
    return r.get('Item', {})


def clear_state(table, tag):
    table.delete_item(Key={'pk': f'POSITION#{tag}', 'sk': 'current'})


def put_state(table, tag, **fields):
    item = {'pk': f'POSITION#{tag}', 'sk': 'current',
            'strategy': FAMILY, 'ts': int(time.time()), **fields}
    table.put_item(Item=item)


def record_trade(table, tag, side, qty, px, reason, pnl, ts):
    table.put_item(Item={
        'pk': f'TRADE#{tag}', 'sk': str(ts),
        'side': side, 'qty': _s(qty), 'px': _s(px), 'pnl': _s(pnl),
        'reason': reason, 'strategy': FAMILY, 'venue': 'Binance.US (paper)',
        'mode': 'PAPER-EXEC', 'ts': ts,
    })


def add_pnl(table, date, pnl):
    r = table.get_item(Key={'pk': f'RISK#{date}', 'sk': 'crypto'})
    it = r.get('Item', {})
    cur = _f(it.get('realized_pnl')) + pnl
    n = int(it.get('trades', 0)) + 1
    table.put_item(Item={'pk': f'RISK#{date}', 'sk': 'crypto',
                         'realized_pnl': _s(cur), 'trades': n,
                         'strategy': FAMILY, 'ts': int(time.time())})


def size_qty(entry_px, stop_px):
    risk_usd = PAPER_CAPITAL * RISK_PCT
    stop_dist = entry_px - stop_px
    if stop_dist <= 0:
        return 0.0
    qty = risk_usd / stop_dist
    max_qty = PAPER_CAPITAL / entry_px   # no leverage
    return min(qty, max_qty)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    s3 = boto3.client('s3', region_name=AWS_REGION)
    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    today = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    now_ts = int(time.time())

    for u in UNIVERSE:
        sym = u['binance']
        tag = f'{sym}_{FAMILY}'
        try:
            px = live_price(sym)
        except Exception as e:
            print(f'  [{sym}] live price failed: {e!r} — skip')
            continue
        if u['history'] == 'yf':
            df = merge_live(load_yf(s3, u['yf']), px)
        else:
            df = merge_live(load_candles(s3, sym), px)
        if df is None or len(df) < MIN_BARS:
            print(f'  [{sym}] insufficient history ({0 if df is None else len(df)} bars) — skip')
            continue
        signal, reason, extra = analyze_momentum(df)
        state = get_state(table, tag)
        pos = _f(state.get('pos'))

        if pos <= 0:
            if signal == 'LONG':
                entry = px * (1 + SLIP_BPS)
                stop = _f(extra.get('stop'))
                qty = size_qty(entry, stop)
                if qty <= 0:
                    print(f'  [{sym}] LONG but size=0 (degenerate stop) — skip')
                    continue
                if args.dry_run:
                    print(f'  [dry] {tag} BUY {qty:.6f} @ {entry:.2f} stop {stop:.2f}')
                else:
                    put_state(table, tag, pos=_s(qty), side='LONG', entry=_s(entry),
                              stop=_s(stop), entry_ts=now_ts, session_date=today)
                    record_trade(table, tag, 'BUY', qty, entry, 'breakout', 0.0, now_ts)
                print(f'  [{sym}] ENTER LONG {qty:.6f} @ {entry:.2f} (stop {stop:.2f}) — {reason}')
            else:
                print(f'  [{sym}] flat — {reason[:70]}')
        else:
            entry = _f(state.get('entry'))
            stop = _f(state.get('stop'))
            exit_px = None
            exit_reason = None
            if px <= stop:
                exit_px = px * (1 - SLIP_BPS)
                exit_reason = 'stop'
            elif signal == 'BREAKDOWN':
                exit_px = px * (1 - SLIP_BPS)
                exit_reason = 'breakdown'
            if exit_px is not None:
                gross = (exit_px - entry) * pos
                fee = (entry + exit_px) * pos * (FEE_BPS / 2)
                pnl = gross - fee
                if args.dry_run:
                    print(f'  [dry] {tag} SELL {pos:.6f} @ {exit_px:.2f} pnl {pnl:.2f} ({exit_reason})')
                else:
                    record_trade(table, tag, 'SELL', pos, exit_px, exit_reason, pnl, now_ts)
                    clear_state(table, tag)
                    add_pnl(table, today, pnl)
                print(f'  [{sym}] EXIT ({exit_reason}) {pos:.6f} @ {exit_px:.2f} pnl {pnl:.2f}')
            else:
                print(f'  [{sym}] holding {pos:.6f} @ {entry:.2f} (stop {stop:.2f}, px {px:.2f})')

    print('\ncrypto_exec done.')


if __name__ == '__main__':
    main()
