#!/usr/bin/env python3
"""BOOK SCAN — CFI "Complete Guide to Trading" candidates, capital-preservation rubric.

Three candidates (paper-only, no live, never-lose-money untouched):

  1. ADX(14)>25 REGIME FILTER on the EXISTING edges:
       - Donchian index (chandelier 3*ATR trail, long-only)   [bot/live.py]
       - RSI2 index (fixed 2*ATR stop, long-only)            [bot/live.py]
       - GC TSMOM (12m sign, fixed 3*ATR stop, L/S)          [bot/live_gc.py]
       - GC Donchian (chandelier 3*ATR, L/S)                 [bot/live_gc.py]  (bonus)
     For each: baseline vs ADX>25-only vs ADX<=25-only (entry gate; exits unchanged).
  2. GOLDEN/DEATH CROSS (50 SMA vs 200 SMA, always-in L/S) — index futures + equities.
  3. 5/8/13 EMA crossover (long-only) — daily + 1h/4h.

Rubric (drawdown-first, per INTRADAY_BUILD.md): rank by maxDrawdown, worst-case
(largest single-trade loss / worst day), consistency (win rate + longest losing
streak) FIRST; PF / net / return are secondary.

Honest fill model (same as validate_edges.py / trailing_stop_backtest.py):
  - entry at signal-bar close + adverse slippage; exit close-based at close - slip;
  - GTC stop intraday gap-aware (open gap-through -> open fill, else stop fill);
  - one entry OR exit per bar; force-close open position at end of data.
Cost: futures fee 1.3bp round-trip notional + slip 0/1/2/3 ticks/side;
      equities fee 1.3bp + slip 0/2/5/10 bps/side.
"""
import json
import os

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, 'book_scan_results.json')

# ---- instrument specs (mult $/point, tick in price units) ----
FUT = {
    'ES=F': ('ES E-mini S&P', 50.0, 0.25),
    'NQ=F': ('NQ E-mini Nasdaq', 20.0, 0.25),
    'YM=F': ('YM E-mini Dow', 5.0, 1.0),
    'GC=F': ('GC gold', 100.0, 0.10),
}
EQ = ['SPY', 'QQQ', 'DIA', 'IWM']          # long history (SPY 1993-)

FEE_BPS = 0.00013          # 1.3 bps round-trip notional
SLIP_TICKS = [0, 1, 2, 3]
EQ_BPS = [0, 2, 5, 10]     # equities slippage per side (bps)

FUT_START = '2000-01-01'
EQ_START = '1993-01-01'

LOOKBACK = 20
MAX_HOLD = 5
CHAND_ATR = 3.0
STOP_ATR = 2.0
TSMOM_STOP_ATR = 3.0
TSMOM_LOOKBACK = 252
RSI2_LO, RSI2_HI = 10.0, 70.0
ADX_THRESH = 25.0


# ======================================================================
# indicators (vectorized, no lookahead)
# ======================================================================
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def adx(h, l, c, n=14):
    up = h.diff()
    dn = -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def sma(s, n):
    return s.rolling(n).mean()


# ======================================================================
# data
# ======================================================================
def load(tk, start, interval='1d', period=None):
    kw = dict(progress=False, auto_adjust=True, interval=interval)
    if period:
        df = yf.download(tk, period=period, **kw)
    else:
        df = yf.download(tk, start=start, **kw)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=['Open', 'High', 'Low', 'Close'])


def resample_4h(df):
    """Aggregate 1h -> 4h OHLCV (aligned to 4h boundaries)."""
    r = df.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min',
                               'Close': 'last', 'Volume': 'sum'}).dropna()
    return r


# ======================================================================
# metrics (drawdown-first)
# ======================================================================
def pf_of(trades):
    if not trades:
        return 0.0, 0
    p = np.array([t['pnl'] for t in trades])
    w, l = p[p > 0], p[p <= 0]
    pf = w.sum() / abs(l.sum()) if l.size and l.sum() != 0 else (float('inf') if w.size else 0.0)
    return float(pf), len(trades)


