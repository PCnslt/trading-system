"""Donchian (index LONG) robustness pass + RSI2-vs-Donchian redundancy check.

Same battery as rsi2_robustness.py but for the Donchian 20-day breakout
(LONG-only, 2xATR GTC stop, 5-day max-hold, Donchian-low breakout exit) — the
other half of bot/live.py. Uses the HONEST intraday gap-aware stop model (the
close-based model overstates: 1.92 vs 1.56 PF). Also computes the cross-edge
redundancy between RSI2 and Donchian on the same ES data (the review/skill
"redundancy, not a new edge" check).
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from validate_edges import (  # noqa: E402
    run_donchian, run_rsi2_long, wilder_atr, SPECS, FEE_BPS,
)
from rsi2_robustness import (  # noqa: E402
    pnl_distribution, maxdd_from_pnls, bootstrap_maxdd, per_year_pf,
    worst_streak_and_dd, oos_slice,
)

LONG_START = '2000-01-01'
SLIP_TICKS = [0, 1, 2, 3, 4, 5]
STOP_ATR_GRID = [1.5, 2.0, 2.5, 3.0, 4.0]
LOOKBACK_GRID = [15, 20, 25, 30]
N_BOOT = 5000


def run_donchian_late(df, lookback=20, stop_atr=2.0, max_hold=5, mult=50.0,
                      tick=0.25, fee_bps=FEE_BPS, slip=0, entry_lag=0):
    """run_donchian variant with entry fill lag (entry_lag bars late)."""
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    don_hi = h.rolling(lookback).max().shift(1)
    don_lo = l.rolling(lookback).min().shift(1)
    warmup = lookback + 2
    trades = []
    pos, entry_px, entry_i, stop = 0, 0.0, 0, 0.0
    n = len(df)
    for i in range(warmup, n):
        oi, ci, bar_l = o.iloc[i], c.iloc[i], l.iloc[i]
        if pos == 0:
            if not np.isnan(don_hi.iloc[i]) and ci > don_hi.iloc[i]:
                ei = i + entry_lag
                if ei >= n:
                    break
                entry_px = c.iloc[ei] + slip * tick
                entry_i = ei
                stop = entry_px - stop_atr * atr.iloc[ei]
                pos = 1
        else:
            held = i - entry_i
            mae = (l.iloc[entry_i:i + 1].min() - entry_px)
            mfe = (h.iloc[entry_i:i + 1].max() - entry_px)
            exit_px = None
            if oi < stop:                       # gap through stop
                exit_px = oi - slip * tick
            elif bar_l <= stop:
                exit_px = stop - slip * tick
            if exit_px is None and held >= max_hold:
                exit_px = ci - slip * tick
            if exit_px is None and not np.isnan(don_lo.iloc[i]) and ci < don_lo.iloc[i]:
                exit_px = ci - slip * tick
            if exit_px is not None:
                fee = fee_bps * entry_px * mult
                pnl = (exit_px - entry_px) * mult - fee
                trades.append({'pnl': pnl, 'entry_i': int(entry_i), 'exit_i': int(i),
                               'mae': mae, 'mfe': mfe})
                pos = 0
    return trades


def daily_pnl_series(trades, df):
    """Realized P&L attributed to the EXIT day (zero-filled elsewhere)."""
    idx = list(df.index)
    s = pd.Series(0.0, index=df.index)
    for t in trades:
        s.iloc[t['exit_i']] += t['pnl']
    return s


def cross_edge_redundancy(rs2_trades, don_trades, df):
    """(signal_overlap, daily_pnl_corr) between two trade streams on the same df."""
    idx = list(df.index)
    # position mask per day
    r2_pos = np.zeros(len(df), dtype=bool)
    don_pos = np.zeros(len(df), dtype=bool)
    for t in rs2_trades:
        r2_pos[t['entry_i']:t['exit_i'] + 1] = True
    for t in don_trades:
        don_pos[t['entry_i']:t['exit_i'] + 1] = True
    both_in = (r2_pos & don_pos).sum()
    both_flat = ((~r2_pos) & (~don_pos)).sum()
    overlap = float((both_in + both_flat) / len(df))
    # daily P&L correlation (exit-day attributed)
    r2s = daily_pnl_series(rs2_trades, df)
    dons = daily_pnl_series(don_trades, df)
    corr = float(r2s.corr(dons)) if r2s.std() > 0 and dons.std() > 0 else 0.0
    return {'signal_overlap': round(overlap, 4),
            'daily_pnl_corr': round(corr, 4),
            'r2_days_in': int(r2_pos.sum()),
            'don_days_in': int(don_pos.sum()),
            'days': len(df)}


def main():
    out = {}
    for sym in ['ES', 'NQ', 'YM']:
        tk = f'{sym}=F'
        mult, tick = SPECS[tk][1], SPECS[tk][2]
        try:
            import yfinance as yf
            df = yf.download(tk, start=LONG_START, interval='1d',
                             progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
        except Exception as e:
            out[sym] = {'error': str(e)}
            continue
        if df is None or df.empty:
            out[sym] = {'error': 'no data'}
            continue
        df = df[df.index >= LONG_START]
        r = {'rows': len(df), 'start': str(df.index[0].date()),
             'end': str(df.index[-1].date()), 'mult': mult, 'tick': tick}

        # baseline (intraday stop, 1 tick/side)
        base_trades, base_eq = run_donchian(df, mult=mult, tick=tick, slip=1)
        r['baseline_n'] = len(base_trades)
        r['return_distribution'] = pnl_distribution(base_trades)
        r['bootstrap_dd_iid'] = bootstrap_maxdd(base_trades, block=None)
        r['bootstrap_dd_block10'] = bootstrap_maxdd(base_trades, block=10)

        # slippage stress 0-5 ticks
        r['slippage'] = {}
        for s in SLIP_TICKS:
            tr, eq = run_donchian(df, mult=mult, tick=tick, slip=s)
            p = np.array([t['pnl'] for t in tr], dtype=float)
            wins, losses = p[p > 0].sum(), abs(p[p <= 0].sum())
            pf = wins / losses if losses > 0 else float('inf')
            r['slippage'][f'{s}tick'] = {'pf': round(pf, 3), 'net': round(p.sum(), 0),
                                         'maxdd': round(maxdd_from_pnls(p), 0), 'n': len(tr)}

        # stop-ATR sensitivity
        r['stop_atr'] = {}
        for sa in STOP_ATR_GRID:
            tr, eq = run_donchian(df, stop_atr=sa, mult=mult, tick=tick, slip=1)
            p = np.array([t['pnl'] for t in tr], dtype=float)
            wins, losses = p[p > 0].sum(), abs(p[p <= 0].sum())
            pf = wins / losses if losses > 0 else float('inf')
            r['stop_atr'][f'{sa}'] = {'pf': round(pf, 3), 'net': round(p.sum(), 0),
                                      'maxdd': round(maxdd_from_pnls(p), 0), 'n': len(tr),
                                      'winrate': round(float((p > 0).mean()), 3)}

        # lookback sensitivity
        r['lookback'] = {}
        for lb in LOOKBACK_GRID:
            tr, eq = run_donchian(df, lookback=lb, mult=mult, tick=tick, slip=1)
            p = np.array([t['pnl'] for t in tr], dtype=float)
            wins, losses = p[p > 0].sum(), abs(p[p <= 0].sum())
            pf = wins / losses if losses > 0 else float('inf')
            r['lookback'][f'{lb}'] = {'pf': round(pf, 3), 'net': round(p.sum(), 0),
                                      'maxdd': round(maxdd_from_pnls(p), 0), 'n': len(tr)}

        # entry timing (1/2 bars late)
        r['entry_lag'] = {}
        for lag in [1, 2]:
            tr = run_donchian_late(df, mult=mult, tick=tick, slip=1, entry_lag=lag)
            p = np.array([t['pnl'] for t in tr], dtype=float)
            wins, losses = p[p > 0].sum(), abs(p[p <= 0].sum())
            pf = wins / losses if losses > 0 else float('inf')
            r['entry_lag'][f'{lag}bar'] = {'pf': round(pf, 3), 'net': round(p.sum(), 0),
                                           'maxdd': round(maxdd_from_pnls(p), 0), 'n': len(tr)}

        # OOS40 (last 40% by entry date)
        ins, oos = oos_slice(base_trades, frac=0.4)
        r['oos40'] = {'n': len(oos), 'worst_streak': worst_streak_and_dd(oos)[0],
                      'maxdd': round(worst_streak_and_dd(oos)[1], 0),
                      'pf': round((sum(t['pnl'] for t in oos if t['pnl'] > 0) /
                                   abs(sum(t['pnl'] for t in oos if t['pnl'] <= 0))), 3)
                      if any(t['pnl'] <= 0 for t in oos) else float('inf')}
        r['insample_60'] = {'n': len(ins), 'worst_streak': worst_streak_and_dd(ins)[0],
                            'maxdd': round(worst_streak_and_dd(ins)[1], 0)}
        r['per_year'] = per_year_pf(base_trades, df)

        mae = np.array([t['mae'] for t in base_trades], dtype=float)
        mfe = np.array([t['mfe'] for t in base_trades], dtype=float)
        r['excursions'] = {'mae_p5': float(np.percentile(mae, 5)),
                           'mae_p50': float(np.percentile(mae, 50)),
                           'mae_p95': float(np.percentile(mae, 95)),
                           'mae_worst': float(mae.min()),
                           'mfe_p95': float(np.percentile(mfe, 95)),
                           'mfe_worst': float(mfe.max())}

        # RSI2 vs Donchian redundancy (same ES data)
        rs2_trades, _ = run_rsi2_long(df, mult=mult, tick=tick, slip=1)
        r['redundancy_vs_rsi2'] = cross_edge_redundancy(rs2_trades, base_trades, df)

        out[sym] = r
        print(f"[{sym}] {len(df)} bars {r['start']}→{r['end']} · "
              f"n={len(base_trades)} · OOS40 n={len(oos)}")

    with open(os.path.join(HERE, 'donchian_robustness_results.json'), 'w') as f:
        json.dump(out, f, indent=1, default=str)
    print('\nwrote research/donchian_robustness_results.json')


if __name__ == '__main__':
    main()
