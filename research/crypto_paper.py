#!/usr/bin/env python3
"""Crypto paper-signal lane — logs signals for SURVIVORS only. INERT until a
strategy clears the promotion bar in research/CRYPTO_SWEEP_HIST.md.

Owner distrusts crypto; crypto is RESEARCH-GRADE, NOT live, and has NO broker on
this VPS. This lane therefore:
  - computes signals from S3 crypto-hist/ daily candles (Binance.US klines),
  - logs them to DynamoDB under SIGNAL#CRYPTO_<sym>_<strat> (paper audit trail),
  - places NO orders and manages NO positions (there is nothing to trade against),
  - is NOT scheduled (no cron) until the owner re-engages crypto.

SURVIVORS below is the promote list from CRYPTO_SWEEP_HIST.md. As of the first sweep
(2026-08-15) it is EMPTY (0 promotes) — running this file exits 0 with a note and
writes nothing, by design.
"""
import os
import sys
import time
import datetime as dt

import numpy as np
import boto3
from dotenv import load_dotenv

REPO = os.environ.get('TRADING_REPO', os.path.expanduser('~/trading-system'))
sys.path.insert(0, os.path.join(REPO, 'research'))
load_dotenv(os.path.join(REPO, '.env'))
load_dotenv()

from crypto_sweep import (load_bars, wilder_atr, rsi, donchian_hi_lo,
                          strat_momentum_long, strat_meanrev,
                          DON_N, ATR_N, RSI2_LO, RSI2_HI)  # noqa: E402

DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

# Promotion survivors from CRYPTO_SWEEP_HIST.md. Empty = nothing cleared the bar.
# Add '<SYM>': '<strategy>' entries ONLY after a PROMOTE verdict.
SURVIVORS = {}   # e.g. {'SOLUSDT': 'momentum_long'} once a survivor exists

STRATEGIES = {
    'momentum_long': strat_momentum_long,
    'meanrev_rsi2_long': strat_meanrev,
}


def last_bar_signal(bars, strat):
    """Run `strat` on the latest bar -> ('LONG'|'SHORT'|'NONE', reason)."""
    if len(bars) < DON_N + 2:
        return 'NONE', 'insufficient history'
    c = np.array([b['close'] for b in bars], float)
    h = np.array([b['high'] for b in bars], float)
    l = np.array([b['low'] for b in bars], float)
    detail = {'close': c, 'atr': wilder_atr(h, l, c), 'rsi2': rsi(c, 2)}
    detail['don_hi'], detail['don_lo'] = donchian_hi_lo(h, l)
    i = len(bars) - 1
    sig, _ = strat(detail, i, 0, 0)
    if sig == 1:
        return 'LONG', f"signal at close {c[i]:.2f}"
    if sig == -1:
        return 'SHORT', f"signal at close {c[i]:.2f}"
    return 'NONE', f"no signal (close {c[i]:.2f})"


def main():
    if not SURVIVORS:
        print('[crypto_paper] no promotion survivors (CRYPTO_SWEEP_HIST.md) — inert, '
              'writing nothing. Crypto stays research-grade until the owner re-engages.')
        return

    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()
    for sym, sname in SURVIVORS.items():
        bars = load_bars(sym)
        if not bars:
            print(f'[{sym}] no crypto-hist bars — skip')
            continue
        sig, reason = last_bar_signal(bars, STRATEGIES[sname])
        table.put_item(Item={
            'pk': f'SIGNAL#CRYPTO_{sym}_{sname}', 'sk': today,
            'signal': sig, 'symbol': sym, 'strategy': sname,
            'reason': reason, 'paper': True, 'ts': int(time.time()),
        })
        print(f'[{sym}] {sname}: {sig} ({reason})')


if __name__ == '__main__':
    main()
