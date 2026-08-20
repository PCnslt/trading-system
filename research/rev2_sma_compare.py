import numpy as np, pandas as pd
from short_horizon_edges_study import fetch_daily, wilder_atr, run_trades, metrics, INSTR

def reversal_long(df, N, thresh_atr=1.0, stop_atr=2.0, max_hold=3, sma_filter=False):
    h, l, c = df['High'], df['Low'], df['Close']
    atr = wilder_atr(h, l, c, 14)
    retN = c.pct_change(N)
    sma200 = c.rolling(200).mean()
    atr_a, ret_a, cl_a = atr.values, retN.values, c.values
    sma_a = sma200.values

    def entry(i):
        if np.isnan(ret_a[i]) or np.isnan(atr_a[i]) or atr_a[i] <= 0:
            return 0
        if sma_filter and (np.isnan(sma_a[i]) or cl_a[i] <= sma_a[i]):
            return 0
        k = thresh_atr * atr_a[i] / cl_a[i]
        return 1 if ret_a[i] < -k else 0

    def stop(e, side, a):
        return e - stop_atr * a

    def exit_fn(i, side, entry, stop, held):
        return (cl_a[i] > entry), 'REVERT'

    return run_trades(df, entry, stop, exit_fn, max_hold)

for tkr in ['ES=F', 'NQ=F', 'YM=F']:
    pv, tick = INSTR[tkr]['pv'], INSTR[tkr]['tick']
    df = fetch_daily(tkr)
    print(f"### {tkr}")
    for sma in [False, True]:
        tr = reversal_long(df, 2, sma_filter=sma)
        m1 = metrics(tr, pv, 1, tick)
        m3 = metrics(tr, pv, 3, tick)
        lab = "REV2 (no filter)" if not sma else "REV2 + 200d-SMA filter"
        print(f"  {lab:24s} n={m1['n']:4d}  @1t PF={m1['pf']:.2f} win={m1['win_rate']:.0%} "
              f"maxDD=${m1['maxdd_abs']:,.0f}  @3t PF={m3['pf']:.2f}")
    print()
