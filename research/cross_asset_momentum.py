#!/usr/bin/env python3
"""Cross-asset short-term (1-month) time-series momentum — first-pass screen.

Tests the Zaremba et al. "short-term momentum (almost) everywhere" finding on
OUR deployable futures universe (indices + rates + energy + metals + ags — all
CME/CBOT/NYMEX/COMEX, all resolve on the paper account; FX majors excluded
because they GAP on this account's entitlement).

Strategy (time-series momentum, the deployable shape):
  - Signal at each MONTHLY rebalance (every 21 trading days): past-21d return,
    skipping the most recent day (avoid 1-day reversal contaminating momentum).
      mom = close[i-1]/close[i-1-lookback] - 1
      sign = +1 if mom>0, -1 if mom<0, 0 else.
  - Enter/flip at the rebalance bar CLOSE (+ adverse slippage in metrics()).
  - Disaster-floor stop 3xATR (gap-aware) — catastrophic-only, per the
    momentum-family stop rule (NOT a chandelier trail, which destroyed TSMOM).
  - Signal-flip exit at the next rebalance when the sign changes.

Honest fill model (per trading-backtest-validation skill):
  - gross P&L in points; slippage 0/1/3 ticks PER SIDE + 1.3bps RT notional fee
    applied in metrics() — same convention as short_horizon_edges_study.py.

Deliverables: lookback sweep (5/21/63), cost-stress table, 40/20/40 OOS,
per-asset-class breakdown, drawdown-first ranking.
"""
import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf

START = '2000-01-01'
FEE_BPS = 1.3 / 10000.0
REBAL = 21            # trading days per monthly rebalance
DISASTER_ATR = 3.0    # catastrophic-only stop

# (yf ticker, point_value $, tick size, asset_class, label)
UNIVERSE = [
    # indices
    ('ES=F', 50.0,    0.25,     'index',  'ES'),
    ('NQ=F', 20.0,    0.25,     'index',  'NQ'),
    ('YM=F', 5.0,     1.00,     'index',  'YM'),
    ('RTY=F', 50.0,   0.10,     'index',  'RTY'),
    # rates
    ('ZB=F', 1000.0,  0.03125,  'rates',  'ZB'),
    ('ZN=F', 1000.0,  0.015625, 'rates',  'ZN'),
    ('ZF=F', 1000.0,  0.0078125,'rates',  'ZF'),
    ('ZT=F', 2000.0,  0.00390625,'rates', 'ZT'),
    ('UB=F', 1000.0,  0.03125,  'rates',  'UB'),
    ('TN=F', 1000.0,  0.015625, 'rates',  'TN'),
    # energy
    ('CL=F', 1000.0,  0.01,     'energy', 'CL'),
    ('NG=F', 10000.0, 0.001,    'energy', 'NG'),
    ('RB=F', 42000.0, 0.0001,   'energy', 'RB'),
    ('HO=F', 42000.0, 0.0001,   'energy', 'HO'),
    ('BZ=F', 1000.0,  0.01,     'energy', 'BZ'),
    # metals
    ('GC=F', 100.0,   0.10,     'metals', 'GC'),
    ('SI=F', 5000.0,  0.005,    'metals', 'SI'),
    ('HG=F', 25000.0, 0.0005,   'metals', 'HG'),
    ('PL=F', 50.0,    0.10,     'metals', 'PL'),
    ('PA=F', 100.0,   0.50,     'metals', 'PA'),
    # ags
    ('ZC=F', 50.0,    0.25,     'ags',    'ZC'),
    ('ZW=F', 50.0,    0.25,     'ags',    'ZW'),
    ('ZS=F', 50.0,    0.25,     'ags',    'ZS'),
    ('ZM=F', 100.0,   0.10,     'ags',    'ZM'),
    ('ZL=F', 600.0,   0.01,     'ags',    'ZL'),
    ('KE=F', 50.0,    0.25,     'ags',    'KE'),
    ('HE=F', 400.0,   0.025,    'ags',    'HE'),
    ('LE=F', 400.0,   0.025,    'ags',    'LE'),
    ('GF=F', 500.0,   0.025,    'ags',    'GF'),
]


def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def fetch_daily(tkr):
    try:
        df = yf.download(tkr, start=START, interval='1d', progress=False, auto_adjust=True)
    except Exception as e:
        return None, f'fetch error: {e}'
    if df is None or len(df) == 0:
        return None, 'empty'
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    df.index = pd.to_datetime(df.index)
    return df, None