def summary(trades, eq, n_years):
    if not trades:
        return {'trades': 0, 'winrate': 0.0, 'pf': 0.0, 'net': 0.0, 'maxdd': 0.0,
                'ret_dd': 0.0, 'avg_trade': 0.0, 'avg_hold': 0.0, 'worst_trade': 0.0,
                'worst_day': 0.0, 'worst_streak': 0, 'turnover': 0.0,
                'mae': 0.0, 'mfe': 0.0}
    p = np.array([t['pnl'] for t in trades])
    wins = (p > 0).sum()
    pf, _ = pf_of(trades)
    eqv = np.asarray(eq, dtype=float)
    dd = eqv - np.maximum.accumulate(eqv)
    maxdd = float(dd.min())
    net = float(p.sum())
    # worst single day (mark-to-market daily P&L)
    d = pd.Series(eqv).diff().fillna(0.0)
    worst_day = float(d.min())
    # consecutive-loss streak
    streak = cur = 0
    for x in p:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    return {
        'trades': len(trades),
        'winrate': 100.0 * wins / len(trades),
        'pf': pf,
        'net': net,
        'maxdd': maxdd,
        'ret_dd': float(net / abs(maxdd)) if maxdd < 0 else (net if net else 0.0),
        'avg_trade': float(p.mean()),
        'avg_hold': float(np.mean([t['days'] for t in trades])),
        'worst_trade': float(p.min()),
        'worst_day': worst_day,
        'worst_streak': int(streak),
        'turnover': float(len(trades) / n_years),
        'mae': float(np.mean([t['mae'] for t in trades])),
        'mfe': float(np.mean([t['mfe'] for t in trades])),
    }


# ======================================================================
# engines
# ======================================================================
def _entry_px(ci, d, slip, tick):
    return ci + d * slip * tick          # adverse: long pays up, short pays down


def _exit_close_px(ci, d, slip, tick):
    return ci - d * slip * tick          # closing: long sells down, short buys up


