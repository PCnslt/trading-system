#!/usr/bin/env python3
"""Large-cap CROSS-SECTIONAL short-term reversal (de Groot/Huij/Zhou + FIM).

Candidate #3 from the deep-search. Unlike the live RSI2/REV2 (TIME-SERIES:
each name dips vs its own past), this is CROSS-SECTIONAL: rank the large-cap
universe by recent return and long the biggest LOSERS.

Method (vectorized):
  - Universe: 50 S&P100 large-caps (the live RSI2 equity universe).
  - At each rebalance (every H days), rank by past-L-day return; long the
    bottom-K losers, equal weight (1/K). Long-only (RH cash acct, no short).
  - Hold H days, mark-to-market daily for a real equity curve + maxDD.
  - Cost: bps per side {0, 5, 10} on bucket turnover (changed name = 1 sell +
    1 buy = 2 sides). Full turnover = 2*bps per rebalance.
Reports: lookback/hold/K sweep, cost stress, per-year, 40/20/40 OOS.
"""
import numpy as np
import pandas as pd

PKL = "/tmp/stock_mr_ohlcv.pkl"
STOCKS = ['MU', 'NVDA', 'MSFT', 'AAPL', 'AMD', 'TSLA', 'AMZN', 'INTC', 'GOOGL',
          'META', 'AVGO', 'PLTR', 'ORCL', 'AMAT', 'LRCX', 'LLY', 'NOW', 'NFLX',
          'COST', 'CRM', 'QCOM', 'TXN', 'ADBE', 'JPM', 'BAC', 'WFC', 'GS', 'MS',
          'XOM', 'CVX', 'COP', 'JNJ', 'UNH', 'PFE', 'MRK', 'ABBV', 'KO', 'PEP',
          'WMT', 'HD', 'MCD', 'DIS', 'NKE', 'SBUX', 'CAT', 'BA', 'GE', 'PG', 'BKNG']


def maxdd(eq):
    peak = eq.cummax()
    return float(((eq - peak) / peak).min())


def run(close, L, H, K, bps):
    rets = close.pct_change()
    past = close / close.shift(L) - 1.0
    n = len(close)
    cols = close.columns
    pos = {c: i for i, c in enumerate(cols)}
    wf = pd.DataFrame(0.0, index=close.index, columns=cols)
    holdings = None
    cost = pd.Series(0.0, index=close.index)
    for t in range(L + 2, n, H):
        pr = past.iloc[t].dropna()
        if len(pr) < K:
            continue
        losers = set(pr.nsmallest(K).index)
        if holdings is None:
            turnover = 1.0
        else:
            turnover = len(losers ^ holdings) / K   # fraction of bucket replaced
        holdings = losers
        # set the weight vector for the whole H-day holding window (reset, no drift of stale names)
        wf.iloc[t:min(t + H, n), [pos[s] for s in losers]] = 1.0 / K
        cost.loc[close.index[t]] = 2.0 * bps * turnover
    port = (wf.shift(1) * rets).sum(axis=1)
    net = port - cost
    active = wf.sum(axis=1) > 0            # days where a bucket is actually held
    return net[active].iloc[1:]           # drop the very first day (no prior weights)


def stats(dr):
    if len(dr) == 0:
        return None
    eq = (1 + dr).cumprod()
    yrs = len(dr) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else 0
    sh = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    return dict(cagr=cagr, sharpe=sh, maxdd=maxdd(eq), win_d=(dr > 0).mean(), n=len(dr))


def main():
    df = pd.read_pickle(PKL)
    close = df['close'].unstack(level=0).sort_index()
    close = close[[s for s in STOCKS if s in close.columns]]
    close = close.dropna(how='all').ffill()
    close = close.dropna(axis=1, thresh=3000)
    print(f'panel: {close.shape[0]}d x {close.shape[1]} names  {close.index[0].date()}..{close.index[-1].date()}')
    print(f'universe ({close.shape[1]}): {", ".join(close.columns)}')

    print('\n=== SWEEP (L lookback / H hold / K losers) — Sharpe, CAGR, maxDD @ 0/5/10bps ===')
    for L in [5, 21]:
        for H in [5, 21]:
            for K in [5, 10]:
                row = []
                for bps in [0.0, 0.0005, 0.0010]:
                    s = stats(run(close, L, H, K, bps))
                    row.append(f"{s['sharpe']:.2f} | {s['cagr']:+.1%} | {s['maxdd']:.1%}" if s else 'n/a')
                print(f'  L={L:2d} H={H:2d} K={K:2d}:  @0b {row[0]}   @5b {row[1]}   @10b {row[2]}')

    print('\n=== HEADLINE L=5 H=5 K=5 @5bps — per year ===')
    dr = run(close, 5, 5, 5, 0.0005)
    yr = (1 + dr).resample('YE').prod() - 1
    print('  ' + '  '.join(f'{y.year%100:02d}:{v:+.0%}' for y, v in yr.items()))

    print('\n=== OOS 40/20/40 L=5 H=5 K=5 @5bps ===')
    dr = run(close, 5, 5, 5, 0.0005)
    n = len(dr)
    for k, s in [('train', dr.iloc[:int(n*0.4)]), ('validate', dr.iloc[int(n*0.4):int(n*0.6)]),
                 ('oos', dr.iloc[int(n*0.6):])]:
        st = stats(s)
        print(f'  {k:9s}  CAGR={st["cagr"]:+.1%}  Sharpe={st["sharpe"]:.2f}  mDD={st["maxdd"]:.1%}  winD={st["win_d"]:.1%}')


if __name__ == '__main__':
    main()
