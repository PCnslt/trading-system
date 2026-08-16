#!/usr/bin/env python3
"""Drawdown-first re-ranking of the intraday candidates (owner standard 2026-08-16).

The owner retired the PF-based promote bar as PRIMARY. The NEW ranking is:
  1. maxDrawdown (smaller = better)
  2. worst-case (largest single-trade loss)
  3. consistency (win rate + longest losing streak)
  secondary: PF, Sharpe, return.

Reuses the cached bars + strategy engines from intraday_validate.py. Reports
per-strategy (pooled across the liquid universe, in ticks) at two cost levels:
  1-tick/side + commission (realistic for MES/MNQ micros)
  3-tick/side + commission (the brutal stress)

READ-ONLY: no S3 writes, no orders.
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import research.intraday_validate as iv  # noqa: E402

LIQUID = iv.LIQUID


def worst_and_streak(net):
    """(worst single trade in ticks, longest losing streak)."""
    net = np.asarray(net)
    if len(net) == 0:
        return 0.0, 0
    worst = float(net.min())
    streak = cur = 0
    for v in net:
        if v <= 0:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0
    return worst, streak


def main():
    rows = []
    for name, meta in iv.STRATEGIES.items():
        tf = meta['tf']
        # accumulate pooled per-trade net ticks at each cost level
        for slip, label in [(1, '1t'), (3, '3t')]:
            nets = []
            trades = []
            for sym in LIQUID:
                df = iv.load_intraday(sym, tf)
                if df.empty:
                    continue
                tr = meta['fn'](df)
                if not tr:
                    continue
                nets.extend(iv.apply_cost(tr, iv.SPECS[sym], slip, True).tolist())
                trades.extend(tr)
            nets = np.array(nets)
            if len(nets) == 0:
                continue
            s = iv.summarize(nets, iv.daily_buckets(nets, trades))
            worst, streak = worst_and_streak(nets)
            rows.append(dict(strategy=name, cost=label, n=s['n'], win=round(s['win'], 1),
                             maxdd=round(s['maxdd'], 1), worst=round(worst, 1),
                             streak=streak, pf=round(s['pf'], 2),
                             sharpe=round(s['sharpe'], 2), net=round(s['net'], 1)))

    print(f"{'strategy':10s} {'cost':4s} {'n':>6s} {'win%':>6s} {'maxDD(t)':>10s} "
          f"{'worst(t)':>10s} {'streak':>7s} {'PF':>6s} {'Sharpe':>7s} {'net(t)':>9s}")
    for r in rows:
        print(f"{r['strategy']:10s} {r['cost']:4s} {r['n']:6d} {r['win']:6.1f} "
              f"{r['maxdd']:10.1f} {r['worst']:10.1f} {r['streak']:7d} "
              f"{r['pf']:6.2f} {r['sharpe']:7.2f} {r['net']:9.1f}")
    # drawdown-first ranking at 3t (the binding cost)
    r3 = [r for r in rows if r['cost'] == '3t']
    r3.sort(key=lambda r: (r['maxdd'], r['worst'], -r['win'], r['streak']))
    print("\nDrawdown-first rank @ 3-tick+comm (maxDD asc):")
    for i, r in enumerate(r3, 1):
        print(f"  {i}. {r['strategy']:10s} maxDD={r['maxdd']:9.1f}t worst={r['worst']:8.1f}t "
              f"win={r['win']:5.1f}% streak={r['streak']} PF={r['pf']}")


if __name__ == '__main__':
    main()