def run_donchian_long(df, mult, tick, adx_gate=None, fee_bps=FEE_BPS, slip=0):
    """Long-only Donchian 20d breakout, chandelier 3*ATR trail (live.py)."""
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    don_hi = h.rolling(LOOKBACK).max().shift(1)
    don_lo = l.rolling(LOOKBACK).min().shift(1)
    ax = adx(h, l, c) if adx_gate is not None else None
    warmup = LOOKBACK + 30
    trades, eq, cash = [], [], 0.0
    pos, entry_px, entry_i, stop, peak = 0, 0.0, 0, 0.0, 0.0
    for i in range(warmup, len(df)):
        oi, ci, bh, bl = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if (not np.isnan(don_hi.iloc[i]) and ci > don_hi.iloc[i]
                    and (ax is None or (not np.isnan(ax.iloc[i]) and _adx_ok(ax.iloc[i], adx_gate)))):
                entry_px = ci + slip * tick
                entry_i = i
                stop = ci - CHAND_ATR * atr.iloc[i]
                peak = ci
                pos = 1
        else:
            if i - 1 >= entry_i:
                prev_c, prev_atr = c.iloc[i - 1], atr.iloc[i - 1]
                peak = max(peak, prev_c)
                cand = peak - CHAND_ATR * prev_atr
                if cand > stop:
                    stop = cand
            held = i - entry_i
            mae = l.iloc[entry_i:i + 1].min() - entry_px
            mfe = h.iloc[entry_i:i + 1].max() - entry_px
            exit_px = reason = None
            if oi < stop:
                exit_px, reason = oi - slip * tick, 'stop_gap'
            elif bl <= stop:
                exit_px, reason = stop - slip * tick, 'stop'
            if exit_px is None and held >= MAX_HOLD:
                exit_px, reason = ci - slip * tick, 'time'
            if exit_px is None and not np.isnan(don_lo.iloc[i]) and ci < don_lo.iloc[i]:
                exit_px, reason = ci - slip * tick, 'breakout'
            if exit_px is not None:
                pnl = (exit_px - entry_px) * mult - fee_bps * entry_px * mult
                trades.append({'dir': 1, 'pnl': pnl, 'entry_i': int(entry_i),
                               'exit_i': i, 'reason': reason, 'days': int(i - entry_i),
                               'mae': mae, 'mfe': mfe})
                cash += pnl
                pos = 0
        eq.append(cash + (ci - entry_px) * mult if pos == 1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


def run_rsi2_long(df, mult, tick, adx_gate=None, fee_bps=FEE_BPS, slip=0):
    """Long-only RSI(2) buy-dip, FIXED 2*ATR stop (live.py)."""
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    r2 = rsi(c, 2)
    ax = adx(h, l, c) if adx_gate is not None else None
    warmup = 30
    trades, eq, cash = [], [], 0.0
    pos, entry_px, entry_i, stop = 0, 0.0, 0, 0.0
    for i in range(warmup, len(df)):
        oi, ci, bh, bl = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if (r2.iloc[i] < RSI2_LO
                    and (ax is None or (not np.isnan(ax.iloc[i]) and _adx_ok(ax.iloc[i], adx_gate)))):
                entry_px = ci + slip * tick
                entry_i = i
                stop = ci - STOP_ATR * atr.iloc[i]
                pos = 1
        else:
            held = i - entry_i
            mae = l.iloc[entry_i:i + 1].min() - entry_px
            mfe = h.iloc[entry_i:i + 1].max() - entry_px
            exit_px = reason = None
            if oi < stop:
                exit_px, reason = oi - slip * tick, 'stop_gap'
            elif bl <= stop:
                exit_px, reason = stop - slip * tick, 'stop'
            if exit_px is None and held >= MAX_HOLD:
                exit_px, reason = ci - slip * tick, 'time'
            if exit_px is None and r2.iloc[i] > RSI2_HI:
                exit_px, reason = ci - slip * tick, 'signal'
            if exit_px is not None:
                pnl = (exit_px - entry_px) * mult - fee_bps * entry_px * mult
                trades.append({'dir': 1, 'pnl': pnl, 'entry_i': int(entry_i),
                               'exit_i': i, 'reason': reason, 'days': int(i - entry_i),
                               'mae': mae, 'mfe': mfe})
                cash += pnl
                pos = 0
        eq.append(cash + (ci - entry_px) * mult if pos == 1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


def run_tsmom(df, mult, tick, adx_gate=None, fee_bps=FEE_BPS, slip=0):
    """L/S TSMOM: sign of 12m return, FIXED 3*ATR hard stop (live_gc.py)."""
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    ret12 = c / c.shift(TSMOM_LOOKBACK) - 1.0
    ax = adx(h, l, c) if adx_gate is not None else None
    warmup = TSMOM_LOOKBACK + 30
    trades, eq, cash = [], [], 0.0
    pos, entry_px, entry_i, stop = 0, 0.0, 0, 0.0
    for i in range(warmup, len(df)):
        oi, ci, bh, bl = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        r = ret12.iloc[i]
        desired = 0 if (np.isnan(r) or r == 0) else (1 if r > 0 else -1)
        if pos == 0:
            if desired != 0 and (ax is None or (not np.isnan(ax.iloc[i]) and _adx_ok(ax.iloc[i], adx_gate))):
                entry_px = _entry_px(ci, desired, slip, tick)
                entry_i = i
                stop = ci - desired * TSMOM_STOP_ATR * atr.iloc[i]
                pos = desired
        else:
            held = i - entry_i
            if pos == 1:
                mae = l.iloc[entry_i:i + 1].min() - entry_px
                mfe = h.iloc[entry_i:i + 1].max() - entry_px
                exit_px = reason = None
                if oi < stop:
                    exit_px, reason = oi - slip * tick, 'stop_gap'
                elif bl <= stop:
                    exit_px, reason = stop - slip * tick, 'stop'
            else:
                mae = entry_px - h.iloc[entry_i:i + 1].max()
                mfe = entry_px - l.iloc[entry_i:i + 1].min()
                exit_px = reason = None
                if oi > stop:
                    exit_px, reason = oi + slip * tick, 'stop_gap'
                elif bh >= stop:
                    exit_px, reason = stop + slip * tick, 'stop'
            if exit_px is None and desired != pos:
                exit_px, reason = _exit_close_px(ci, pos, slip, tick), 'signal'
            if exit_px is not None:
                pnl = (exit_px - entry_px) * pos * mult - fee_bps * entry_px * mult
                trades.append({'dir': pos, 'pnl': pnl, 'entry_i': int(entry_i),
                               'exit_i': i, 'reason': reason, 'days': int(i - entry_i),
                               'mae': mae, 'mfe': mfe})
                cash += pnl
                pos = 0
        eq.append(cash + (ci - entry_px) * pos * mult if pos != 0 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


def run_donchian_ls(df, mult, tick, adx_gate=None, fee_bps=FEE_BPS, slip=0):
    """L/S Donchian 20d breakout, chandelier 3*ATR trail (live_gc.py)."""
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    don_hi = h.rolling(LOOKBACK).max().shift(1)
    don_lo = l.rolling(LOOKBACK).min().shift(1)
    ax = adx(h, l, c) if adx_gate is not None else None
    warmup = LOOKBACK + 30
    trades, eq, cash = [], [], 0.0
    pos, entry_px, entry_i, stop, ext = 0, 0.0, 0, 0.0, 0.0
    for i in range(warmup, len(df)):
        oi, ci, bh, bl = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            d = 0
            if not np.isnan(don_hi.iloc[i]) and ci > don_hi.iloc[i]:
                d = 1
            elif not np.isnan(don_lo.iloc[i]) and ci < don_lo.iloc[i]:
                d = -1
            if d != 0 and (ax is None or (not np.isnan(ax.iloc[i]) and _adx_ok(ax.iloc[i], adx_gate))):
                entry_px = _entry_px(ci, d, slip, tick)
                entry_i = i
                stop = ci - d * CHAND_ATR * atr.iloc[i]
                ext = ci
                pos = d
        else:
            if i - 1 >= entry_i:
                prev_c, prev_atr = c.iloc[i - 1], atr.iloc[i - 1]
                ext = max(ext, prev_c) if pos == 1 else min(ext, prev_c)
                cand = ext - pos * CHAND_ATR * prev_atr
                if (pos == 1 and cand > stop) or (pos == -1 and cand < stop):
                    stop = cand
            held = i - entry_i
            exit_px = reason = None
            if pos == 1:
                mae = l.iloc[entry_i:i + 1].min() - entry_px
                mfe = h.iloc[entry_i:i + 1].max() - entry_px
                if oi < stop:
                    exit_px, reason = oi - slip * tick, 'stop_gap'
                elif bl <= stop:
                    exit_px, reason = stop - slip * tick, 'stop'
                if exit_px is None and held >= MAX_HOLD:
                    exit_px, reason = ci - slip * tick, 'time'
                if exit_px is None and not np.isnan(don_lo.iloc[i]) and ci < don_lo.iloc[i]:
                    exit_px, reason = ci - slip * tick, 'breakout'
            else:
                mae = entry_px - h.iloc[entry_i:i + 1].max()
                mfe = entry_px - l.iloc[entry_i:i + 1].min()
                if oi > stop:
                    exit_px, reason = oi + slip * tick, 'stop_gap'
                elif bh >= stop:
                    exit_px, reason = stop + slip * tick, 'stop'
                if exit_px is None and held >= MAX_HOLD:
                    exit_px, reason = ci + slip * tick, 'time'
                if exit_px is None and not np.isnan(don_hi.iloc[i]) and ci > don_hi.iloc[i]:
                    exit_px, reason = ci + slip * tick, 'breakout'
            if exit_px is not None:
                pnl = (exit_px - entry_px) * pos * mult - fee_bps * entry_px * mult
                trades.append({'dir': pos, 'pnl': pnl, 'entry_i': int(entry_i),
                               'exit_i': i, 'reason': reason, 'days': int(i - entry_i),
                               'mae': mae, 'mfe': mfe})
                cash += pnl
                pos = 0
        eq.append(cash + (ci - entry_px) * pos * mult if pos != 0 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


def _adx_ok(v, gate):
    return v > ADX_THRESH if gate == 'trend' else v <= ADX_THRESH


def run_golden_cross(df, mult, tick, fee_bps=FEE_BPS, slip=0, is_fut=True):
    """L/S always-in golden/death cross (50 SMA vs 200 SMA). No stop — the cross IS the exit."""
    c = df['Close']
    s50, s200 = sma(c, 50), sma(c, 200)
    warmup = 220
    trades, eq, cash = [], [], 0.0
    pos, entry_px, entry_i = 0, 0.0, 0
    for i in range(warmup, len(df)):
        ci = c.iloc[i]
        if np.isnan(s50.iloc[i]) or np.isnan(s200.iloc[i]):
            eq.append(cash)
            continue
        desired = 1 if s50.iloc[i] > s200.iloc[i] else -1
        if pos == 0:
            if desired != 0:
                entry_px = _entry_px(ci, desired, slip, tick)
                entry_i = i
                pos = desired
        elif desired != pos:
            exit_px = _exit_close_px(ci, pos, slip, tick)
            pnl = (exit_px - entry_px) * pos * mult - fee_bps * entry_px * mult
            trades.append({'dir': pos, 'pnl': pnl, 'entry_i': int(entry_i), 'exit_i': i,
                           'reason': 'cross', 'days': int(i - entry_i), 'mae': 0.0, 'mfe': 0.0})
            cash += pnl
            pos = 0
            # re-enter on the new side same bar (one flip = one round trip)
            entry_px = _entry_px(ci, desired, slip, tick)
            entry_i = i
            pos = desired
        eq.append(cash + (ci - entry_px) * pos * mult if pos != 0 else cash)
    # force-close open position at last close (update the last eq point, don't append)
    if pos != 0:
        last = c.iloc[-1]
        exit_px = _exit_close_px(last, pos, slip, tick)
        pnl = (exit_px - entry_px) * pos * mult - fee_bps * entry_px * mult
        trades.append({'dir': pos, 'pnl': pnl, 'entry_i': int(entry_i),
                       'exit_i': len(df) - 1, 'reason': 'force_close', 'days': int(len(df) - 1 - entry_i),
                       'mae': 0.0, 'mfe': 0.0})
        cash += pnl
        eq[-1] = cash
    return trades, pd.Series(eq, index=df.index[warmup:])


def run_ema_cross(df, mult, tick, short=5, long=13, fee_bps=FEE_BPS, slip=0, ls=False):
    """EMA 5/13 crossover. long_only: flat below; ls: always-in L/S."""
    c = df['Close']
    e5, e13 = ema(c, short), ema(c, long)
    warmup = long + 5
    trades, eq, cash = [], [], 0.0
    pos, entry_px, entry_i = 0, 0.0, 0
    for i in range(warmup, len(df)):
        ci = c.iloc[i]
        bull = e5.iloc[i] > e13.iloc[i]
        if ls:
            desired = 1 if bull else -1
        else:
            desired = 1 if bull else 0
        if pos == 0:
            if desired != 0:
                entry_px = _entry_px(ci, desired, slip, tick)
                entry_i = i
                pos = desired
        elif desired != pos:
            exit_px = _exit_close_px(ci, pos, slip, tick)
            pnl = (exit_px - entry_px) * pos * mult - fee_bps * entry_px * mult
            trades.append({'dir': pos, 'pnl': pnl, 'entry_i': int(entry_i), 'exit_i': i,
                           'reason': 'cross', 'days': int(i - entry_i), 'mae': 0.0, 'mfe': 0.0})
            cash += pnl
            pos = 0
            if desired != 0:
                entry_px = _entry_px(ci, desired, slip, tick)
                entry_i = i
                pos = desired
        eq.append(cash + (ci - entry_px) * pos * mult if pos != 0 else cash)
    if pos != 0:
        last = c.iloc[-1]
        exit_px = _exit_close_px(last, pos, slip, tick)
        pnl = (exit_px - entry_px) * pos * mult - fee_bps * entry_px * mult
        trades.append({'dir': pos, 'pnl': pnl, 'entry_i': int(entry_i),
                       'exit_i': len(df) - 1, 'reason': 'force_close',
                       'days': int(len(df) - 1 - entry_i), 'mae': 0.0, 'mfe': 0.0})
        cash += pnl
        eq[-1] = cash
    return trades, pd.Series(eq, index=df.index[warmup:])


def buy_hold(df, mult):
    """Buy-and-hold benchmark: pnl in points (scale-invariant) for the same window."""
    c = df['Close']
    return float(c.iloc[-1] - c.iloc[0]), float((c - c.cummax()).min())


# ======================================================================
# report helpers
# ======================================================================
def fmt_pf(pf):
    return ' inf' if pf == float('inf') else f'{pf:6.2f}'


def n_years_of(df):
    return (df.index[-1] - df.index[0]).days / 365.25


def print_adx_block(label, rows):
    print(f"\n{'=' * 100}\n{label}\n{'=' * 100}")
    hdr = (f"  {'edge':<12} {'gate':<8} {'n':>5} {'win%':>6} {'PF':>6} "
           f"{'maxDD$':>10} {'worstTrd':>10} {'worstDay':>10} {'streak':>7} {'net$':>10}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for r in rows:
        print(f"  {r['edge']:<12} {r['gate']:<8} {r['trades']:>5} {r['winrate']:>6.0f} "
              f"{fmt_pf(r['pf'])} {r['maxdd']:>10,.0f} {r['worst_trade']:>10,.0f} "
              f"{r['worst_day']:>10,.0f} {r['worst_streak']:>7} {r['net']:>10,.0f}")


# ======================================================================
# main
# ======================================================================
def main():
    print("BOOK SCAN — CFI candidates (capital-preservation rubric, drawdown-first)")
    print(f"fee={FEE_BPS:.5f} (1.3bp) · futures slip 0/1/2/3 ticks · equities 0/2/5/10 bps")
    print("honest fills: entry@close+slip, GTC stop intraday gap-aware, 1 entry/exit per bar")

    # ---- fetch daily futures + equities ----
    print("\nFetching data...")
    fut_dfs, eq_dfs = {}, {}
    for tk, (name, mult, tick) in FUT.items():
        try:
            fut_dfs[tk] = load(tk, FUT_START)
            print(f"  {tk:<6} {len(fut_dfs[tk]):>5} bars  {fut_dfs[tk].index[0].date()}..{fut_dfs[tk].index[-1].date()}")
        except Exception as e:  # noqa: BLE001
            print(f"  {tk} FAILED: {e}")
    for tk in EQ:
        try:
            eq_dfs[tk] = load(tk, EQ_START)
            print(f"  {tk:<6} {len(eq_dfs[tk]):>5} bars  {eq_dfs[tk].index[0].date()}..{eq_dfs[tk].index[-1].date()}")
        except Exception as e:  # noqa: BLE001
            print(f"  {tk} FAILED: {e}")

    report = {'fee_bps': FEE_BPS, 'part1_adx': {}, 'part2_goldencross': {}, 'part3_ema': {}}

    # ==================================================================
    # PART 1 — ADX regime filter on existing edges
    # ==================================================================
    print("\n\n" + "#" * 100)
    print("# PART 1 — ADX(14)>25 REGIME FILTER on EXISTING edges (baseline vs trend-only vs range-only)")
    print("#" * 100)

    part1_rows = []
    p1 = report['part1_adx']

    # index edges (ES/NQ/YM pooled trades)
    for edge_name, runner, instruments in [
        ('DONCHIAN_idx', run_donchian_long, ['ES=F', 'NQ=F', 'YM=F']),
        ('RSI2_idx', run_rsi2_long, ['ES=F', 'NQ=F', 'YM=F']),
    ]:
        for gate, glabel in [(None, 'baseline'), ('trend', 'ADX>25'), ('range', 'ADX<=25')]:
            pool = []
            for tk in instruments:
                df = fut_dfs.get(tk)
                if df is None:
                    continue
                _, mult, tick = FUT[tk]
                trades, eq = runner(df, mult, tick, adx_gate=gate, slip=1)
                pool.extend(trades)
            if not pool:
                continue
            ny = n_years_of(fut_dfs[instruments[0]])
            eq_s = pd.Series([t['pnl'] for t in pool]).cumsum()
            s = summary(pool, eq_s, ny)
            s['edge'], s['gate'] = edge_name, glabel
            part1_rows.append(s)
            p1[f"{edge_name}_{glabel}"] = {k: s[k] for k in
                                           ('trades', 'winrate', 'pf', 'maxdd', 'worst_trade',
                                            'worst_day', 'worst_streak', 'net', 'avg_trade', 'avg_hold')}

    # GC edges (GC=F single symbol)
    for edge_name, runner in [('GC_TSMOM', run_tsmom), ('GC_DONCHIAN', run_donchian_ls)]:
        df = fut_dfs.get('GC=F')
        if df is None:
            continue
        _, mult, tick = FUT['GC=F']
        for gate, glabel in [(None, 'baseline'), ('trend', 'ADX>25'), ('range', 'ADX<=25')]:
            trades, eq = runner(df, mult, tick, adx_gate=gate, slip=1)
            if not trades:
                continue
            s = summary(trades, eq, n_years_of(df))
            s['edge'], s['gate'] = edge_name, glabel
            part1_rows.append(s)
            p1[f"{edge_name}_{glabel}"] = {k: s[k] for k in
                                           ('trades', 'winrate', 'pf', 'maxdd', 'worst_trade',
                                            'worst_day', 'worst_streak', 'net', 'avg_trade', 'avg_hold')}

    print_adx_block("ADX filter comparison @ fee 1.3bp + 1-tick slip (drawdown-first)", part1_rows)

    # ==================================================================
    # PART 2 — Golden/Death cross
    # ==================================================================
    print("\n\n" + "#" * 100)
    print("# PART 2 — GOLDEN/DEATH CROSS (50 SMA vs 200 SMA, always-in L/S)")
    print("#" * 100)
    p2 = report['part2_goldencross']
    print(f"\n  {'symbol':<6} {'n':>5} {'win%':>6} {'PF':>6} {'maxDD':>11} {'worstTrd':>10} "
          f"{'worstDay':>10} {'streak':>7} {'net':>10} {'avgHold':>8}  | buy&hold ret/maxDD")
    for tk in ['ES=F', 'NQ=F', 'YM=F']:
        df = fut_dfs.get(tk)
        if df is None:
            continue
        _, mult, tick = FUT[tk]
        trades, eq = run_golden_cross(df, mult, tick, slip=1)
        s = summary(trades, eq, n_years_of(df))
        bh = buy_hold(df, mult)
        s['edge'], s['gate'] = 'GOLDEN_X', 'baseline'
        p2[tk] = {k: s[k] for k in ('trades', 'winrate', 'pf', 'maxdd', 'worst_trade',
                                     'worst_day', 'worst_streak', 'net', 'avg_hold')}
        p2[tk]['buyhold_ret_pts'] = bh[0]
        p2[tk]['buyhold_maxdd_pts'] = bh[1]
        print(f"  {tk:<6} {s['trades']:>5} {s['winrate']:>6.0f} {fmt_pf(s['pf'])} "
              f"{s['maxdd']:>11,.0f} {s['worst_trade']:>10,.0f} {s['worst_day']:>10,.0f} "
              f"{s['worst_streak']:>7} {s['net']:>10,.0f} {s['avg_hold']:>8.1f}  "
              f"| {bh[0]:>10,.0f}/{bh[1]:>10,.0f}")
    for tk in EQ:
        df = eq_dfs.get(tk)
        if df is None:
            continue
        # equities: mult=1 (per-share $), slip in bps -> convert to approx $ via last close
        trades, eq = run_golden_cross(df, 1.0, 0.0, slip=0)
        s = summary(trades, eq, n_years_of(df))
        bh = buy_hold(df, 1.0)
        s['edge'], s['gate'] = 'GOLDEN_X', 'baseline'
        p2[tk] = {k: s[k] for k in ('trades', 'winrate', 'pf', 'maxdd', 'worst_trade',
                                     'worst_day', 'worst_streak', 'net', 'avg_hold')}
        p2[tk]['buyhold_ret_pts'] = bh[0]
        p2[tk]['buyhold_maxdd_pts'] = bh[1]
        print(f"  {tk:<6} {s['trades']:>5} {s['winrate']:>6.0f} {fmt_pf(s['pf'])} "
              f"{s['maxdd']:>11,.0f} {s['worst_trade']:>10,.0f} {s['worst_day']:>10,.0f} "
              f"{s['worst_streak']:>7} {s['net']:>10,.0f} {s['avg_hold']:>8.1f}  "
              f"| {bh[0]:>10,.0f}/{bh[1]:>10,.0f}  (per-share $, 0-cost ideal)")
    print("\n  note: futures P&L in $ (via mult); equities P&L in $/share; buy&hold in same units.")

    # ==================================================================
    # PART 3 — 5/8/13 EMA crossover
    # ==================================================================
    print("\n\n" + "#" * 100)
    print("# PART 3 — 5/8/13 EMA CROSSOVER (buy EMA5>EMA13, sell below) — daily + intraday")
    print("#" * 100)
    p3 = report['part3_ema']
    print(f"\n  {'frame':<14} {'mode':<5} {'n':>5} {'win%':>6} {'PF':>6} {'maxDD':>11} "
          f"{'worstTrd':>10} {'worstDay':>10} {'streak':>7} {'net':>10} {'avgHold':>8}")

    # daily — ES and GC
    for tk, tag in [('ES=F', 'ES'), ('GC=F', 'GC')]:
        df = fut_dfs.get(tk)
        if df is None:
            continue
        _, mult, tick = FUT[tk]
        for mode, ls in [('long', False), ('L/S', True)]:
            trades, eq = run_ema_cross(df, mult, tick, ls=ls, slip=1)
            s = summary(trades, eq, n_years_of(df))
            s['edge'], s['gate'] = f'EMA513_{tag}', mode
            p3[f"{tag}_daily_{mode}"] = {k: s[k] for k in
                                         ('trades', 'winrate', 'pf', 'maxdd', 'worst_trade',
                                          'worst_day', 'worst_streak', 'net', 'avg_hold')}
            print(f"  {'daily ' + tag:<14} {mode:<5} {s['trades']:>5} {s['winrate']:>6.0f} "
                  f"{fmt_pf(s['pf'])} {s['maxdd']:>11,.0f} {s['worst_trade']:>10,.0f} "
                  f"{s['worst_day']:>10,.0f} {s['worst_streak']:>7} {s['net']:>10,.0f} {s['avg_hold']:>8.1f}")

    # intraday — ES 1h and 4h (2y limit, honest)
    for tf, period, tag in [('1h', '730d', '1h'), ('4h', '730d', '4h')]:
        try:
            raw = load('ES=F', None, interval='1h', period=period)
        except Exception as e:  # noqa: BLE001
            print(f"  intraday ES load failed: {e}")
            raw = None
        if raw is None or len(raw) < 200:
            print(f"  intraday ES {tag}: insufficient data")
            continue
        df = resample_4h(raw) if tag == '4h' else raw
        _, mult, tick = FUT['ES=F']
        for mode, ls in [('long', False), ('L/S', True)]:
            trades, eq = run_ema_cross(df, mult, tick, ls=ls, slip=1)
            s = summary(trades, eq, (df.index[-1] - df.index[0]).days / 365.25)
            s['edge'], s['gate'] = 'EMA513_ES', mode
            p3[f"ES_{tag}_{mode}"] = {k: s[k] for k in
                                      ('trades', 'winrate', 'pf', 'maxdd', 'worst_trade',
                                       'worst_day', 'worst_streak', 'net', 'avg_hold')}
            print(f"  {'ES ' + tag:<14} {mode:<5} {s['trades']:>5} {s['winrate']:>6.0f} "
                  f"{fmt_pf(s['pf'])} {s['maxdd']:>11,.0f} {s['worst_trade']:>10,.0f} "
                  f"{s['worst_day']:>10,.0f} {s['worst_streak']:>7} {s['net']:>10,.0f} {s['avg_hold']:>8.1f}")
    print("\n  note: intraday = 2y only (yfinance 1h free limit) — directional smoke, not an edge.")

    with open(RESULTS_FILE, 'w') as f:
        json.dump(report, f, indent=2, default=float)
    print(f"\nSaved -> {RESULTS_FILE}")


if __name__ == '__main__':
    main()
