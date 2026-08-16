#!/usr/bin/env python3
"""RSI(2) entry-refinement test: no-trend-filter vs Connors 200d-SMA filter.

Task (laptop Hermes): compare our current RSI(2) buy-the-dip (RSI(2)<10, NO
trend filter) against Connors' ORIGINAL rule (RSI(2)<10 AND close > 200-day
SMA) on ES/NQ daily, same cost model (3-tick + 1.3bp commission) and the same
walk-forward split used by validate_edges.py. Decide adopt-vs-keep.

Method: reuse validate_edges' run_rsi2_long exactly (same engine, exits, cost
model, fold logic); the ONLY delta is an added `sma200_filter` gate on entry.
No-filter uses warmup=3 (== run_rsi2_long baseline); filtered uses warmup=203
(SMA200 needs 200 bars). The OOS (last-40%) bucket starts ~bar 2300 so it is
warmup-invariant — OOS PF and cost-stress are directly comparable.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_edges import (  # noqa: E402
    FEE_BPS, SLIP_TICKS, bucket_trades, load_yfinance, metrics, pf_of, rsi,
    trade_record, wilder_atr,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'rsi2_sma200_results.json')


def run_rsi2(df, lo=10.0, hi=70.0, max_hold=5, mult=50.0, tick=0.25,
             fee_bps=FEE_BPS, slip=0, sma200_filter=False):
    """LONG-only RSI(2) buy-the-dip. Optional Connors 200d-SMA trend gate."""
    c, h, l = df['Close'], df['High'], df['Low']
    r2 = rsi(c, 2)
    sma200 = c.rolling(200).mean() if sma200_filter else None
    warmup = 203 if sma200_filter else 3
    trades, eq = [], []
    pos, entry_px, entry_i = 0, 0.0, 0
    cash = 0.0
    for i in range(warmup, len(df)):
        ci = c.iloc[i]
        if pos == 0:
            trig = r2.iloc[i] < lo
            if sma200_filter:
                trig = trig and not np.isnan(sma200.iloc[i]) and ci > sma200.iloc[i]
            if trig:
                entry_px, entry_i = ci + slip * tick, i
                pos = 1
        else:
            held = i - entry_i
            mae = (l.iloc[entry_i:i + 1].min() - entry_px)
            mfe = (h.iloc[entry_i:i + 1].max() - entry_px)
            if held >= max_hold or r2.iloc[i] > hi:
                reason = 'time' if held >= max_hold else 'signal'
                fee = fee_bps * entry_px * mult
                trades.append(trade_record(entry_px, entry_i, ci - slip * tick, i, 1,
                                           reason, mult, fee, mae, mfe))
                cash += trades[-1]['pnl']
                pos = 0
        eq.append(cash + (ci - entry_px) * mult if pos == 1 else cash)
    return trades, pd.Series(eq, index=df.index[warmup:])


def split_40_20_40(df, trades):
    n = len(df)
    warmup = 25
    a = warmup + int((n - warmup) * 0.4)
    b = warmup + int((n - warmup) * 0.6)
    edges = [(warmup, a, 'train'), (a, b, 'validate'), (b, n, 'oos')]
    buckets = bucket_trades(trades, df.index, edges)
    return {lbl: {'pf': pf_of(buckets[lbl])[0], 'trades': pf_of(buckets[lbl])[1]}
            for lbl in ('train', 'validate', 'oos')}


def wf_folds(df, trades, folds=3):
    n = len(df)
    warmup = 25
    edge_idx = [warmup] + [warmup + int((n - warmup) * f / folds) for f in range(1, folds)] + [n]
    fold_edges = [(edge_idx[i], edge_idx[i + 1], f'fold{i+1}') for i in range(folds)]
    buckets = bucket_trades(trades, df.index, fold_edges)
    return {f'fold{i+1}': {'pf': pf_of(buckets[f'fold{i+1}'])[0],
                            'trades': pf_of(buckets[f'fold{i+1}'])[1]}
            for i in range(folds)}


def variant_report(df, mult, tick, sma200_filter):
    ny = (df.index[-1] - df.index[0]).days / 365.25
    out = {}
    # baseline cost (1.3bp fee, 0 slip)
    trades, eq = run_rsi2(df, mult=mult, tick=tick, sma200_filter=sma200_filter)
    m = metrics(trades, eq, ny)
    out['full'] = {k: m[k] for k in ('trades', 'winrate', 'pf', 'net', 'maxdd',
                                     'avg_trade', 'avg_hold', 'worst_streak',
                                     'turnover', 'mae', 'mfe')}
    out['split_40_20_40'] = split_40_20_40(df, trades)
    out['walk_forward'] = wf_folds(df, trades)
    # 3-tick + commission cost cell (the task's cost model)
    t3, eq3 = run_rsi2(df, mult=mult, tick=tick, slip=3, sma200_filter=sma200_filter)
    m3 = metrics(t3, eq3, ny)
    out['cost_3tick'] = {k: m3[k] for k in ('trades', 'winrate', 'pf', 'net', 'maxdd')}
    out['oos_3tick'] = split_40_20_40(df, t3)['oos']
    return out, trades, t3


SPECS = {'ES=F': ('ES', 50.0, 0.25), 'NQ=F': ('NQ', 20.0, 0.25)}


def main():
    report = {'fee_bps': FEE_BPS, 'slip_ticks': 3, 'symbols': {}}
    pooled = {'no_filter': [], 'sma200': []}
    for tk, (name, mult, tick) in SPECS.items():
        df = load_yfinance(tk)
        print(f"\n{'='*100}\n{name} ({tk})  n_bars={len(df)}  "
              f"{df.index[0].date()} -> {df.index[-1].date()}\n{'='*100}")
        report['symbols'][tk] = {}
        for label, filt in (('no_filter', False), ('sma200', True)):
            rep, trades, t3 = variant_report(df, mult, tick, filt)
            report['symbols'][tk][label] = rep
            pooled[label].extend(t3)  # 3-tick trades for pooled headline
            f = rep['full']; s = rep['split_40_20_40']; c = rep['cost_3tick']
            print(f"\n  [{label}]  trades={f['trades']} win={f['winrate']:.0f}% "
                  f"PF={f['pf']:.2f} net=${f['net']:,.0f} maxDD=${f['maxdd']:,.0f} "
                  f"streak={f['worst_streak']} hold={f['avg_hold']:.1f}d turn={f['turnover']:.0f}/yr")
            print(f"         40/20/40: train {s['train']['pf']:.2f}/{s['train']['trades']}  "
                  f"validate {s['validate']['pf']:.2f}/{s['validate']['trades']}  "
                  f"OOS {s['oos']['pf']:.2f}/{s['oos']['trades']}")
            wf = rep['walk_forward']
            print(f"         folds: " + "  ".join(
                f"{k}={wf[k]['pf']:.2f}({wf[k]['trades']})" for k in wf))
            print(f"         3-tick+comm: PF={c['pf']:.2f} maxDD=${c['maxdd']:,.0f} "
                  f"net=${c['net']:,.0f} (n={c['trades']})  "
                  f"OOS@3tick PF={rep['oos_3tick']['pf']:.2f}/{rep['oos_3tick']['trades']}")

    # pooled ES+NQ headline (3-tick cost model)
    print(f"\n{'='*100}\nPOOLED ES+NQ (3-tick + 1.3bp commission)\n{'='*100}")
    report['pooled_3tick'] = {}
    for label in ('no_filter', 'sma200'):
        tr = pooled[label]
        pf, n = pf_of(tr)
        wr = 100.0 * np.mean([t['pnl'] > 0 for t in tr]) if tr else 0.0
        pnls = np.array([t['pnl'] for t in tr])
        net = pnls.sum()
        report['pooled_3tick'][label] = {'pf': pf, 'trades': n, 'winrate': wr, 'net': net}
        print(f"  [{label}]  PF={pf:.2f}  win={wr:.0f}%  net=${net:,.0f}  trades={n}")

    with open(OUT, 'w') as fh:
        json.dump(report, fh, indent=2, default=float)
    print(f"\nSaved -> {OUT}")


if __name__ == '__main__':
    main()