def run_tsmom(df, lookback=21, stop_atr=DISASTER_ATR, long_only=False):
    """Monthly-rebalanced time-series momentum. Returns list of trade dicts
    with gross P&L in POINTS (cost applied later in metrics())."""
    c = df['Close'].values
    h = df['High'].values
    l = df['Low'].values
    o = df['Open'].values
    atr = wilder_atr(df['High'], df['Low'], df['Close'], 14).values
    idx = df.index
    n = len(df)
    warmup = lookback + 5
    if n <= warmup:
        return []
    trades = []
    pos = None  # dict(side, entry, entry_i, stop)

    def record(i, exit_px, reason):
        nonlocal pos
        p = pos
        gross = (exit_px - p['entry']) * p['side']          # points, gross
        trades.append(dict(entry_date=idx[p['entry_i']], exit_date=idx[i],
                           reason=reason, pnl=gross, entry_px=p['entry'],
                           side=p['side']))
        pos = None

    i = warmup
    while i < n:
        # 1. disaster stop (gap-aware), only when in position
        if pos is not None and stop_atr is not None and not np.isnan(atr[i]):
            side, entry, stop = pos['side'], pos['entry'], pos['stop']
            if side == 1:
                if o[i] < stop:
                    record(i, o[i], 'STOP-GAP'); i += 1; continue
                if l[i] <= stop:
                    record(i, stop, 'STOP'); i += 1; continue
            else:
                if o[i] > stop:
                    record(i, o[i], 'STOP-GAP'); i += 1; continue
                if h[i] >= stop:
                    record(i, stop, 'STOP'); i += 1; continue
        # 2. monthly rebalance
        if (i - warmup) % REBAL == 0:
            mom = c[i - 1] / c[i - 1 - lookback] - 1.0
            sign = 1 if mom > 0 else (-1 if mom < 0 else 0)
            if long_only and sign == -1:
                sign = 0
            if pos is None:
                if sign != 0:
                    entry = c[i]
                    st = entry - stop_atr * atr[i] if sign == 1 else entry + stop_atr * atr[i]
                    pos = dict(side=sign, entry=entry, entry_i=i, stop=st)
            else:
                if sign != pos['side']:
                    record(i, c[i], 'FLIP' if sign != 0 else 'FLAT')
                    if sign != 0:
                        entry = c[i]
                        st = entry - stop_atr * atr[i] if sign == 1 else entry + stop_atr * atr[i]
                        pos = dict(side=sign, entry=entry, entry_i=i, stop=st)
        i += 1
    return trades


def metrics(trades, pv, tick, slip_ticks, fee_bps=FEE_BPS):
    """Drawdown-first stats. P&L in dollars with cost applied."""
    if not trades:
        return None
    rows = []
    for t in trades:
        gross = t['pnl'] * pv
        slip = 2 * slip_ticks * tick * pv
        fee = fee_bps * t['entry_px'] * pv
        rows.append(dict(entry_date=t['entry_date'], exit_date=t['exit_date'],
                         reason=t['reason'], side=t['side'], pnl=gross - slip - fee))
    pnl = pd.Series([r['pnl'] for r in rows])
    n = len(pnl)
    wins = (pnl > 0).sum()
    gross_w = pnl[pnl > 0].sum()
    gross_l = -pnl[pnl < 0].sum()
    pf = (gross_w / gross_l) if gross_l > 0 else float('inf')
    streak = max_streak = 0
    for p in pnl:
        streak = streak + 1 if p <= 0 else 0
        max_streak = max(max_streak, streak)
    daily = {}
    for r in rows:
        daily[r['exit_date']] = daily.get(r['exit_date'], 0.0) + r['pnl']
    all_days = pd.date_range(rows[0]['entry_date'], rows[-1]['exit_date'], freq='D')
    eq = pd.Series([daily.get(d, 0.0) for d in all_days], index=all_days).cumsum()
    peak = eq.cummax()
    maxdd_abs = (eq - peak).min()
    maxdd_rel = ((eq - peak) / peak.replace(0, np.nan)).min()
    return dict(n=n, win_rate=wins / n, pf=pf, maxdd_abs=maxdd_abs, maxdd_rel=maxdd_rel,
                worst=pnl.min(), losing_streak=max_streak, net=pnl.sum(),
                avg_hold=np.mean([(r['exit_date'] - r['entry_date']).days + 1 for r in rows]),
                avg_win=pnl[pnl > 0].mean() if wins else 0,
                avg_loss=pnl[pnl < 0].mean() if (pnl < 0).any() else 0)


def fmt(m):
    if m is None:
        return '0 trades'
    return (f"n={m['n']:4d}  win%={m['win_rate']:5.1%}  PF={m['pf']:5.2f}  "
            f"maxDD${m['maxdd_abs']:10,.0f} ({m['maxdd_rel']:6.1%})  worst${m['worst']:9,.0f}  "
            f"loseStreak={m['losing_streak']:2d}  net${m['net']:11,.0f}  hold={m['avg_hold']:.0f}d")


def oos_split(trades):
    """40/20/40 by ENTRY date."""
    if not trades:
        return None
    ed = pd.Series([t['entry_date'] for t in trades])
    lo, hi = ed.min(), ed.max()
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
    return seg


