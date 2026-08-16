#!/usr/bin/env python3
"""EDGE SWEEP 2 — parameter-sensitivity confirmation (second pass).

Answers: "was the NO-GO a parameter choice, or is the edge genuinely absent?"
Reuses edge_sweep2 loaders/engine. Runs the cheap parameter alternatives the
first pass skipped, on the DEEPEST available data (yfinance continuous, 26y).

  xsmom futures : 12m-skip1 (baseline) vs 6m-skip1 vs 12m-skip0
  value         : 5y (baseline) vs 3y vs 10y lookback  (cross-sectional)
  vol overlay   : 20d (baseline) vs 60d realized-vol
  carry         : not re-run -- the gap is the DATA (fixed-spread proxy),
                  no parameter changes what "near/far" means without expired
                  contract history. Noted, not tested.

Paper-only. No live. No gateway restart.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import edge_sweep2 as e2  # noqa: E402

YF_SYMS = ['CL=F', 'GC=F', 'NG=F', 'SI=F', 'ZC=F', 'ZS=F', 'ZW=F',
           'ES=F', 'NQ=F', 'YM=F', 'RTY=F', 'ZB=F', 'ZN=F', '6E=F']


def load_yf_panel(min_months=120):
    closes, ticks = {}, {}
    for s in YF_SYMS:
        try:
            df = e2.load_yf_futures(s)
            me = e2.month_end_closes(df)
            if len(me) < min_months:
                continue
            closes[s] = me
            ticks[s] = e2.TICK.get(s, 0.01)
        except Exception as ex:
            print(f'  {s} load failed: {ex}')
    return pd.DataFrame(closes), ticks


def summarize(name, slip_series):
    r0 = e2.portfolio_metrics(slip_series[0])
    r1 = e2.portfolio_metrics(slip_series[1])
    wf = e2.walk_forward_ret(slip_series[0])
    print(f'  {name:34s} PF(s0)={r0["pf"]:.2f}  PF(s1)={r1["pf"]:.2f}  '
          f'sharpe={r0["sharpe"]:.2f}  ann={r0["ann_ret"]*100:+.1f}%  '
          f'maxDD={r0["maxdd"]*100:.1f}%  '
          f'WF train={wf["train"]["pf"]:.2f}/val={wf["validate"]["pf"]:.2f}/'
          f'OOS={wf["oos"]["pf"]:.2f}(n={wf["oos"]["n"]})')


def xsmom_params():
    print('\n' + '=' * 90)
    print('PARAM CHECK — cross-sectional momentum (futures), yfinance 26y')
    print('=' * 90)
    cdf, ticks = load_yf_panel()
    print(f'  universe: {len(cdf.columns)} symbols, '
          f'{cdf.index.min().date()}..{cdf.index.max().date()} ({len(cdf)} months)')
    for label, skip, look in [('12m skip1 (baseline)', 1, 11),
                              ('6m skip1', 1, 5),
                              ('12m skip0', 0, 11),
                              ('6m skip0', 0, 5)]:
        sc = e2.momentum_score(cdf, skip_months=skip, lookback_months=look)
        ss = e2.xsectional_futures(cdf, sc, 3, 3, ticks)
        summarize(label, ss)


def value_params():
    print('\n' + '=' * 90)
    print('PARAM CHECK — value / long-term reversal (cross-sectional), yfinance 26y')
    print('=' * 90)
    cdf, ticks = load_yf_panel(min_months=10 * 12 + 24)
    print(f'  universe: {len(cdf.columns)} symbols')
    for yrs in [5, 3, 10]:
        mean = cdf.rolling(yrs * 12).mean()
        val = np.log(cdf / mean)
        ss = e2.xsectional_futures(cdf, val, 3, 3, ticks)
        summarize(f'{yrs}y lookback' + (' (baseline)' if yrs == 5 else ''), ss)


def vol_params():
    print('\n' + '=' * 90)
    print('PARAM CHECK — vol-targeting overlay: 20d vs 60d realized vol')
    print('=' * 90)
    from research.validate_edges import run_donchian, run_rsi2_long
    specs = {'ES=F': (50.0, 0.25), 'GC=F': (100.0, 0.1)}
    for sym, (mult, tick) in specs.items():
        df = e2.load_yf_futures(sym)
        c = df['Close']
        r = c.pct_change().fillna(0.0)
        for n in [20, 60]:
            vol = e2.realized_vol(c, n=n).shift(1)
            line = f'  {sym} vol{n}d: '
            for strat, fn in [('DON', run_donchian), ('RSI2', run_rsi2_long)]:
                trades, _ = fn(df, mult=mult, tick=tick, slip=0)
                if not trades:
                    line += f'{strat}=no-trades  '
                    continue
                idx = df.index
                ret_b = pd.Series(0.0, index=idx)
                ret_o = pd.Series(0.0, index=idx)
                for t in trades:
                    ei, xi, dr = t['entry_i'], t['exit_i'], t['dir']
                    for k in range(ei + 1, xi + 1):
                        ret_b.iloc[k] = dr * r.iloc[k]
                    v = vol.iloc[ei]
                    w = 1.0 if (np.isnan(v) or v <= 0) else min(3.0, max(0.0, 0.10 / v))
                    for k in range(ei + 1, xi + 1):
                        ret_o.iloc[k] = w * dr * r.iloc[k]
                sb = e2._daily_metrics(ret_b)['sharpe']
                so = e2._daily_metrics(ret_o)['sharpe']
                line += f'{strat} base={sb:.2f}->ov={so:.2f}  '
            print(line)


if __name__ == '__main__':
    xsmom_params()
    value_params()
    vol_params()
    print('\nDone.')
