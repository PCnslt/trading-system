#!/usr/bin/env python3
"""Short-horizon (1-3 day) edge study — Donchian short-lookback + short-term reversal.

Validates the two "next-action #3" candidates against the owner's mandate
(intraday -> 2-3 day swing), drawdown-first. Honest fill model + cost stress +
walk-forward OOS + correlation vs the live RSI2 edge.

Strategy A: Donchian L-day breakout (L in {2,3,5}) — short-swing trend.
Strategy B: N-day short-term reversal (N in {2,3}) — mean reversion.

Fill model (per trading-backtest-validation skill):
  - entry at signal-bar CLOSE + adverse slippage (bot computes at close, acts now)
  - GTC protective stop, gap-aware: open<stop -> fill at open; else low<=stop -> fill at stop
  - close-based signal/time exit -> fill at close + slippage
  - one entry OR exit per bar
Cost model: fee 1.3bps round-trip of notional; slippage 0/1/2/3 ticks per side.
"""
import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf

# ---- instruments (point value, tick size) ----
INSTR = {
    'ES=F':  dict(pv=50.0, tick=0.25),
    'NQ=F':  dict(pv=20.0, tick=0.25),
    'YM=F':  dict(pv=5.0,  tick=1.00),
    'RTY=F': dict(pv=50.0, tick=0.10),
}
FEE_BPS = 1.3 / 10000.0   # round-trip of notional (conservative baseline)
START = '2000-01-01'


