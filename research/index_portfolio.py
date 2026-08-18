"""Combined index sleeve (RSI2 + Donchian) — the portfolio the live bot runs.

The live index bot (bot/live.py) runs BOTH MES Donchian and MES RSI2. Each
robustness pass showed them nearly uncorrelated (daily P&L corr ~0) and, more
importantly, complementary across regimes (RSI2 wins 2008 where Donchian loses;
Donchian wins 2018 where RSI2 loses). This computes the COMBINED 1+1-contract
portfolio P&L (equal-weight, daily P&L attributed to exit day) and compares its
drawdown / per-year profile against each sleeve alone — the drawdown-first
question the owner cares about.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from validate_edges import run_donchian, run_rsi2_long, SPECS, FEE_BPS  # noqa: E402
from rsi2_robustness import maxdd_from_pnls, bootstrap_maxdd  # noqa: E402

LONG_START = '2000-01-01'


def daily_pnl(trades, df):
    s = pd.Series(0.0, index=df.index)
    for t in trades:
        s.iloc[t['exit_i']] += t['pnl']
    return s


def per_year(s, idx):
    out = {}
    for i, v in s.items():
        y = i.year  # s is indexed by DatetimeIndex; i is the timestamp
        b = out.setdefault(y, {'wins': 0.0, 'losses': 0.0, 'n': 0})
        if v > 0:
            b['wins'] += v
        elif v < 0:
            b['losses'] += abs(v)
    for y in sorted(out):
        b = out[y]
        b['pf'] = round(b['wins'] / b['losses'], 2) if b['losses'] > 0 else float('inf')
        b['net'] = round(b['wins'] - b['losses'], 0)
    return out


def summary(trades_or_series, label, idx):
    if isinstance(trades_or_series, pd.Series):
        p = trades_or_series.values
    else:
        p = np.array([t['pnl'] for t in trades_or_series], dtype=float)
    wins, losses = p[p > 0].sum(), abs(p[p <= 0].sum())
    pf = wins / losses if losses > 0 else float('inf')
    return {'label': label, 'n': int((p != 0).sum()), 'pf': round(pf, 2),
            'net': round(p.sum(), 0), 'maxdd': round(maxdd_from_pnls(p), 0),
            'winrate': round(float((p > 0).mean()), 3)}


def main():
    out = {}
    for sym in ['ES', 'NQ', 'YM']:
        tk = f'{sym}=F'
        mult, tick = SPECS[tk][1], SPECS[tk][2]
        import yfinance as yf
        df = yf.download(tk, start=LONG_START, interval='1d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])[df.index >= LONG_START]

        r2, _ = run_rsi2_long(df, mult=mult, tick=tick, slip=1)
        don, _ = run_donchian(df, mult=mult, tick=tick, slip=1)
        s_r2 = daily_pnl(r2, df)
        s_don = daily_pnl(don, df)
        s_comb = s_r2 + s_don

        idx = list(df.index)
        r = {
            'rsi2': summary(r2, 'RSI2', idx),
            'donchian': summary(don, 'Donchian', idx),
            'combined': summary(s_comb, 'Combined', idx),
            'combined_bootstrap_iid': bootstrap_maxdd(
                [{'pnl': v} for v in s_comb.values if v != 0], block=None),
            'combined_per_year': per_year(s_comb, idx),
            'rsi2_per_year': per_year(s_r2, idx),
            'donchian_per_year': per_year(s_don, idx),
            'corr': round(float(s_r2.corr(s_don)), 3),
        }
        out[sym] = r
        print(f'[{sym}] RSI2 PF {r["rsi2"]["pf"]} dd {r["rsi2"]["maxdd"]:,.0f} | '
              f'Donchian PF {r["donchian"]["pf"]} dd {r["donchian"]["maxdd"]:,.0f} | '
              f'COMBINED PF {r["combined"]["pf"]} dd {r["combined"]["maxdd"]:,.0f} | '
              f'corr {r["corr"]}')

    with open(os.path.join(HERE, 'index_portfolio_results.json'), 'w') as f:
        json.dump(out, f, indent=1, default=str)
    print('\nwrote research/index_portfolio_results.json')


if __name__ == '__main__':
    main()
