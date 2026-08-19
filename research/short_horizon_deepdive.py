#!/usr/bin/env python3
"""Deep-dive on the promising candidate: N-day short-term reversal (LONG-only).

Checks the two remaining gates from trading-backtest-validation:
  1. Walk-forward OOS (40/20/40) + rolling folds — does it survive out-of-sample?
  2. Redundancy vs the LIVE RSI2 edge (daily-P&L correlation + signal overlap).
Also per-year PF to expose regime fragility (grind vs crash).

Donchian short-lookback is already a clear NO-GO (breakeven long-only, losing
long-short) — not re-tested here.
"""
import numpy as np
import pandas as pd

from short_horizon_edges_study import (
    fetch_daily, wilder_atr, rsi, run_trades, metrics, INSTR,
)

INSTRUMENTS = ['ES=F', 'NQ=F', 'YM=F']


def reversal_long(N, thresh_atr=1.0, stop_atr=2.0, max_hold=3):
    """Factory returning (entry, stop, exit) closures for reversal LONG-only."""
    def make(df):
        h, l, c = df['High'], df['Low'], df['Close']
        atr = wilder_atr(h, l, c, 14)
        retN = c.pct_change(N)
        atr_a, ret_a, cl_a = atr.values, retN.values, c.values

        def entry(i):
            if np.isnan(ret_a[i]) or np.isnan(atr_a[i]) or atr_a[i] <= 0:
                return 0
            k = thresh_atr * atr_a[i] / cl_a[i]
            return 1 if ret_a[i] < -k else 0

        def stop(e, side, a):
            return e - stop_atr * a

        def exit_fn(i, side, entry, stop, held):
            return (cl_a[i] > entry), 'REVERT'

        return run_trades(df, entry, stop, exit_fn, max_hold)
    return make


def rsi2_long(df, lo=10.0, hi=70.0, stop_atr=2.0, max_hold=5):
    """The LIVE RSI2 dip-buy (close>SMA200, RSI2<10, 2xATR stop, exit RSI2>70/5d)."""
    h, l, c = df['High'], df['Low'], df['Close']
    atr = wilder_atr(h, l, c, 14)
    r2 = rsi(c, 2)
    sma200 = c.rolling(200).mean()
    atr_a, r2_a, sma_a, cl_a = atr.values, r2.values, sma200.values, c.values

    def entry(i):
        return (r2_a[i] < lo and not np.isnan(sma_a[i]) and cl_a[i] > sma_a[i])

    def stop(e, side, a):
        return e - stop_atr * a

    def exit_fn(i, side, entry, stop, held):
        return (r2_a[i] > hi), 'RSI2>70'

    return run_trades(df, entry, stop, exit_fn, max_hold)


def per_year_pf(trades, pv, slip, tick):
    """PF per calendar year (entry-year bucketed)."""
    rows = {}
    for t in trades:
        y = t['entry_date'].year
        rows.setdefault(y, []).append(t)
    out = []
    for y in sorted(rows):
        m = metrics(rows[y], pv, slip, tick)
        out.append((y, m['n'] if m else 0, m['pf'] if m else float('nan'),
                    m['net'] if m else 0.0, m['maxdd_abs'] if m else 0.0))
    return out


def daily_pnl_series(trades, pv, slip, tick, fee_bps=1.3e-4):
    """Daily dollar P&L attributed to exit date, zero-filled full range."""
    daily = {}
    for t in trades:
        gross = t['pnl'] * pv
        slip_d = 2 * slip * tick * pv
        fee = fee_bps * t['entry_px'] * pv
        d = t['exit_date']
        daily[d] = daily.get(d, 0.0) + (gross - slip_d - fee)
    if not daily:
        return pd.Series(dtype=float)
    idx = pd.date_range(min(daily), max(daily), freq='D')
    return pd.Series([daily.get(d, 0.0) for d in idx], index=idx)


