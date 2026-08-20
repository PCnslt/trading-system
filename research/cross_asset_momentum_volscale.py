#!/usr/bin/env python3
"""Cross-asset 1-month TSMOM — VOL-SCALED equal-risk portfolio (the real test).

The naive "1 contract each" pool weights a $115k bond the same as $22k corn,
so its dollar P&L and maxDD are notional artifacts. This builds the actual
Moskowitz-Ooi-Pedersen / Zaremba shape:

  - signal_i(t) = sign( past-21d return_i )   (skip most recent day)
  - weight_i(t)  = signal_i / realized_vol_63d_i,  normalized to 100% gross
  - daily portfolio return = sum( weight_i * r_i,t ), weights drift between
    monthly rebalances; rebalanced every 21 trading days.

Costs: turnover-weighted, per-contract, from each contract's actual tick +
1.3bps RT fee (so a wide-tick bond pays more per dollar of notional turnover).
Reports gross vs net (0/1/3-tick), Sharpe, CAGR, maxDD%, annual turnover,
and per-year returns for regime honesty.
"""
import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf

START = '2000-01-01'
FEE_BPS = 1.3 / 10000.0
REBAL = 21
TARGET_VOL = 0.15       # 15% annualized portfolio vol target (scale factor is
                        # arbitrary — cancels in normalization; only matters for
                        # the drift between rebalances, which we ignore)
LOOKBACK = 21
VOL_WIN = 63

UNIVERSE = [
    ('ES=F', 50.0, 0.25, 'index', 'ES'), ('NQ=F', 20.0, 0.25, 'index', 'NQ'),
    ('YM=F', 5.0, 1.00, 'index', 'YM'), ('RTY=F', 50.0, 0.10, 'index', 'RTY'),
    ('ZB=F', 1000.0, 0.03125, 'rates', 'ZB'), ('ZN=F', 1000.0, 0.015625, 'rates', 'ZN'),
    ('ZF=F', 1000.0, 0.0078125, 'rates', 'ZF'), ('ZT=F', 2000.0, 0.00390625, 'rates', 'ZT'),
    ('UB=F', 1000.0, 0.03125, 'rates', 'UB'), ('TN=F', 1000.0, 0.015625, 'rates', 'TN'),
    ('CL=F', 1000.0, 0.01, 'energy', 'CL'), ('NG=F', 10000.0, 0.001, 'energy', 'NG'),
    ('RB=F', 42000.0, 0.0001, 'energy', 'RB'), ('HO=F', 42000.0, 0.0001, 'energy', 'HO'),
    ('BZ=F', 1000.0, 0.01, 'energy', 'BZ'),
    ('GC=F', 100.0, 0.10, 'metals', 'GC'), ('SI=F', 5000.0, 0.005, 'metals', 'SI'),
    ('HG=F', 25000.0, 0.0005, 'metals', 'HG'), ('PL=F', 50.0, 0.10, 'metals', 'PL'),
    ('PA=F', 100.0, 0.50, 'metals', 'PA'),
    ('ZC=F', 50.0, 0.25, 'ags', 'ZC'), ('ZW=F', 50.0, 0.25, 'ags', 'ZW'),
    ('ZS=F', 50.0, 0.25, 'ags', 'ZS'), ('ZM=F', 100.0, 0.10, 'ags', 'ZM'),
    ('ZL=F', 600.0, 0.01, 'ags', 'ZL'), ('KE=F', 50.0, 0.25, 'ags', 'KE'),
    ('HE=F', 400.0, 0.025, 'ags', 'HE'), ('LE=F', 400.0, 0.025, 'ags', 'LE'),
    ('GF=F', 500.0, 0.025, 'ags', 'GF'),
]


def fetch(tkr):
    try:
        df = yf.download(tkr, start=START, interval='1d', progress=False, auto_adjust=True)
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Close'])
    df.index = pd.to_datetime(df.index)
    return df


def maxdd_pct(eq):
    peak = eq.cummax()
    return ((eq - peak) / peak).min()


def sharpe(daily_net, periods=252):
    if daily_net.std() == 0:
        return 0.0
    return float(np.sqrt(periods) * daily_net.mean() / daily_net.std())


