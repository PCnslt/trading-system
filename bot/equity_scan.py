"""Equity swing re-test at REALISTIC costs (corrects the earlier 0.5% error).

Universe: SPY QQQ TQQQ SQQQ + 15 liquid single names.
Strategies: Donchian/ATR breakout, RSI(2) MR, MA 5/20 cross, Bollinger reversal
(signal generators imported verbatim from strategy_scan.py).

Costs tested: 0.02% / 0.05% / 0.10% round-trip (commission-free + spread
~0.01-0.05%). Applied per completed trade; equity curve via (cost/2)*turnover.

Output: per (strategy, cost) pooled PF across ALL tickers (full period) and
pooled out-of-sample PF (walk-forward 60/40 test half). A strategy is only
"alive" if pooled OOS PF > 1.1 at the realistic cost level.
"""
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

from strategy_scan import sig_donchian, sig_rsi2, sig_ma_cross, sig_bollinger

COSTS = [0.0002, 0.0005, 0.0010]      # round-trip: 0.02%, 0.05%, 0.10%
TICKERS = ['SPY', 'QQQ', 'TQQQ', 'SQQQ',
           'NVDA', 'AAPL', 'MSFT', 'TSLA', 'AMD', 'META', 'GOOGL', 'AMZN',
           'NFLX', 'COST', 'AVGO', 'JPM', 'XOM', 'PLTR', 'CRM']
START = '2015-01-01'
STRATEGIES = [
    ('Donchian/ATR', sig_donchian),
    ('RSI(2)', sig_rsi2),
    ('MA 5/20', sig_ma_cross),
    ('Bollinger', sig_bollinger),
]

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, 'equity_scan_results.json')


def load_all(tickers):
    raw = yf.download(tickers, start=START, interval='1d', progress=False,
                      auto_adjust=True, group_by='ticker')
    out = {}
    for tk in tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                df = raw[tk]
            else:
                df = raw
            df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
            out[tk] = df
        except Exception:
            out[tk] = pd.DataFrame()
    return out


def extract_trades(pos, close, cost):
    trades = []
    p, entry_px, entry_i = 0, np.nan, None
    for i in range(len(pos)):
        pi = int(pos.iloc[i])
        ci = close.iloc[i]
        if p == 0 and pi != 0:
            p, entry_px, entry_i = pi, ci, i
        elif p != 0 and pi != p:
            trades.append({'ret': (ci / entry_px - 1) * p - cost, 'days': i - entry_i, 'dir': p})
            if pi == 0:
                p = 0
            else:
                p, entry_px, entry_i = pi, ci, i
    if p != 0:
        trades.append({'ret': (close.iloc[-1] / entry_px - 1) * p - cost,
                       'days': len(pos) - 1 - entry_i, 'dir': p})
    return trades


def pf_from_trades(trades):
    if not trades:
        return 0.0
    rets = np.array([t['ret'] for t in trades])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    if losses.size == 0:
        return float('inf') if wins.size else 0.0
    if losses.sum() == 0:
        return float('inf')
    return wins.sum() / abs(losses.sum())


def main():
    print("Loading data for", len(TICKERS), "tickers...")
    data = load_all(TICKERS)
    loaded = {tk: df for tk, df in data.items() if len(df) > 200}
    print(f"Loaded {len(loaded)}/{len(TICKERS)} tickers with >200 bars\n")
    if len(loaded) < 10:
        print("WARNING: too few tickers loaded — aborting (data fetch issue)")
        return

    results = {name: {c: {} for c in COSTS} for name, _ in STRATEGIES}

    # per-ticker 60/40 split once
    splits = {}
    for tk, df in loaded.items():
        s = int(len(df) * 0.6)
        splits[tk] = (df.iloc[:s], df.iloc[s:])

    header = (f"{'Strategy':<14} {'Cost':>7} {'Trades':>7} {'Win%':>6} {'PF':>7} "
              f"{'OOS Trades':>11} {'OOS PF':>8}")
    print(header)
    print('-' * len(header))

    payload = {'costs': COSTS, 'tickers': sorted(loaded.keys()), 'strategies': {}}

    for name, fn in STRATEGIES:
        for cost in COSTS:
            all_trades, oos_trades = [], []
            for tk, df in loaded.items():
                tr, te = splits[tk]
                all_trades.extend(extract_trades(fn(df), df['Close'], cost))
                oos_trades.extend(extract_trades(fn(te), te['Close'], cost))
            pf = pf_from_trades(all_trades)
            oos_pf = pf_from_trades(oos_trades)
            wins = sum(1 for t in all_trades if t['ret'] > 0)
            winrate = 100.0 * wins / len(all_trades) if all_trades else 0.0
            results[name][cost] = {'pf': pf, 'oos_pf': oos_pf,
                                   'trades': len(all_trades), 'oos_trades': len(oos_trades),
                                   'winrate': winrate}
            pf_s = ' inf' if pf == float('inf') else f"{pf:>7.2f}"
            oos_s = ' inf' if oos_pf == float('inf') else f"{oos_pf:>8.2f}"
            print(f"{name:<14} {cost*100:>5.2f}% {len(all_trades):>7} {winrate:>5.0f} "
                  f"{pf_s} {len(oos_trades):>11} {oos_s}")
        print()

    payload['strategies'] = {name: {str(c): results[name][c] for c in COSTS}
                             for name, _ in STRATEGIES}
    with open(RESULTS_FILE, 'w') as f:
        import json
        json.dump(payload, f, indent=2, default=float)
    print(f"Saved results -> {RESULTS_FILE}")

    # verdict
    print("=== VERDICT (pooled OOS PF > 1.1 = alive) ===")
    alive = False
    for name, _ in STRATEGIES:
        for cost in COSTS:
            if results[name][cost]['oos_pf'] > 1.1 and results[name][cost]['oos_trades'] >= 30:
                print(f"  ALIVE: {name} @ {cost*100:.2f}%  OOS PF {results[name][cost]['oos_pf']:.2f}")
                alive = True
    if not alive:
        print("  NONE. Equity swing is genuinely dead at realistic costs (OOS PF <= 1.1 everywhere).")


if __name__ == '__main__':
    main()
