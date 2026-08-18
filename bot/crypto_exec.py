"""Crypto PAPER-EXECUTION — 24/7 forward-test with simulated fills + P&L ledger.

The crypto lane has been SIGNAL-ONLY (crypto_paper.py logs SIGNAL# and stops).
This module adds the execution half: it recomputes the same Donchian-20 +
200d-SMA momentum signal (long-only spot on Binance.US), then SIMULATES the
fills and tracks a paper position + realized P&L in DynamoDB, so the 24/7 lane
finally produces actual round-trips.

Fill model (honest, from the crypto sweep cost convention):
  - entry = live price * (1 + slippage); exit = live price * (1 - slippage)
  - slippage = 5 bps/side, taker fee = 10 bps round-trip
  - protective stop = 2*ATR(14) below entry (gap-aware: fill at live if < stop)
  - position size = 1% of a $10k paper sleeve / stop distance (capped at full sleeve)

Ledger (DynamoDB, same conventions as the futures bots):
  POSITION#<sym>_DONCH200  sk='current'   — the open paper position
  TRADE#<sym>_DONCH200     sk=<epoch>     — every simulated fill
  RISK#<date>/crypto       sk='summary'   — daily realized P&L + trade count

PAPER ONLY — no Binance.US account, no real orders, no money at risk.
Idempotent per 30-min cycle: the POSITION# state is the single source of truth
(flat -> enter on LONG; in-position -> exit on NONE or stop).
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

from bot.crypto_paper import (  # noqa: E402
    live_price, load_yf, merge_live, analyze, wilder_atr, UNIVERSE, FAMILY,
)

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

PAPER_CAPITAL = float(os.getenv('CRYPTO_PAPER_CAPITAL', '10000'))  # paper sleeve ($)
RISK_PCT = 0.01          # 1% risk per trade
SLIP_BPS = 0.0005        # 5 bps per side
FEE_BPS = 0.001          # 10 bps round-trip taker fee
MIN_BARS = 220


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
    """Accumulate realized P&L in RISK#<date>/crypto summary."""
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
        df = merge_live(load_yf(s3, u['yf']), px)
        if df is None or len(df) < MIN_BARS:
            print(f'  [{sym}] insufficient history — skip')
            continue
        signal, reason, extra = analyze(df)
        state = get_state(table, tag)
        pos = _f(state.get('pos'))

        if pos <= 0:
            # flat — enter on LONG
            if signal == 'LONG':
                entry = px * (1 + SLIP_BPS)
                stop = _f(extra.get('stop'))
                qty = size_qty(entry, stop)
                if qty <= 0:
                    print(f'  [{sym}] LONG but size=0 (stop/px degenerate) — skip')
                    continue
                if args.dry_run:
                    print(f'  [dry] {tag} BUY {qty:.6f} @ {entry:.2f} stop {stop:.2f}')
                else:
                    put_state(table, tag, pos=qty, side='LONG', entry=_s(entry),
                              stop=_s(stop), entry_ts=now_ts, session_date=today)
                    record_trade(table, tag, 'BUY', qty, entry, 'entry', 0.0, now_ts)
                print(f'  [{sym}] ENTER LONG {qty:.6f} @ {entry:.2f} (stop {stop:.2f}) — {reason}')
            else:
                print(f'  [{sym}] flat, no signal — {reason[:70]}')
        else:
            # in position — exit on stop or signal NONE
            entry = _f(state.get('entry'))
            stop = _f(state.get('stop'))
            exit_px = None
            exit_reason = None
            if px <= stop:
                exit_px = px * (1 - SLIP_BPS)   # gap-aware: filled at market below stop
                exit_reason = 'stop'
            elif signal == 'NONE':
                exit_px = px * (1 - SLIP_BPS)
                exit_reason = 'signal'
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