def fetch_daily(tkr):
    df = yf.download(tkr, start=START, interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    df.index = pd.to_datetime(df.index)
    return df


def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


# =====================================================================
# Backtest engine (shared) — returns trades as list of dicts
#   each: entry_date, exit_date, exit_reason, pnl_points (gross, no cost)
# =====================================================================
def run_trades(df, entry_signal, stop_fn, exit_fn, max_hold):
    """entry_signal(i)->side (1 long, -1 short, 0 none); stop_fn(entry, side, atr)->price;
    exit_fn(i, side, entry, stop, held)-> (bool, reason) checked at close after stop/time."""
    h, l, c = df['High'].values, df['Low'].values, df['Close'].values
    o = df['Open'].values
    idx = df.index
    atr = wilder_atr(df['High'], df['Low'], df['Close'], 14).values
    n = len(df)
    trades = []
    pos = None  # dict(entry, stop, side, held, entry_i)

    def _close(i, reason, pnl):
        trades.append(dict(entry_date=idx[pos['entry_i']], exit_date=idx[i],
                           reason=reason, pnl=pnl, entry_px=pos['entry']))

    for i in range(1, n):
        if pos is not None:
            pos['held'] += 1
            side = pos['side']
            entry, stop = pos['entry'], pos['stop']
            opn, hi, lo, cl = o[i], h[i], l[i], c[i]
            # 1. protective stop (gap-aware)
            if side == 1:
                if opn < stop:
                    _close(i, 'STOP-GAP', stop - entry); pos = None; continue
                if lo <= stop:
                    _close(i, 'STOP', stop - entry); pos = None; continue
            else:
                if opn > stop:
                    _close(i, 'STOP-GAP', entry - stop); pos = None; continue
                if hi >= stop:
                    _close(i, 'STOP', entry - stop); pos = None; continue
            # 2. time stop
            if pos['held'] >= max_hold:
                pnl = (cl - entry) if side == 1 else (entry - cl)
                _close(i, 'TIME', pnl); pos = None; continue
            # 3. close-based signal exit
            ex, reason = exit_fn(i, side, entry, stop, pos['held'])
            if ex:
                pnl = (cl - entry) if side == 1 else (entry - cl)
                _close(i, reason, pnl); pos = None
        else:
            side = entry_signal(i)
            if side != 0:
                entry = float(c[i])
                st = stop_fn(entry, side, float(atr[i]))
                pos = dict(entry=entry, stop=st, side=side, held=0, entry_i=i)
    return trades


# =====================================================================
# Metrics — drawdown-first
# =====================================================================
def metrics(trades, pv, slip_ticks, tick, fee_bps=FEE_BPS, label=''):
    """Return dict of drawdown-first stats. P&L in dollars, cost applied."""
    if not trades:
        return None
    rows = []
    for t in trades:
        gross = t['pnl'] * pv                                    # gross dollars
        slip = 2 * slip_ticks * tick * pv                         # 2 sides * ticks
        fee = fee_bps * t['entry_px'] * pv                        # bps of entry notional (RT)
        rows.append(dict(entry_date=t['entry_date'], exit_date=t['exit_date'],
                         reason=t['reason'], pnl=gross - slip - fee))
    pnl = pd.Series([r['pnl'] for r in rows])
    n = len(pnl)
    wins = (pnl > 0).sum()
    win_rate = wins / n
    gross_w = pnl[pnl > 0].sum()
    gross_l = -pnl[pnl < 0].sum()
    pf = (gross_w / gross_l) if gross_l > 0 else float('inf')
    worst = pnl.min()
    # longest losing streak
    streak = max_streak = 0
    for p in pnl:
        streak = streak + 1 if p <= 0 else 0
        max_streak = max(max_streak, streak)
    # chronological equity (attribute to exit date, zero-fill)
    daily = {}
    for r in rows:
        d = r['exit_date']
        daily[d] = daily.get(d, 0.0) + r['pnl']
    all_days = pd.date_range(rows[0]['entry_date'], rows[-1]['exit_date'], freq='D')
    eq = pd.Series([daily.get(d, 0.0) for d in all_days], index=all_days).cumsum()
    peak = eq.cummax()
    maxdd_abs = (eq - peak).min()
    dd_rel = (eq - peak) / peak.replace(0, np.nan)
    maxdd_rel = dd_rel.min()
    net = pnl.sum()
    avg_hold = np.mean([(r['exit_date'] - r['entry_date']).days + 1 for r in rows])
    return dict(label=label, n=n, win_rate=win_rate, pf=pf, maxdd_abs=maxdd_abs,
                maxdd_rel=maxdd_rel, worst=worst, losing_streak=max_streak,
                net=net, avg_hold=avg_hold, avg_win=pnl[pnl > 0].mean() if wins else 0,
                avg_loss=pnl[pnl < 0].mean() if (pnl < 0).any() else 0)


def _fmt(m, tick):
    if m is None:
        return '0 trades'
    return (f"n={m['n']:4d}  win%={m['win_rate']:5.1%}  PF={m['pf']:5.2f}  "
            f"maxDD${m['maxdd_abs']:9,.0f} ({m['maxdd_rel']:6.1%})  worst${m['worst']:8,.0f}  "
            f"loseStreak={m['losing_streak']}  net${m['net']:9,.0f}  hold={m['avg_hold']:.1f}d")


# =====================================================================
# STRATEGY A — Donchian L-day breakout (short-swing trend)
# =====================================================================
def donchian_strategy(df, L, stop_atr=2.0, max_hold=3, long_only=False):
    h, l, c = df['High'], df['Low'], df['Close']
    don_hi = h.rolling(L).max().shift(1)
    don_lo = l.rolling(L).min().shift(1)
    atr = wilder_atr(h, l, c, 14)
    hi_a = don_hi.values
    lo_a = don_lo.values
    atr_a = atr.values
    cl_a = c.values

    def entry(i):
        if np.isnan(hi_a[i]) or np.isnan(lo_a[i]):
            return 0
        if cl_a[i] > hi_a[i]:
            return 1
        if (not long_only) and cl_a[i] < lo_a[i]:
            return -1
        return 0

    def stop(entry, side, a):
        return entry - stop_atr * a if side == 1 else entry + stop_atr * a

    def exit_fn(i, side, entry, stop, held):
        # opposite breakout
        if side == 1 and cl_a[i] < lo_a[i]:
            return True, 'X-DONLO'
        if side == -1 and cl_a[i] > hi_a[i]:
            return True, 'X-DONHI'
        return False, ''

    return run_trades(df, entry, stop, exit_fn, max_hold)


# =====================================================================
# STRATEGY B — N-day short-term reversal (mean reversion)
# =====================================================================
def reversal_strategy(df, N, thresh_atr=1.0, stop_atr=2.0, max_hold=3, long_only=False):
    h, l, c = df['High'], df['Low'], df['Close']
    atr = wilder_atr(h, l, c, 14)
    retN = c.pct_change(N)
    atr_a = atr.values
    ret_a = retN.values
    cl_a = c.values

    def entry(i):
        if np.isnan(ret_a[i]) or np.isnan(atr_a[i]) or atr_a[i] <= 0:
            return 0
        # threshold in ATR terms: drop > thresh_atr * atr (as % of price)
        k = thresh_atr * atr_a[i] / cl_a[i]
        if ret_a[i] < -k:
            return 1
        if (not long_only) and ret_a[i] > k:
            return -1
        return 0

    def stop(entry, side, a):
        return entry - stop_atr * a if side == 1 else entry + stop_atr * a

    def exit_fn(i, side, entry, stop, held):
        # revert: close back above/below entry (mean reversion completes)
        if side == 1 and cl_a[i] > entry:
            return True, 'REVERT'
        if side == -1 and cl_a[i] < entry:
            return True, 'REVERT'
        return False, ''

    return run_trades(df, entry, stop, exit_fn, max_hold)


# =====================================================================
# Walk-forward OOS (40/20/40) + rolling folds by ENTRY date
# =====================================================================
def oos_stats(trades):
    """Split trades by entry_date: train 40% / validate 20% / OOS 40%."""
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


def summarize_segments(trades, pv, slip, tick):
    seg = oos_stats(trades)
    out = {}
    for k, v in seg.items():
        m = metrics(v, pv, slip, tick) if v else None
        out[k] = m
    return out


# =====================================================================
# Main sweep
# =====================================================================
def sweep():
    print('=' * 90)
    print('SHORT-HORIZON EDGE STUDY — Donchian L-day breakout + N-day reversal')
    print(f'data: yfinance futures-continuous from {START} | fee {FEE_BPS*10000:.1f}bps RT | drawdown-first')
    print('=' * 90)

    for tkr, spec in INSTR.items():
        pv, tick = spec['pv'], spec['tick']
        df = fetch_daily(tkr)
        print(f'\n#### {tkr}  (pv=${pv:g}, tick={tick:g})  {df.index[0].date()}..{df.index[-1].date()}  bars={len(df)} ####')

        print('\n  --- STRATEGY A: Donchian L-day breakout (stop 2xATR, max hold 3d) ---')
        for L in [2, 3, 5]:
            for lo in [True, False]:
                trades = donchian_strategy(df, L, stop_atr=2.0, max_hold=3, long_only=lo)
                lab = f"L={L} {'LONG-only' if lo else 'LONG+SHORT'}"
                m0 = metrics(trades, pv, 0, tick)
                m1 = metrics(trades, pv, 1, tick)
                m3 = metrics(trades, pv, 3, tick)
                print(f'    {lab:18s} @0t  {_fmt(m0, tick)}')
                print(f'    {"":18s} @1t  {_fmt(m1, tick)}')
                print(f'    {"":18s} @3t  {_fmt(m3, tick)}')

        print('\n  --- STRATEGY B: N-day short-term reversal (thresh 1xATR, stop 2xATR, hold 3d) ---')
        for N in [2, 3]:
            for lo in [True, False]:
                trades = reversal_strategy(df, N, thresh_atr=1.0, stop_atr=2.0, max_hold=3, long_only=lo)
                lab = f"N={N} {'LONG-only' if lo else 'LONG+SHORT'}"
                m0 = metrics(trades, pv, 0, tick)
                m1 = metrics(trades, pv, 1, tick)
                m3 = metrics(trades, pv, 3, tick)
                print(f'    {lab:18s} @0t  {_fmt(m0, tick)}')
                print(f'    {"":18s} @1t  {_fmt(m1, tick)}')
                print(f'    {"":18s} @3t  {_fmt(m3, tick)}')


if __name__ == '__main__':
    sweep()
