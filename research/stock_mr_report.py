"""Supplementary drawdown-first + concentration metrics for the stock-MR validation.

Recomputes the chosen config (thr=2 fixed) trades and adds:
  * worst / best single trades (identified)
  * per-symbol PF/win/n  -> concentration check
  * longest losing streak (consecutive losses by exit date)
  * compounded equal-weight portfolio equity curve -> interpretable maxDD%
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, "research")
import stock_mr_engine as E

PKL = "/tmp/stock_mr_ohlcv.pkl"


def load_symbols():
    df = pd.read_pickle(PKL)
    data = {}
    for sym, g in df.groupby(level=0):
        if g.index.nlevels > 1:
            g = g.droplevel(0)
        data[sym] = g
    return data


def trade_return(t, bps):
    return (t["exit_price"] * (1 - bps)) / (t["entry_price"] * (1 + bps)) - 1.0


def portfolio_maxdd(trades, data, bps):
    """Compounded equal-weight-across-open-positions daily portfolio. Returns maxDD%."""
    day_ret = defaultdict(list)
    for t in trades:
        d = data[t["symbol"]]
        c = d["close"].to_numpy()
        entry_adj = t["entry_price"] * (1 + bps)
        prev = entry_adj
        for i in range(t["entry_i"], t["exit_i"] + 1):
            px = t["exit_price"] * (1 - bps) if i == t["exit_i"] else c[i]
            day_ret[d.index[i]].append(px / prev - 1.0)
            prev = px
    V, peak, maxdd = 1.0, 1.0, 0.0
    for dt in sorted(day_ret):
        r = sum(day_ret[dt]) / len(day_ret[dt])
        V *= (1 + r)
        peak = max(peak, V)
        maxdd = min(maxdd, V / peak - 1.0)
    return float(maxdd), float(V)


def main():
    data = load_symbols()
    print(f"{len(data)} symbols")
    for thr in (2, 5):
        trades = []
        for sym, d in data.items():
            trades.extend(E.run_symbol(d, sym, thr, "fixed"))
        print(f"\n===== thr={thr} fixed: {len(trades)} trades =====")

        # worst / best trades
        rets = [(trade_return(t, 0.0005), t) for t in trades]
        rets.sort(key=lambda x: x[0])
        print("WORST 5 (5bps):")
        for r, t in rets[:5]:
            print(f"   {t['symbol']:6s} {str(t['entry_date'].date()):>11} -> {str(t['exit_date'].date()):>11} "
                  f"{t['reason']:6s} {r*100:7.2f}%")
        print("BEST 5 (5bps):")
        for r, t in rets[-5:]:
            print(f"   {t['symbol']:6s} {str(t['entry_date'].date()):>11} -> {str(t['exit_date'].date()):>11} "
                  f"{t['reason']:6s} {r*100:7.2f}%")

        # per-symbol concentration (5bps)
        by = defaultdict(list)
        for t in trades:
            by[t["symbol"]].append(trade_return(t, 0.0005))
        rows = []
        for sym, rs in by.items():
            rs = np.array(rs)
            wins = rs[rs > 0].sum(); losses = -rs[rs < 0].sum()
            pf = wins / losses if losses > 0 else float("inf")
            rows.append((sym, len(rs), pf, float((rs > 0).mean()), float(rs.sum())))
        rows.sort(key=lambda x: -x[2])
        print(f"\nper-symbol (5bps), {len(rows)} symbols:  sym  n  pf  win%  net(sum%)")
        pos, neg = 0, 0
        for sym, n, pf, w, net in rows:
            flag = "POS" if pf > 1.0 else "neg"
            if pf > 1.0:
                pos += 1
            else:
                neg += 1
            print(f"   {sym:6s} {n:4d} {pf:6.2f} {w*100:5.1f} {net*100:8.2f}  {flag}")
        print(f"   -> {pos} symbols PF>1, {neg} symbols PF<=1 (of {len(rows)} with trades)")

        # losing streak (by exit date, 0bps)
        ordered = sorted(trades, key=lambda t: t["exit_date"])
        streak = best = 0
        for t in ordered:
            if trade_return(t, 0.0) < 0:
                streak += 1
                best = max(best, streak)
            else:
                streak = 0
        print(f"\nlongest losing streak (0bps, exit-order): {best}")

        # portfolio maxDD
        for bps in (0.0, 0.0005, 0.0010):
            dd, V = portfolio_maxdd(trades, data, bps)
            print(f"portfolio maxDD @ {bps:.4f} = {dd*100:.2f}%   (end equity x{V:.2f})")


if __name__ == "__main__":
    main()
