#!/usr/bin/env python3
"""Adaptive-stop backtest — fixed vs chandelier vs adaptive, drawdown-first.

Replays the 4 daily/swing strategies (Donchian, RSI2, TSMOM, crypto MOM20) across
the 3 stop modes, using the shared bot/adaptive_stop.py engine for 'adaptive'.

Honest fills (same convention as trailing_stop_backtest.py): entry at signal-close
+ adverse slip; GTC stop gap-aware (open<stop -> open, low<=stop -> stop) + slip;
close-based exits + slip; fee in bps round-trip notional.

Deliverable: PF / maxDD / worst-trade / win% / net / n per (instrument, strategy,
stop_mode), so the decision rule is drawdown-first (maxDD -> worst -> win%).
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.adaptive_stop import AdaptiveStop, compute_features, adaptive_multiplier  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
START = '2010-01-01'

# instrument -> (name, multiplier/point-value, tick, fee_bps, slip_ticks)
INST = {
    'ES=F': ('ES', 50.0, 0.25, 0.13, 2),
    'NQ=F': ('NQ', 20.0, 0.25, 0.13, 2),
    'GC=F': ('GC', 100.0, 0.1, 0.13, 2),
    'BTC-USD': ('BTC', 1.0, 0.01, 10.0, 0),
    'ETH-USD': ('ETH', 1.0, 0.01, 10.0, 0),
}

LOOKBACK = 20
MAX_HOLD = 5
RSI2_LO, RSI2_HI = 10.0, 70.0
TSMOM_LOOK = 252


def rsi(close, n=2):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def stats(trades):
    if not trades:
        return None
    p = np.array(trades)
    wins = p[p > 0]
    losses = p[p <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float('inf')
    eq = np.cumsum(p)
    dd = eq - np.maximum.accumulate(eq)
    return {'n': len(p), 'pf': round(float(pf), 2),
            'win%': round(100 * len(wins) / len(p)),
            'maxDD': round(float(dd.min()), 0), 'worst': round(float(p.min()), 0),
            'net': round(float(p.sum()), 0)}


def load(sym):
    start = '2018-01-01' if sym.endswith('-USD') else START
    return yf.download(sym, start=start, auto_adjust=(sym.endswith('-USD')), progress=False)


def signals(df, strat):
    h = df['High'].squeeze(); l = df['Low'].squeeze(); c = df['Close'].squeeze()
    if strat == 'DONCHIAN' or strat == 'MOM20':
        enter = (c > h.rolling(LOOKBACK).max().shift(1)).astype(int)
        exit_sig = (c < l.rolling(LOOKBACK).min().shift(1)).astype(int)
    elif strat == 'RSI2':
        r = rsi(c)
        enter = (r < RSI2_LO).astype(int)
        exit_sig = (r > RSI2_HI).astype(int)
    elif strat == 'TSMOM':
        mom = c / c.shift(TSMOM_LOOK) - 1.0
        enter = (mom > 0).astype(int)
        exit_sig = (mom <= 0).astype(int)
    return enter, exit_sig


def run(df, strat, stop_mode, mult, ptval, tick, fee_bps, slip):
    h = df['High'].squeeze(); l = df['Low'].squeeze()
    c = df['Close'].squeeze(); o = df['Open'].squeeze()
    atr, atr_med, er = compute_features(df)
    enter, exit_sig = signals(df, strat)
    edge = 'trend' if strat in ('DONCHIAN', 'MOM20') else ('meanrev' if strat == 'RSI2' else 'momentum')

    n = len(df)
    pos, entry_px, peak, held = 0, 0.0, 0.0, 0
    eng = AdaptiveStop(edge, base_mult=mult)
    trades = []
    slip_usd = slip * tick
    for i in range(1, n):
        if pos == 0:
            if enter.iloc[i] == 1 and enter.iloc[i - 1] == 0:  # signal FLIP only (no churn)
                entry_px = c.iloc[i] + slip_usd
                pos = 1; peak = h.iloc[i]; held = 0
                eng.reset(); eng.peak = peak
        else:
            held += 1
            peak = max(peak, h.iloc[i - 1])
            a = float(atr.iloc[i]); am = float(atr_med.iloc[i]); e = float(er.iloc[i])
            if stop_mode == 'adaptive':
                stop, _sz = eng.update(entry_px, float(c.iloc[i - 1]), float(h.iloc[i - 1]), a, am, e)
            elif stop_mode == 'chandelier':
                stop = peak - mult * a
            else:  # fixed
                stop = entry_px - mult * a
            # gap-aware intraday stop (no lookahead: uses THIS bar's open/low vs stop)
            exit_px = None
            ob = float(o.iloc[i]); lo = float(l.iloc[i])
            if ob <= stop:
                exit_px = ob - slip_usd
            elif lo <= stop:
                exit_px = stop - slip_usd
            if exit_px is not None:
                pnl = (exit_px - entry_px) * ptval - fee_bps / 1e4 * (entry_px + exit_px) * ptval
                trades.append(pnl); pos = 0; continue
            # signal / time exit at close
            if exit_sig.iloc[i] == 1 or (strat != 'TSMOM' and held >= MAX_HOLD):
                exit_px = float(c.iloc[i]) - slip_usd
                pnl = (exit_px - entry_px) * ptval - fee_bps / 1e4 * (entry_px + exit_px) * ptval
                trades.append(pnl); pos = 0
    return trades


def main():
    results = {}
    for sym, (name, ptval, tick, fee_bps, slip) in INST.items():
        df = load(sym)
        if df is None or len(df) < 300:
            print(f'skip {sym}: insufficient data'); continue
        strats = ['DONCHIAN', 'RSI2'] if sym in ('ES=F', 'NQ=F') else \
                 (['TSMOM'] if sym == 'GC=F' else ['MOM20'])
        results[sym] = {}
        for s in strats:
            results[sym][s] = {}
            for mode in ['fixed', 'chandelier', 'adaptive']:
                tr = run(df, s, mode, mult=3.0, ptval=ptval, tick=tick, fee_bps=fee_bps, slip=slip)
                st = stats(tr)
                results[sym][s][mode] = st
                print(f'{sym:9} {s:9} {mode:11} -> {st}')
    out = os.path.join(HERE, 'adaptive_stop_results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=float)
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
