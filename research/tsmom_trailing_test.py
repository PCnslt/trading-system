#!/usr/bin/env python3
"""TSMOM (12-month time-series momentum) trailing-stop test — GOLD.

Owner directive: verify trailing-stop benefit BEFORE applying. TSMOM is the one
strategy not covered by research/trailing_stop_backtest.py (which covers index
Donchian + RSI2). TSMOM is trend-following (long 12m momentum), so the Donchian
result (chandelier helps) *should* transfer — but TSMOM holds for 12+ months, so
a 3*ATR chandelier exits far earlier than the 12m sign-flip and may cut the trend.
Test it rather than assume.

Strategy: LONG when close > close 252 bars ago (12m), exit on sign flip.
Stop modes: fixed 3*ATR (current) vs chandelier 3*ATR (ratchet) vs none.
Honest fills: entry at signal close + 2-tick slip; GTC stop gap-aware
(open<stop -> open; low<=stop -> stop), + slip. Fee 1.3bp round-trip.
"""
import numpy as np
import pandas as pd
import yfinance as yf

TICK = 0.1        # GC tick = $0.10/oz
MULT = 100.0      # GC = 100 oz/contract
FEE_BPS = 0.00013
SLIP = 2          # ticks
STOP_ATR = 3.0
LOOK = 252        # 12-month lookback


def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def run(df, stop_mode):
    h = df['High'].squeeze()
    l = df['Low'].squeeze()
    c = df['Close'].squeeze()
    o = df['Open'].squeeze()
    atr = wilder_atr(h, l, c)
    mom = c / c.shift(LOOK) - 1.0
    long_sig = (mom > 0).astype(int)
    n = len(df)
    pos = 0
    entry = 0.0
    peak = 0.0
    stop = 0.0
    trades = []
    for i in range(LOOK + 15, n):
        px_close = c.iloc[i]
        if pos == 0:
            if long_sig.iloc[i] == 1 and long_sig.iloc[i - 1] == 0:
                entry = px_close + SLIP * TICK
                pos = 1
                peak = px_close
                stop = entry - STOP_ATR * atr.iloc[i]
        else:
            # update chandelier peak/trail (gap-aware, ratchet only)
            peak = max(peak, h.iloc[i - 1])
            if stop_mode == 'chandelier':
                trail = peak - STOP_ATR * atr.iloc[i]
                stop = max(stop, trail)
            # intraday stop check (gap-aware)
            exit_px = None
            if stop_mode != 'none':
                o_bar, lo = o.iloc[i], l.iloc[i]
                if o_bar <= stop:
                    exit_px = o_bar - SLIP * TICK
                elif lo <= stop:
                    exit_px = stop - SLIP * TICK
            if exit_px is not None:
                pnl = (exit_px - entry) * MULT - FEE_BPS * (entry + exit_px) * MULT
                trades.append(pnl)
                pos = 0
                continue
            # signal exit (12m sign flip) at close
            if long_sig.iloc[i] == 0:
                exit_px = px_close - SLIP * TICK
                pnl = (exit_px - entry) * MULT - FEE_BPS * (entry + exit_px) * MULT
                trades.append(pnl)
                pos = 0
    return trades


def stats(trades):
    if not trades:
        return None
    p = np.array(trades)
    wins = p[p > 0]
    losses = p[p <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float('inf')
    eq = np.cumsum(p)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    return {'n': len(p), 'pf': round(pf, 2), 'win%': round(100 * len(wins) / len(p)),
            'maxDD': round(float(dd.min()), 0), 'worst': round(float(p.min()), 0),
            'net': round(float(p.sum()), 0)}


if __name__ == '__main__':
    print('loading GC=F ...')
    df = yf.download('GC=F', start='2000-01-01', auto_adjust=False, progress=False)
    print(f'bars: {len(df)} ({df.index[0].date()} -> {df.index[-1].date()})')
    for mode in ['fixed', 'chandelier', 'none']:
        tr = run(df, mode)
        s = stats(tr)
        print(f"TSMOM {mode:11} -> {s}")
