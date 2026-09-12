#!/usr/bin/env python3
"""Crypto short-term reversal (buy recent losers) — is it real or liquidity/survivorship trap?

The full-universe momentum test showed cross-sectional momentum INVERTS (buy winners
loses -67bp/d, t=-5.5). That implies "buy losers" is +67bp/d. But that's likely the
illiquid/dead-coin bounce artifact. Test whether the reversal survives on LIQUID coins
only (top-40 by 24h volume) with honest costs.
"""
import sys
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, '/home/ubuntu/trading-system/research/atomics')
from crypto_momentum_full_universe import load_daily_panel, stats, ONE_SIDE_BP


def liquid_symbols(n=40):
    r = requests.get('https://api.binance.us/api/v3/ticker/24hr', timeout=30)
    r.raise_for_status()
    rows = [x for x in r.json() if x.get('symbol', '').endswith('USDT')]
    rows.sort(key=lambda x: float(x.get('quoteVolume', 0) or 0), reverse=True)
    return set(x['symbol'] for x in rows[:n])


def run(p, label):
    ret = p.pct_change()
    print(f'\n=== {label} ({p.shape[1]} symbols) ===')
    stats(ret.mean(axis=1), 'B&H equal-weight (gross)')
    for lb in [7, 14, 28]:
        mom = p.pct_change(lb)
        rank = mom.rank(axis=1, ascending=True, method='first')  # 1 = biggest loser
        for K in [5, 10]:
            hold = (rank <= K).astype(float)
            w = hold.div(hold.sum(axis=1), axis=0).shift(1)
            strat = (w * ret).sum(axis=1)
            turn = w.diff().abs().sum(axis=1)
            net = strat - turn * ONE_SIDE_BP / 1e4
            stats(net, f'XS-REVERSAL {lb}d bottom{K} long (net)')


def main():
    px = load_daily_panel()
    liq = liquid_symbols(40)
    liq_px = px[[c for c in px.columns if c in liq]]
    run(px, 'ALL symbols')
    run(liq_px, f'LIQUID top-40')


if __name__ == '__main__':
    main()