def walk_forward(trades, pv, slip, tick):
    """40/20/40 split by ENTRY date -> PF per segment."""
    if not trades:
        return None
    ed = [t['entry_date'] for t in trades]
    lo, hi = min(ed), max(ed)
    span = (hi - lo).total_seconds()
    t40 = lo + pd.Timedelta(seconds=span * 0.40)
    v60 = lo + pd.Timedelta(seconds=span * 0.60)
    seg = {'train': [], 'validate': [], 'oos': []}
    for t in trades:
        if t['entry_date'] <= t40:
            seg['train'].append(t)
        elif t['entry_date'] <= v60:
            seg['validate'].append(t)
        else:
            seg['oos'].append(t)
    out = {}
    for k, v in seg.items():
        m = metrics(v, pv, slip, tick)
        out[k] = (m['n'] if m else 0, m['pf'] if m else float('nan'),
                  m['win_rate'] if m else float('nan'),
                  m['maxdd_abs'] if m else 0.0)
    return out


def main():
    print('=' * 95)
    print('DEEP-DIVE — N-day reversal LONG-only: walk-forward OOS + redundancy vs RSI2')
    print('=' * 95)
    for tkr in INSTRUMENTS:
        pv, tick = INSTR[tkr]['pv'], INSTR[tkr]['tick']
        df = fetch_daily(tkr)
        print(f'\n#### {tkr}  {df.index[0].date()}..{df.index[-1].date()} ####')
        rev_trades = {N: reversal_long(N)(df) for N in [2, 3]}
        rsi_trades = rsi2_long(df)

        for N in [2, 3]:
            tr = rev_trades[N]
            m1 = metrics(tr, pv, 1, tick)
            m3 = metrics(tr, pv, 3, tick)
            print(f'\n  reversal N={N} LONG-only  (n={m1["n"]})')
            print(f'    @1t PF={m1["pf"]:.2f} win%={m1["win_rate"]:.1%} '
                  f'maxDD${m1["maxdd_abs"]:,.0f} worst${m1["worst"]:,.0f} '
                  f'streak={m1["losing_streak"]} hold={m1["avg_hold"]:.1f}d')
            print(f'    @3t PF={m3["pf"]:.2f} win%={m3["win_rate"]:.1%} maxDD${m3["maxdd_abs"]:,.0f}')
            wf = walk_forward(tr, pv, 1, tick)
            print(f'    walk-fwd (40/20/40) @1t: train={wf["train"][0]}t PF{wf["train"][1]:.2f} | '
                  f'val={wf["validate"][0]}t PF{wf["validate"][1]:.2f} | '
                  f'OOS={wf["oos"][0]}t PF{wf["oos"][1]:.2f} win{wf["oos"][2]:.0%}')
            # correlation vs RSI2 (daily P&L, @1t)
            a = daily_pnl_series(tr, pv, 1, tick)
            b = daily_pnl_series(rsi_trades, pv, 1, tick)
            corr = a.corr(b) if (len(a) and len(b)) else float('nan')
            # signal overlap: entry-date set intersection
            rev_dates = {t['entry_date'] for t in tr}
            rsi_dates = {t['entry_date'] for t in rsi_trades}
            overlap = len(rev_dates & rsi_dates) / len(rev_dates) if rev_dates else 0.0
            print(f'    vs RSI2: daily-P&L corr={corr:+.2f}  entry-overlap={overlap:.0%} '
                  f'(rev={len(rev_dates)} entries, RSI2={len(rsi_dates)} entries)')

        # per-year PF for the best reversal (N=2) + RSI2, @1t
        print(f'\n  per-year PF @1t (reversal N=2 LONG vs RSI2):')
        print(f'    {"year":6s} {"rev_n":>4s} {"revPF":>7s} {"revDD$":>9s} | {"rsi2_n":>5s} {"rsi2PF":>7s}')
        rv = per_year_pf(rev_trades[2], pv, 1, tick)
        rs = per_year_pf(rsi_trades, pv, 1, tick)
        rsd = {y: (n, pf) for y, n, pf, net, dd in rs}
        for y, n, pf, net, dd in rv:
            rn, rpf = rsd.get(y, (0, float('nan')))
            print(f'    {y:<6d} {n:>4d} {pf:>7.2f} {dd:>9,.0f} | {rn:>5d} {rpf:>7.2f}')


if __name__ == '__main__':
    main()
