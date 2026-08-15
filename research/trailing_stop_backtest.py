#!/usr/bin/env python3
"""TRAILING-STOP BACKTEST — fixed 2*ATR vs Chandelier(3*ATR) vs ATR-trail(2*ATR).

Owner directive: verify BEFORE changing a validated edge. Never apply blind.

Strategies (exact ports of bot/live.py daily index bots):
  DONCHIAN  : close > prior 20d-high -> LONG; exits = stop / 5d time / close <
              prior 20d-low.
  RSI2      : RSI(2) < 10 -> LONG (buy dip); exits = stop / 5d time / RSI(2) > 70.

Stop modes compared (all LONG, GTC intraday gap-aware):
  fixed      : 2*ATR below ENTRY (constant)  <-- CURRENT live.py behaviour.
  chandelier : 3*ATR below HIGHEST CLOSE since entry, ratcheted up (classic).
  atr_trail  : 2*ATR below PEAK (highest HIGH) since entry, ratcheted up.
  none       : (RSI2 reference only) no stop — the VALIDATED validate_edges.py
               model. Included to show what the never-lose-money stop itself
               changed vs the validated edge.

Honest fill model (same as research/validate_edges.py):
  - Entry at signal bar CLOSE + adverse slippage.
  - Stop GTC INTRADAY gap-aware: open<stop -> fill at open; elif low<=stop ->
    fill at stop. Both + slippage. Trailing stop is re-computed each bar from
    data through the PRIOR bar (no lookahead), ratchet-up only.
  - Close-based exits (time / signal) fill at close + slippage. One exit/bar.
Cost: fee 1.3bp round-trip notional (0bp ideal ref); slip 0/1/2/3 ticks/side.

Deliverable: PF / maxDD / net / win% / n / WORST single-trade loss — fixed vs
trailing, plus cost-stress and 40/20/40 OOS PF at 2-tick slip for the decision
rule (trailing must lower maxDD materially AND hold OOS PF >= ~1.4 @ 2-tick).
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
START = '2010-01-01'

SPECS = {
    'ES=F': ('ES E-mini S&P', 50.0, 0.25),
    'NQ=F': ('NQ E-mini Nasdaq', 20.0, 0.25),
    'YM=F': ('YM E-mini Dow', 5.0, 1.0),
}

FEE_BPS = 0.00013          # 1.3bp round-trip notional
SLIP_TICKS = [0, 1, 2, 3]

STOP_ATR = 2.0             # fixed / atr-trail distance
CHAND_ATR = 3.0            # chandelier distance
LOOKBACK = 20
MAX_HOLD = 5
RSI2_LO, RSI2_HI = 10.0, 70.0


# ---- indicators (identical to validate_edges.py / live.py) ----
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def load(tk):
    df = yf.download(tk, start=START, interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=['Open', 'High', 'Low', 'Close'])


# ---- unified long-only engine with pluggable stop ----
def run_strategy(df, strat, stop_mode, mult, tick, fee_bps=FEE_BPS, slip=0):
    """strat in {'DONCHIAN','RSI2'}; stop_mode in {'fixed','chandelier','atr_trail','none'}."""
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    if strat == 'DONCHIAN':
        don_hi = h.rolling(LOOKBACK).max().shift(1)
        don_lo = l.rolling(LOOKBACK).min().shift(1)
        warmup = LOOKBACK + 2
        def entry_cond(i):
            return not np.isnan(don_hi.iloc[i]) and c.iloc[i] > don_hi.iloc[i]
        def signal_exit_cond(i):
            return not np.isnan(don_lo.iloc[i]) and c.iloc[i] < don_lo.iloc[i]
    else:  # RSI2
        r2 = rsi(c, 2)
        warmup = 15  # enough for ATR(14) to be meaningful
        def entry_cond(i):
            return r2.iloc[i] < RSI2_LO
        def signal_exit_cond(i):
            return r2.iloc[i] > RSI2_HI

    trades, eq = [], []
    cash = 0.0
    pos = entry_px = 0.0
    entry_i = 0
    stop = peak_c = peak_h = 0.0
    stop_mult = CHAND_ATR if stop_mode == 'chandelier' else STOP_ATR

    for i in range(warmup, len(df)):
        oi, ci, bar_h, bar_l = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if entry_cond(i):
                entry_px = ci + slip * tick          # long pays up
                entry_i = i
                if stop_mode == 'none':
                    stop = -np.inf
                else:
                    stop = ci - stop_mult * atr.iloc[i]
                peak_c, peak_h = ci, bar_h
                pos = 1
        else:
            # ratchet the trailing stop from data through the PRIOR bar (no lookahead)
            if i - 1 >= entry_i and stop_mode in ('chandelier', 'atr_trail'):
                prev_c, prev_h, prev_atr = c.iloc[i - 1], h.iloc[i - 1], atr.iloc[i - 1]
                if stop_mode == 'atr_trail':
                    peak_h = max(peak_h, prev_h)
                    cand = peak_h - stop_mult * prev_atr
                else:  # chandelier
                    peak_c = max(peak_c, prev_c)
                    cand = peak_c - stop_mult * prev_atr
                if cand > stop:
                    stop = cand
            held = i - entry_i
            mae = l.iloc[entry_i:i + 1].min() - entry_px   # adverse (long)
            mfe = h.iloc[entry_i:i + 1].max() - entry_px
            exit_px = reason = None
            if stop_mode != 'none':                       # intraday GTC gap-aware stop
                if oi < stop:
                    exit_px, reason = oi - slip * tick, 'stop_gap'
                elif bar_l <= stop:
                    exit_px, reason = stop - slip * tick, 'stop'
            if exit_px is None and held >= MAX_HOLD:
                exit_px, reason = ci - slip * tick, 'time'
            if exit_px is None and signal_exit_cond(i):
                exit_px, reason = ci - slip * tick, 'signal'
            if exit_px is not None:
                fee = fee_bps * entry_px * mult
                pnl = (exit_px - entry_px) * mult - fee
                trades.append({'dir': 1, 'entry': entry_px, 'exit': exit_px,
                               'entry_i': int(entry_i), 'exit_i': i, 'reason': reason,
                               'pnl': pnl, 'days': int(i - entry_i),
                               'mae': mae, 'mfe': mfe})
                cash += pnl
                pos = 0
        eq.append(cash + (ci - entry_px) * mult if pos == 1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


# ---- metrics ----
def pf_of(trades):
    if not trades:
        return 0.0, 0
    p = np.array([t['pnl'] for t in trades])
    w, l = p[p > 0], p[p <= 0]
    pf = w.sum() / abs(l.sum()) if l.size and l.sum() != 0 else (float('inf') if w.size else 0.0)
    return float(pf), len(trades)


def summary(trades, eq):
    if not trades:
        return {'trades': 0, 'winrate': 0.0, 'pf': 0.0, 'net': 0.0, 'maxdd': 0.0,
                'worst_trade': 0.0, 'avg_trade': 0.0, 'avg_hold': 0.0}
    p = np.array([t['pnl'] for t in trades])
    wins = (p > 0).sum()
    pf, _ = pf_of(trades)
    dd = (eq - eq.cummax()).min()
    return {
        'trades': len(trades),
        'winrate': 100.0 * wins / len(trades),
        'pf': pf,
        'net': float(p.sum()),
        'maxdd': float(dd),
        'worst_trade': float(p.min()),
        'avg_trade': float(p.mean()),
        'avg_hold': float(np.mean([t['days'] for t in trades])),
    }


def oos_pf(df, strat, stop_mode, mult, tick, slip=2):
    """40/20/40 split: PF of the last-40% OOS trades at 2-tick slip."""
    n = len(df)
    warmup = LOOKBACK + 2 if strat == 'DONCHIAN' else 15
    oos_start = warmup + int((n - warmup) * 0.6)
    trades, _ = run_strategy(df, strat, stop_mode, mult, tick, slip=slip)
    oos = [t for t in trades if t['entry_i'] >= oos_start]
    return pf_of(oos)


MODES = ['fixed', 'chandelier', 'atr_trail'] + (['none'] if False else [])


def main():
    dfs = {}
    for tk in SPECS:
        try:
            dfs[tk] = load(tk)
        except Exception as e:  # noqa: BLE001
            print(f"SKIP {tk}: {e}")

    report = {'fee_bps': FEE_BPS, 'instruments': {}}

    for strat in ('DONCHIAN', 'RSI2'):
        modes = ['fixed', 'chandelier', 'atr_trail'] + (['none'] if strat == 'RSI2' else [])
        print(f"\n{'=' * 100}\n{strat}  (fee 1.3bp, slip 2 ticks/side — decision cost)\n{'=' * 100}")
        hdr = f"  {'instrument':<6} {'mode':<11} {'PF':>6} {'maxDD':>9} {'net':>9} {'win%':>5} {'n':>5} {'worstTrade':>11} {'avgHold':>8}"
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        pooled_fixed = None
        for tk, (name, mult, tick) in SPECS.items():
            df = dfs.get(tk)
            if df is None:
                continue
            report['instruments'].setdefault(tk, {})[strat] = {}
            for mode in modes:
                trades, eq = run_strategy(df, strat, mode, mult, tick, slip=2)
                s = summary(trades, eq)
                oos = oos_pf(df, strat, mode, mult, tick, slip=2)
                s['oos_pf'] = oos[0]
                s['oos_n'] = oos[1]
                # cost-stress PF (slip 0..3 @ 1.3bp)
                s['cost_pf'] = {}
                for sl in SLIP_TICKS:
                    t2, _ = run_strategy(df, strat, mode, mult, tick, slip=sl)
                    s['cost_pf'][sl] = pf_of(t2)[0]
                report['instruments'][tk][strat][mode] = s
                pfs = f"{s['pf']:6.2f}" if s['pf'] != float('inf') else "   inf"
                print(f"  {tk:<6} {mode:<11} {pfs} {s['maxdd']:>9,.0f} {s['net']:>9,.0f} "
                      f"{s['winrate']:>5.0f} {s['trades']:>5} {s['worst_trade']:>11,.0f} {s['avg_hold']:>8.1f}")

        # cost-stress PF grid (per mode, slip 0..3)
        print(f"\n  cost-stress PF @1.3bp (slip 0/1/2/3 ticks/side):")
        for mode in modes:
            row = []
            for tk, (_, mult, tick) in SPECS.items():
                if tk not in dfs:
                    continue
                s = report['instruments'][tk][strat][mode]
                row.append(f"{tk}:" + "/".join(
                    f"{s['cost_pf'][sl]:.2f}" if s['cost_pf'][sl] != float('inf') else 'inf'
                    for sl in SLIP_TICKS))
            print(f"    {mode:<11} " + "  ".join(row))

        print(f"\n  40/20/40 OOS PF @2-tick (last-40% by entry date):")
        for mode in modes:
            row = []
            for tk, (_, mult, tick) in SPECS.items():
                if tk not in dfs:
                    continue
                s = report['instruments'][tk][strat][mode]
                row.append(f"{tk}:{s['oos_pf']:.2f}(n={s['oos_n']})")
            print(f"    {mode:<11} " + "  ".join(row))

    out = os.path.join(HERE, 'trailing_stop_results.json')
    with open(out, 'w') as f:
        json.dump(report, f, indent=2, default=float)
    print(f"\nSaved -> {out}")


if __name__ == '__main__':
    main()