def main():
    print('=' * 100)
    print('CROSS-ASSET SHORT-TERM (1-MONTH) TIME-SERIES MOMENTUM — first-pass screen')
    print(f'data: yfinance continuous futures from {START} | fee {FEE_BPS*10000:.1f}bps RT | '
          f'disaster stop {DISASTER_ATR}xATR | rebalance {REBAL}d | drawdown-first')
    print('=' * 100)

    data = {}
    print('\nFetching universe...')
    for tkr, pv, tick, ac, lab in UNIVERSE:
        df, err = fetch_daily(tkr)
        if err:
            print(f'  [SKIP] {lab:4s} {tkr}: {err}')
            continue
        yrs = (df.index[-1] - df.index[0]).days / 365.25
        if yrs < 8:
            print(f'  [THIN] {lab:4s} {tkr}: only {yrs:.1f}y')
        data[tkr] = dict(df=df, pv=pv, tick=tick, ac=ac, lab=lab)

    print(f'\nLoaded {len(data)} contracts.\n')

    for lookback in [5, 21, 63]:
        print(f'\n{"#"*100}\nLOOKBACK = {lookback}d ({"1wk" if lookback==5 else "1mo" if lookback==21 else "3mo"})\n{"#"*100}')
        # pooled trades
        pooled = []
        per_class = {}
        for tkr, d in data.items():
            trades = run_tsmom(d['df'], lookback=lookback)
            for t in trades:
                t['_pv'] = d['pv']; t['_tick'] = d['tick']; t['_ac'] = d['ac']; t['_lab'] = d['lab']
            pooled.extend(trades)
            per_class.setdefault(d['ac'], []).extend(trades)

        for slip in [0, 1, 3]:
            # pooled metric: aggregate rows with per-trade pv/tick
            rows = []
            for t in pooled:
                gross = t['pnl'] * t['_pv']
                s = 2 * slip * t['_tick'] * t['_pv']
                fee = FEE_BPS * t['entry_px'] * t['_pv']
                rows.append(gross - s - fee)
            if not rows:
                print(f'  @{slip}t: 0 trades'); continue
            pnl = pd.Series(rows)
            w = pnl[pnl > 0].sum(); l = -pnl[pnl < 0].sum()
            pf = (w / l) if l > 0 else float('inf')
            # chronological equity pooled (approximate: sort by exit date)
            by_day = {}
            for t, v in zip(pooled, rows):
                by_day[t['exit_date']] = by_day.get(t['exit_date'], 0.0) + v
            days = pd.date_range(min(by_day), max(by_day), freq='D')
            eq = pd.Series([by_day.get(x, 0.0) for x in days], index=days).cumsum()
            dd = (eq - eq.cummax()).min()
            dd_rel = ((eq - eq.cummax()) / eq.cummax().replace(0, np.nan)).min()
            wr = (pnl > 0).mean()
            print(f'  @{slip}t POOLED  n={len(pnl):4d}  win%={wr:5.1%}  PF={pf:5.2f}  '
                  f'maxDD${dd:11,.0f} ({dd_rel:6.1%})  net${pnl.sum():12,.0f}  '
                  f'avg${pnl.mean():7,.0f}/trade')

        # per-asset-class (at 1 tick, the realistic reference)
        print(f'  --- per asset class @1t ---')
        for ac in ['index', 'rates', 'energy', 'metals', 'ags']:
            ts = per_class.get(ac, [])
            rows = []
            for t in ts:
                gross = t['pnl'] * t['_pv']
                s = 2 * 1 * t['_tick'] * t['_pv']
                fee = FEE_BPS * t['entry_px'] * t['_pv']
                rows.append(gross - s - fee)
            if not rows:
                print(f'    {ac:7s}: 0 trades'); continue
            pnl = pd.Series(rows)
            w = pnl[pnl > 0].sum(); l = -pnl[pnl < 0].sum()
            pf = (w / l) if l > 0 else float('inf')
            print(f'    {ac:7s}  n={len(pnl):4d}  win%={(pnl>0).mean():5.1%}  PF={pf:5.2f}  '
                  f'net${pnl.sum():11,.0f}  avg${pnl.mean():7,.0f}/trade')

    # OOS for the headline 1-month lookback
    print(f'\n{"#"*100}\nOOS 40/20/40 (lookback=21d, @1t) — pooled by entry date\n{"#"*100}')
    pooled = []
    for tkr, d in data.items():
        for t in run_tsmom(d['df'], lookback=21):
            t['_pv'] = d['pv']; t['_tick'] = d['tick']; t['_ac'] = d['ac']
            pooled.append(t)
    seg = oos_split(pooled)
    for k in ['train', 'validate', 'oos']:
        rows = []
        for t in seg[k]:
            gross = t['pnl'] * t['_pv']
            s = 2 * 1 * t['_tick'] * t['_pv']
            fee = FEE_BPS * t['entry_px'] * t['_pv']
            rows.append(gross - s - fee)
        if not rows:
            print(f'  {k:9s}: 0 trades'); continue
        pnl = pd.Series(rows)
        w = pnl[pnl > 0].sum(); l = -pnl[pnl < 0].sum()
        pf = (w / l) if l > 0 else float('inf')
        print(f'  {k:9s}  n={len(pnl):4d}  win%={(pnl>0).mean():5.1%}  PF={pf:5.2f}  '
              f'net${pnl.sum():12,.0f}')


if __name__ == '__main__':
    main()
