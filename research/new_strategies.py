#!/usr/bin/env python3
"""NEW-STRATEGY SCREEN (Gate-1 first pass) — ~5 candidates, parallel to the
edge validation. Reuses indicators/metrics from validate_edges.py.

Candidates (chosen to be NEW vs the existing scans — Donchian/RSI2/MA/Bollinger
on equities are already covered):
  1. GAP_FADE        — fade large overnight gaps at the open, exit at close
                       (intraday mean-reversion of the overnight gap).
  2. NR7_BREAKOUT    — volatility expansion: NR7 (narrowest range of 7 days)
                       next-day breakout, 2*ATR GTC stop. Both directions.
  3. DONCHIAN_SHORT  — index SHORT Donchian (mirror of the live LONG edge);
                       answers whether the long-only bias is justified.
  4. OVERNIGHT_LONG  — hold long close->open (overnight risk premium), flat in
                       RTH. Session-decomposition check.
  5. BBAND_INDEX_LONG— Bollinger mean-reversion LONG on the index (buy below
                       lower band, exit at mid) — mirror of bonds BBANDSHORT.

Costs: fee 1.3 bps round-trip of notional + 0/1/2/3-tick slippage per side
(same as the edge validation). Fill at close/open + adverse slippage; stop
strategies use the intraday GTC model.

Survivor bar: OOS PF > 1.2 (last 40%), PF >= 1.0 at 2-tick slippage, and
>= 30 OOS trades (non-thin). Report only survivors + a summary table.
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.validate_edges import (  # noqa: E402
    wilder_atr, bollinger, SPECS, FEE_BPS, SLIP_TICKS, load_yfinance, pf_of,
)

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(HERE, 'new_strategies_results.json')
START = '2010-01-01'


# ======================================================================
# runners — each returns (trades, equity Series). trades have pnl/dir/entry_i/days.
# ======================================================================
def run_gap_fade(df, thresh=0.004, mult=50.0, tick=0.25, fee_bps=FEE_BPS, slip=0):
    o, c = df['Open'], df['Close']
    gap = o / c.shift() - 1.0
    trades, cash, eq = [], 0.0, []
    pos, entry_px, entry_i = 0, 0.0, 0
    for i in range(1, len(df)):
        oi, ci = o.iloc[i], c.iloc[i]
        if pos == 0:
            if not np.isnan(gap.iloc[i]) and gap.iloc[i] > thresh:
                pos, entry_px, entry_i = -1, oi - slip * tick, i
            elif not np.isnan(gap.iloc[i]) and gap.iloc[i] < -thresh:
                pos, entry_px, entry_i = 1, oi + slip * tick, i
        else:
            exit_px = ci + slip * tick if pos == -1 else ci - slip * tick
            fee = fee_bps * entry_px * mult
            trades.append({'pnl': (exit_px - entry_px) * pos * mult - fee, 'dir': pos,
                           'entry_i': entry_i, 'days': 0})
            cash += trades[-1]['pnl']
            pos = 0
        eq.append(cash)
    return trades, pd.Series(eq, index=df.index[1:])


def run_nr7_breakout(df, nr=7, stop_atr=2.0, max_hold=5, mult=50.0, tick=0.25,
                     fee_bps=FEE_BPS, slip=0):
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    rng = h - l
    atr = wilder_atr(h, l, c)
    trades, cash, eq = [], 0.0, []
    pos, entry_px, entry_i, stop = 0, 0.0, 0, 0.0
    for i in range(nr + 1, len(df)):
        oi, ci, hi, li = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        rng_win = rng.iloc[i - nr:i]
        is_nr7 = (rng.iloc[i - 1] == rng_win.min()) and rng_win.min() > 0
        if pos == 0:
            if is_nr7:
                if ci > h.iloc[i - 1]:
                    pos, entry_px, entry_i = 1, ci + slip * tick, i
                    stop = ci - stop_atr * atr.iloc[i]
                elif ci < l.iloc[i - 1]:
                    pos, entry_px, entry_i = -1, ci - slip * tick, i
                    stop = ci + stop_atr * atr.iloc[i]
        else:
            held = i - entry_i
            exit_px = reason = None
            if pos == 1:
                if oi < stop:
                    exit_px, reason = oi - slip * tick, 'stop_gap'
                elif li <= stop:
                    exit_px, reason = stop - slip * tick, 'stop'
            else:
                if oi > stop:
                    exit_px, reason = oi + slip * tick, 'stop_gap'
                elif hi >= stop:
                    exit_px, reason = stop + slip * tick, 'stop'
            if exit_px is None and held >= max_hold:
                exit_px = (ci - slip * tick) if pos == 1 else (ci + slip * tick)
                reason = 'time'
            if exit_px is not None:
                fee = fee_bps * entry_px * mult
                trades.append({'pnl': (exit_px - entry_px) * pos * mult - fee, 'dir': pos,
                               'entry_i': entry_i, 'days': held})
                cash += trades[-1]['pnl']
                pos = 0
        eq.append(cash + (ci - entry_px) * pos * mult if pos != 0 else cash)
    return trades, pd.Series(eq, index=df.index[nr + 1:])


def run_donchian_short(df, lookback=20, stop_atr=2.0, max_hold=5, mult=50.0, tick=0.25,
                       fee_bps=FEE_BPS, slip=0):
    c, h, l, o = df['Close'], df['High'], df['Low'], df['Open']
    atr = wilder_atr(h, l, c)
    don_hi = h.rolling(lookback).max().shift(1)
    don_lo = l.rolling(lookback).min().shift(1)
    trades, cash, eq = [], 0.0, []
    pos, entry_px, entry_i, stop = 0, 0.0, 0, 0.0
    for i in range(lookback + 2, len(df)):
        oi, ci, hi, li = o.iloc[i], c.iloc[i], h.iloc[i], l.iloc[i]
        if pos == 0:
            if not np.isnan(don_lo.iloc[i]) and ci < don_lo.iloc[i]:
                pos, entry_px, entry_i = -1, ci - slip * tick, i
                stop = ci + stop_atr * atr.iloc[i]
        else:
            held = i - entry_i
            exit_px = reason = None
            if oi > stop:
                exit_px, reason = oi + slip * tick, 'stop_gap'
            elif hi >= stop:
                exit_px, reason = stop + slip * tick, 'stop'
            if exit_px is None and held >= max_hold:
                exit_px, reason = ci + slip * tick, 'time'
            if exit_px is None and not np.isnan(don_hi.iloc[i]) and ci > don_hi.iloc[i]:
                exit_px, reason = ci + slip * tick, 'breakout'
            if exit_px is not None:
                fee = fee_bps * entry_px * mult
                trades.append({'pnl': (entry_px - exit_px) * mult - fee, 'dir': -1,
                               'entry_i': entry_i, 'days': held})
                cash += trades[-1]['pnl']
                pos = 0
        eq.append(cash + (entry_px - ci) * mult if pos == -1 else cash)
    return trades, pd.Series(eq, index=df.index[lookback + 2:])


def run_overnight_long(df, mult=50.0, tick=0.25, fee_bps=FEE_BPS, slip=0):
    c, o = df['Close'], df['Open']
    trades, cash, eq = [], 0.0, []
    for i in range(1, len(df)):
        entry_px = c.iloc[i - 1] + slip * tick
        exit_px = o.iloc[i] - slip * tick
        fee = fee_bps * entry_px * mult
        trades.append({'pnl': (exit_px - entry_px) * mult - fee, 'dir': 1,
                       'entry_i': i - 1, 'days': 1})
        cash += trades[-1]['pnl']
        eq.append(cash)
    return trades, pd.Series(eq, index=df.index[1:])


def run_bband_long_index(df, n=20, k=2.0, max_hold=5, mult=50.0, tick=0.25,
                         fee_bps=FEE_BPS, slip=0):
    c, h, l = df['Close'], df['High'], df['Low']
    mid, upper, lower = bollinger(c, n, k)
    trades, cash, eq = [], 0.0, []
    pos, entry_px, entry_i = 0, 0.0, 0
    for i in range(n + 2, len(df)):
        ci = c.iloc[i]
        if pos == 0:
            if not np.isnan(lower.iloc[i]) and ci < lower.iloc[i]:
                pos, entry_px, entry_i = 1, ci + slip * tick, i
        else:
            held = i - entry_i
            if held >= max_hold or ci >= mid.iloc[i]:
                reason = 'time' if held >= max_hold else 'signal'
                exit_px = ci - slip * tick
                fee = fee_bps * entry_px * mult
                trades.append({'pnl': (exit_px - entry_px) * mult - fee, 'dir': 1,
                               'entry_i': entry_i, 'days': held})
                cash += trades[-1]['pnl']
                pos = 0
        eq.append(cash + (ci - entry_px) * mult if pos == 1 else cash)
    return trades, pd.Series(eq, index=df.index[n + 2:])


CANDIDATES = [
    ('GAP_FADE',       run_gap_fade,       ['ES=F', 'NQ=F'], {}),
    ('NR7_BREAKOUT',   run_nr7_breakout,   ['ES=F', 'NQ=F'], {}),
    ('DONCHIAN_SHORT', run_donchian_short, ['ES=F', 'NQ=F', 'YM=F'], {}),
    ('OVERNIGHT_LONG', run_overnight_long, ['ES=F', 'NQ=F', 'YM=F'], {}),
    ('BBAND_INDEX_LONG', run_bband_long_index, ['ES=F', 'NQ=F'], {}),
]


# ======================================================================
# screen metrics + OOS split
# ======================================================================
def screen_metrics(trades, eq, n_years):
    if not trades:
        return {'trades': 0, 'winrate': 0.0, 'pf': 0.0, 'net': 0.0, 'maxdd': 0.0,
                'turnover': 0.0, 'avg_hold': 0.0}
    pnls = np.array([t['pnl'] for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.size and losses.sum() != 0 else float('inf')
    maxdd = (eq - eq.cummax()).min()
    return {
        'trades': len(trades),
        'winrate': 100.0 * wins.size / len(trades),
        'pf': float(pf),
        'net': float(pnls.sum()),
        'maxdd': float(maxdd),
        'turnover': float(len(trades) / n_years),
        'avg_hold': float(np.mean([t['days'] for t in trades])),
    }


def oos_buckets(trades, n, warmup=25):
    a = warmup + int((n - warmup) * 0.4)
    b = warmup + int((n - warmup) * 0.6)
    train = [t for t in trades if t['entry_i'] < a]
    val = [t for t in trades if a <= t['entry_i'] < b]
    oos = [t for t in trades if t['entry_i'] >= b]
    return train, val, oos


def fmt_pf(pf):
    return ' inf' if pf == float('inf') else f'{pf:6.2f}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    args = ap.parse_args()

    print(f"NEW-STRATEGY SCREEN — fee={FEE_BPS:.5f} (1.3bp), slippage 0/1/2/3 ticks/side")
    print("=" * 100)

    cands = CANDIDATES[:2] if args.quick else CANDIDATES
    tickers = sorted({tk for _, _, tks, _ in cands for tk in tks})
    dfs, failed = {}, []
    for tk in tickers:
        try:
            df = load_yfinance(tk)
            if df is None or len(df) < 260:
                failed.append((tk, 'insufficient'))
            else:
                dfs[tk] = df
        except Exception as e:  # noqa: BLE001
            failed.append((tk, f'{type(e).__name__}: {e}'))
    if failed:
        print("SKIPPED:", failed, "\n")

    report = {'fee_bps': FEE_BPS, 'failed': failed, 'candidates': {}}
    survivors = []

    for name, fn, tks, params in cands:
        rep = tks[0]
        if rep not in dfs:
            continue
        _, mult, tick, _, _ = SPECS[rep]
        # pooled full-sample (all instruments, baseline)
        pooled = []
        for tk in tks:
            if tk not in dfs:
                continue
            _, m, ti, _, _ = SPECS[tk]
            tr, _ = fn(dfs[tk], mult=m, tick=ti, **params)
            pooled.extend(tr)
        pool_pf, pool_n = pf_of(pooled)

        # full metrics on the representative instrument
        tr, eq = fn(dfs[rep], mult=mult, tick=tick, **params)
        n_years = (dfs[rep].index[-1] - dfs[rep].index[0]).days / 365.25
        m = screen_metrics(tr, eq, n_years)

        # OOS (last 40%)
        train, val, oos = oos_buckets(tr, len(dfs[rep]))
        oos_pf, oos_n = pf_of(oos)
        val_pf, val_n = pf_of(val)

        # cost stress on representative instrument
        cost = {}
        for s in SLIP_TICKS:
            tr_s, _ = fn(dfs[rep], mult=mult, tick=tick, slip=s, **params)
            cpf, _ = pf_of(tr_s)
            cost[f'slip{s}'] = cpf

        rec = {
            'pooled_pf': pool_pf, 'pooled_trades': pool_n,
            'full_pf': m['pf'], 'net': m['net'], 'maxdd': m['maxdd'],
            'trades': m['trades'], 'winrate': m['winrate'], 'turnover': m['turnover'],
            'avg_hold': m['avg_hold'],
            'oos_pf': oos_pf, 'oos_trades': oos_n, 'val_pf': val_pf, 'val_trades': val_n,
            'cost_stress': cost,
        }
        report['candidates'][name] = rec

        c2 = cost.get('slip2', 0.0)
        survive = oos_pf > 1.2 and c2 >= 1.0 and oos_n >= 30
        if survive:
            survivors.append(name)

        print(f"[{name}] trades={m['trades']} win={m['winrate']:.0f}% fullPF={fmt_pf(m['pf'])} "
              f"net=${m['net']:,.0f} maxDD=${m['maxdd']:,.0f} turn={m['turnover']:.0f}/yr hold={m['avg_hold']:.1f}d")
        print(f"         pooled={fmt_pf(pool_pf)}(n={pool_n}) | OOS={fmt_pf(oos_pf)}(n={oos_n}) "
              f"validate={fmt_pf(val_pf)}(n={val_n})")
        print(f"         cost PF: " + "  ".join(f"s{s}={fmt_pf(cost[f'slip{s}'])}" for s in SLIP_TICKS)
              + f"   -> {'SURVIVOR' if survive else 'reject'}")
        print()

    print("=" * 100)
    print(f"SURVIVORS (OOS PF>1.2, 2-tick PF>=1.0, n>=30): {survivors if survivors else 'none'}")
    report['survivors'] = survivors

    with open(RESULTS_FILE, 'w') as f:
        json.dump(report, f, indent=2, default=float)
    print(f"Saved -> {RESULTS_FILE}")
    try:
        from data.s3_archive import archive_scan_results
        archive_scan_results('new-strategies', report)
        print("Archived to S3 research/scan-results/new-strategies/")
    except Exception as e:  # noqa: BLE001
        print(f"S3 archive failed: {e}")


if __name__ == '__main__':
    main()
