"""Multi-strategy signal engine (Phase 2) — run every registry strategy over the
broad universe and emit per-strategy PAPER signals.

This is the strategy-agnostic engine: it reuses the shared data/indicator layer
(fetch_batch, indicators, flush_writes) and dispatches to bot/strategies.py, so
adding a strategy is a one-line registry entry + a predicate — no execution code
changes. It is PAPER-only and never touches the live RSI2 lane (live_equities.py).

Writes per-signal rows MSIG#<SYM>_<STRAT> (sk = date) + a daily summary.

Usage:
  python bot/live_multi.py --dry-run            # compute + print, no writes
  python bot/live_multi.py                      # write MSIG# signals (paper)
"""
import argparse
import datetime as dt
import os
import sys
import time

import boto3
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from bot.live_equities import (  # noqa: E402  (shared data/indicator layer)
    fetch_batch, indicators, flush_writes, _load_broad_universe, _f, _s, put_item,
)
from bot.strategies import STRATEGIES  # noqa: E402

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()

    syms = _load_broad_universe()
    syms = syms[:args.limit] if args.limit else syms
    print(f'multi-strategy scan: {len(syms)} names x {len(STRATEGIES)} strategies')

    bars = fetch_batch(syms)
    print(f'  got {len(bars)}/{len(syms)} bars')

    counts = {s: 0 for s in STRATEGIES}
    candidates = {s: [] for s in STRATEGIES}
    for sym in syms:
        df = bars.get(sym)
        if df is None or len(df) < 260:
            continue
        d = indicators(df)
        last = d.iloc[-1]
        close_series = df['close']
        sig = {
            'close': _f(last['close']), 'rsi2': _f(last['rsi2']),
            'sma200': _f(last['sma200']), 'atr14': _f(last['atr14']),
            'drop2': _f(close_series.iloc[-1]) - _f(close_series.iloc[-3]),
        }
        for strat, cfg in STRATEGIES.items():
            if cfg['entry'](sig):
                counts[strat] += 1
                candidates[strat].append((sym, sig['rsi2'], sig['drop2'], sig['atr14']))
                put_item(table, f'MSIG#{sym}_{strat}', today, {
                    'strategy': strat, 'signal': 'LONG', 'family': cfg['family'],
                    'close': _s(sig['close']), 'rsi2': _s(sig['rsi2']),
                    'sma200': _s(sig['sma200']), 'atr14': _s(sig['atr14']),
                    'drop2': _s(sig['drop2']), 'mode': 'PAPER',
                    'live_eligible': 'true' if cfg['live'] else 'false',
                    'ts': int(time.time()),
                }, args.dry_run)

    put_item(table, 'RUN#live_multi', today, {'ts': int(time.time()), 'counts': counts}, args.dry_run)
    flush_writes(table)

    for strat in STRATEGIES:
        cands = sorted(candidates[strat], key=lambda x: x[1])  # lowest RSI2 first
        print(f'\n{strat}: {counts[strat]} signals')
        for sym, r2, drop, atr in cands[:15]:
            print(f'    {sym:6s} rsi2={r2:.2f} drop2={drop:+.2f} atr={atr:.2f}')
    print(f'\nmulti-strategy scan done [{today}]: ' +
          ', '.join(f'{s}={counts[s]}' for s in STRATEGIES))


if __name__ == '__main__':
    main()