def main():
    print('Fetching universe...')
    closes, pv_tick = {}, {}
    for tkr, pv, tick, ac, lab in UNIVERSE:
        df = fetch(tkr)
        if df is None or len(df) < 1500:
            continue
        closes[tkr] = df['Close']
        pv_tick[tkr] = (pv, tick, lab)
    # align panel
    panel = pd.DataFrame(closes).sort_index().dropna(how='all')
    rets = panel.pct_change()
    print(f'Panel: {len(panel.columns)} contracts, {panel.index[0].date()}..{panel.index[-1].date()}, '
          f'{len(panel)} days')

    # realized vol (63d, annualized)
    vol = rets.rolling(VOL_WIN).std() * np.sqrt(252)

    # momentum signal: past-21d return skipping most recent day
    mom = panel.shift(1) / panel.shift(1 + LOOKBACK) - 1.0

    # target weights (raw), rebalanced monthly
    w = pd.DataFrame(0.0, index=panel.index, columns=panel.columns)
    sig = np.sign(mom)
    raw = sig.div(vol.replace(0, np.nan))
    rebal_dates = panel.index[VOL_WIN + LOOKBACK + 2::REBAL]
    last_w = None
    for d in rebal_dates:
        r = raw.loc[d]
        r = r[np.isfinite(r)]
        if len(r) == 0:
            continue
        wts = r / r.abs().sum()          # normalize gross = 100%
        w.loc[d] = wts

    # forward-fill weights (constant between rebalances), then drift with returns
    wf = w.replace(0, np.nan).ffill().fillna(0.0)
    # weight drift: w_drifted = w * (1+r) then renormalized implicitly by not renormalizing
    # (positions in dollars grow with price). Compute drifted daily weights:
    wdrift = wf
    # simpler: daily portfolio return = sum(wf_t-1 * r_t) (weights set at prior close)
    port_ret = (wf.shift(1) * rets).sum(axis=1)

    # turnover at rebalance (cost driver): per-contract |w_new - w_old|
    wchg = wf.diff().abs()               # DataFrame, per-contract weight change
    turnover = wchg.sum(axis=1)          # total turnover (Series)
    # only meaningful at rebalance; between rebalances diff is ~0 (ffill) except drift we ignore

    # per-contract round-trip cost in bps of notional (fee + 2*slippage_ticks)
    def cost_bps(slip_ticks):
        out = {}
        for tkr in panel.columns:
            pv, tick, lab = pv_tick[tkr]
            px = float(panel[tkr].iloc[-1])
            slip_bps = 2 * slip_ticks * tick / px * 10000.0
            out[tkr] = FEE_BPS * 10000.0 + slip_bps
        return out

    # apply cost: at rebalance, cost = turnover_weights * cost_bps per unit notional
    # (approximate: cost charged on |weight change| which is the traded fraction of NAV)
    for slip in [0, 1, 3]:
        cb = cost_bps(slip)
        # turnover-weighted average cost in bps at each rebalance
        cost_series = pd.Series(0.0, index=panel.index)
        for d in rebal_dates:
            if d not in wf.index:
                continue
            tw = wchg.loc[d]             # per-contract |weight change| (Series)
            if tw.sum() == 0:
                continue
            # avg cost bps weighted by turnover
            avg_cb = sum(tw[tkr] * cb[tkr] for tkr in panel.columns) / tw.sum()
            cost_series.loc[d] = avg_cb / 10000.0 * tw.sum()   # fraction of NAV lost
        net_ret = port_ret - cost_series
        net_ret = net_ret.dropna()

        eq = (1 + net_ret).cumprod()
        cagr = eq.iloc[-1] ** (252 / len(net_ret)) - 1
        vol_a = net_ret.std() * np.sqrt(252)
        sh = sharpe(net_ret)
        mdd = maxdd_pct(eq)
        ann_turn = turnover[turnover > 0].sum() / (len(panel.index) / 252)
        # per-year
        yr = (1 + net_ret).resample('YE').prod() - 1
        yr_str = '  '.join(f'{y.year % 100:02d}:{v:+.0%}' for y, v in yr.items())
        print(f'\n@{slip}t slip:  CAGR={cagr:+.1%}  vol={vol_a:.1%}  Sharpe={sh:.2f}  '
              f'maxDD={mdd:.1%}  annTurnover={ann_turn:.1f}x')
        print(f'   per-year: {yr_str}')

    print('\nNOTE: gross exposure 100% (long+short), vol-scaled. maxDD is % of NAV.')


if __name__ == '__main__':
    main()
