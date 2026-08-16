#!/usr/bin/env python3
"""Diagnose the NQ maxDD divergence between no_filter and sma200 RSI2 variants."""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_edges import load_yfinance, rsi, trade_record, FEE_BPS
from rsi2_sma200_compare import run_rsi2

def diagnose(tk, mult, tick, filt, label):
    df = load_yfinance(tk)
    trades, eq = run_rsi2(df, mult=mult, tick=tick, slip=3, sma200_filter=filt)
    dd = eq - eq.cummax()
    trough_i = int(np.argmin(dd.values))
    peak_i = int(np.argmax(eq.values[:trough_i + 1]))
    print(f"\n=== {tk} [{label}] ===  n_trades={len(trades)}")
    print(f"  maxDD ${dd.min():,.0f}  peak {eq.iloc[peak_i]:,.0f} @ {eq.index[peak_i].date()}  "
          f"-> trough {eq.iloc[trough_i]:,.0f} @ {eq.index[trough_i].date()}")
    # trades overlapping the drawdown window (entry in [peak, trough])
    win_trades = [t for t in trades if peak_i <= t['entry_i'] <= trough_i]
    pnls = sorted([t['pnl'] for t in win_trades])
    print(f"  trades entering inside DD window: {len(win_trades)}, "
          f"net ${sum(t['pnl'] for t in win_trades):,.0f}")
    print(f"  worst 5 trades (all periods):")
    for t in sorted(trades, key=lambda t: t['pnl'])[:5]:
        print(f"    entry {df.index[t['entry_i']].date()} pnl ${t['pnl']:,.0f} "
              f"days={t['days']} reason={t['reason']}")
    # RSI2<10 fire count vs filtered-pass count (why trades differ)
    c = df['Close']; r2 = rsi(c, 2); sma200 = c.rolling(200).mean()
    raw = (r2 < 10).sum()
    above = ((r2 < 10) & (c > sma200)).sum()
    below = ((r2 < 10) & (c <= sma200)).sum()
    print(f"  RSI2<10 fire bars: {raw}  (above 200SMA: {above}, below: {below})")

for tk, (name, mult, tick) in {'ES=F': ('ES', 50.0, 0.25), 'NQ=F': ('NQ', 20.0, 0.25)}.items():
    diagnose(tk, mult, tick, False, 'no_filter')
    diagnose(tk, mult, tick, True, 'sma200')
