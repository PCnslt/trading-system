"""Small-capital equities sweep — gap strategies, short-term momentum, pairs/stat-arb.

Universe: 50 S&P100 large-caps (top-50 by 20d avg dollar volume, deterministic
liquidity rule — see stock_mr_fetch.py). Data: /tmp/stock_mr_ohlcv.pkl
(split+dividend-adjusted daily OHLCV, yfinance, deep history).

Honest fill model (repo standard):
  * Entry at signal bar CLOSE+slip or next-bar OPEN+slip (per strategy).
  * Exits at close - slip; GTC stop intraday gap-aware.
  * Cost post-applied: bps-per-side {0,5,10} + cents/share {0,1,2,3}.
  * Fractional returns pooled equal-weight per trade.

Strategies (all long-only except pairs, which are market-neutral long/short):
  1. GAP_FADE  : open gaps DOWN >= -2% vs prior close -> buy open, exit close +k days
  2. GAP_GO    : open gaps UP   >= +2% -> buy open, exit close +k days
  3. DONCH20   : 20d high breakout (close>prior 20d high, close>SMA200) long,
                 2*ATR GTC stop, exit < 20d low or 5d time stop
  4. MOM5      : 5-day time-series momentum: 5d return > 0 -> long 5d (close-based)
  5. PAIRS     : z-score(2) mean-reversion on log-price spread of fixed liquid pairs
Output: /home/ubuntu/trading-system/research/smallcap_sweep_results.json
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

import numpy as np
import pandas as pd

PKL = "/tmp/stock_mr_ohlcv.pkl"
OUT = "/home/ubuntu/trading-system/research/smallcap_sweep_results.json"
BPS = (0.0, 0.0005, 0.0010)      # per side
CENTS = (0, 1, 2, 3)             # per side
GAP_THR = 0.02
GAP_HORIZONS = (0, 1, 3, 5)      # exit at close of day entry+k (k=0 => same-day close)


# ---------- shared metrics ----------

def pf_win(rets):
    rets = np.asarray(rets, dtype=float)
    if len(rets) == 0:
        return float("nan"), float("nan"), 0
    wins = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    return float(pf), float((rets > 0).mean()), int(len(rets))


def net_ret(ret, bps, cents, entry, exit_):
    """fractional net return after bps-per-side and cents-per-share-per-side cost."""
    r = (exit_ * (1 - bps)) / (entry * (1 + bps)) - 1.0
    r -= (cents * 2 / 100.0) / entry   # 2 sides * cents (in dollars/share)
    return r


def maxdd_daily(daily_pnl):
    if not daily_pnl:
        return float("nan")
    eq = pd.Series(daily_pnl).sort_index().cumsum()
    return float((eq - eq.cummax()).min())


def summarize(trades, close_by_sym, bps, cents):
    """trades = list of dicts with entry/exit price, entry_i, exit_i, symbol, entry_date."""
    if not trades:
        return None
    rets, daily = [], defaultdict(float)
    for t in trades:
        r = (t["exit_price"] * (1 - bps)) / (t["entry_price"] * (1 + bps)) - 1.0
        r -= (cents * 2 / 100.0) / t["entry_price"]   # cents -> dollars/share, 2 sides
        rets.append(r)
        # daily mark-to-market (equal $1 per trade), use raw prices for curve shape
        closes = close_by_sym[t["symbol"]]
        entry_adj = t["entry_price"] * (1 + bps)
        for i in range(t["entry_i"], t["exit_i"] + 1):
            px = (t["exit_price"] * (1 - bps)) if i == t["exit_i"] else closes[i]
            daily[i] += px / entry_adj - 1.0
    rets = np.asarray(rets)
    pf, win, n = pf_win(rets)
    holds = np.array([t["exit_i"] - t["entry_i"] for t in trades], dtype=float)
    return {
        "n": n, "pf": pf, "win": win,
        "avg_hold": float(holds.mean()),
        "net": float(rets.sum()),          # sum of per-trade fractional returns
        "worst": float(rets.min()), "best": float(rets.max()),
        "maxdd_frac": maxdd_daily(daily),
    }


def load():
    df = pd.read_pickle(PKL)
    data = {}
    for sym, g in df.groupby(level=0):
        if g.index.nlevels > 1:
            g = g.droplevel(0)
        data[sym] = g
    return data


def indicators(d):
    d = d.copy()
    c = d["close"]
    d["sma200"] = c.rolling(200).mean()
    d["sma5"] = c.rolling(5).mean()
    # prior 20d high/low (shifted, excludes today)
    d["hi20"] = d["high"].rolling(20).max().shift(1)
    d["lo20"] = d["low"].rolling(20).min().shift(1)
    # ATR14 (Wilder)
    pc = c.shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()],
                   axis=1).max(axis=1)
    d["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    return d


# ---------- 1. gap strategies ----------

def run_gap(data, direction, k):
    """direction 'down' (buy gap-down fade) or 'up' (buy gap-up go). exit close+k."""
    trades = []
    for sym, df in data.items():
        o = df["open"].to_numpy()
        c = df["close"].to_numpy()
        for i in range(1, len(df) - k):
            gap = o[i] / c[i - 1] - 1.0
            if direction == "down" and gap <= -GAP_THR:
                entry = o[i]
            elif direction == "up" and gap >= GAP_THR:
                entry = o[i]
            else:
                continue
            ex = i + k
            trades.append({"symbol": sym, "entry_price": float(entry),
                           "exit_price": float(c[ex]), "entry_i": i, "exit_i": ex,
                           "entry_date": df.index[i]})
    return trades


# ---------- 2. Donchian 20d breakout (individual, SMA200 gate) ----------

def run_donch(data):
    trades = []
    for sym, df in data.items():
        d = indicators(df)
        o = d["open"].to_numpy(); h = d["high"].to_numpy(); l = d["low"].to_numpy()
        c = d["close"].to_numpy(); sma = d["sma200"].to_numpy()
        hi20 = d["hi20"].to_numpy(); lo20 = d["lo20"].to_numpy(); atr = d["atr14"].to_numpy()
        n = len(d)
        i = 200
        while i < n - 1:
            # flat: check breakout signal at bar i close, enter bar i+1 open
            if c[i] > hi20[i] and c[i] > sma[i] and not np.isnan(sma[i]) and not np.isnan(hi20[i]):
                entry_i = i + 1
                entry = o[entry_i]
                stop = entry - 2 * atr[i]
                ex = None; reason = "end"
                for j in range(entry_i, n):
                    if l[j] <= stop:
                        ex = (j, o[j] if o[j] < stop else stop); reason = "stop"; break
                    if j - entry_i >= 5:
                        ex = (j, c[j]); reason = "time"; break
                    if c[j] < lo20[j]:
                        ex = (j, c[j]); reason = "signal"; break
                if ex is None:
                    ex = (n - 1, c[n - 1])
                trades.append({"symbol": sym, "entry_price": float(entry),
                               "exit_price": float(ex[1]), "entry_i": entry_i,
                               "exit_i": ex[0], "entry_date": d.index[entry_i],
                               "reason": reason})
                i = ex[0] + 1
                continue
            i += 1
    return trades


# ---------- 3. 5-day time-series momentum (close-based) ----------

def run_mom5(data):
    trades = []
    for sym, df in data.items():
        c = df["close"].to_numpy()
        n = len(df)
        i = 5
        while i < n - 6:
            r5 = c[i] / c[i - 5] - 1.0
            if r5 > 0:
                entry_i = i + 1
                exit_i = entry_i + 5
                trades.append({"symbol": sym, "entry_price": float(c[entry_i]),
                               "exit_price": float(c[exit_i]), "entry_i": entry_i,
                               "exit_i": exit_i, "entry_date": df.index[entry_i]})
                i = exit_i + 1
            else:
                i += 1
    return trades


# ---------- 4. pairs (z-score spread mean-reversion, market-neutral) ----------

PAIRS = [("MA", "V"), ("CVX", "XOM"), ("JPM", "BAC"), ("BAC", "C"),
         ("JPM", "GS"), ("NVDA", "AMD"), ("MSFT", "ORCL"), ("QCOM", "TXN"),
         ("AMAT", "LRCX"), ("AVGO", "AMD")]


def run_pairs(data):
    """z-score(2) entry on log-price spread, exit |z|<0.5 or 20d time stop.
    Long the spread = long A short B when z<-2; short spread when z>2.
    Return per-leg P&L in fractional terms summed (approx market-neutral)."""
    trades = []
    for a, b in PAIRS:
        if a not in data or b not in data:
            continue
        da, db = data[a], data[b]
        # align on common index
        common = da.index.intersection(db.index)
        da = da.loc[common]; db = db.loc[common]
        if len(da) < 400:
            continue
        ca = np.log(da["close"].to_numpy()); cb = np.log(db["close"].to_numpy())
        spread = ca - cb
        win = 60
        z = pd.Series(spread).rolling(win).apply(
            lambda x: (x[-1] - x.mean()) / (x.std() + 1e-12), raw=True).to_numpy()
        n = len(spread)
        i = win
        while i < n - 1:
            if not np.isnan(z[i]) and abs(z[i]) >= 2.0:
                # entry next open: long spread (z<-2) => long A, short B
                entry_i = i + 1
                long_spread = z[i] < 0
                leg_a = da["open"].to_numpy()[entry_i]
                leg_b = db["open"].to_numpy()[entry_i]
                ex = None
                for j in range(entry_i, n):
                    if j - entry_i >= 20:
                        ex = j; break
                    if abs(z[j]) < 0.5:
                        ex = j; break
                if ex is None:
                    ex = n - 1
                ex_a = da["close"].to_numpy()[ex]; ex_b = db["close"].to_numpy()[ex]
                if long_spread:
                    # long A, short B
                    r = (ex_a / leg_a - 1.0) - (ex_b / leg_b - 1.0)
                else:
                    r = -(ex_a / leg_a - 1.0) + (ex_b / leg_b - 1.0)
                trades.append({"symbol": f"{a}/{b}", "entry_price": 1.0,
                               "exit_price": 1.0 + r, "entry_i": entry_i,
                               "exit_i": ex, "entry_date": da.index[entry_i],
                               "ret": float(r), "pair": True})
                i = ex + 1
            else:
                i += 1
    return trades


def pairs_summary(trades, bps, cents):
    """Pairs trades already carry fractional spread return in 'ret'; apply cost as
    ~4 sides of bps (2 legs x 2 sides) — conservative."""
    if not trades:
        return None
    rets = np.array([t["ret"] - 4 * bps for t in trades])
    pf, win, n = pf_win(rets)
    holds = np.array([t["exit_i"] - t["entry_i"] for t in trades], dtype=float)
    return {"n": n, "pf": pf, "win": win, "avg_hold": float(holds.mean()),
            "net": float(rets.sum()), "worst": float(rets.min()),
            "best": float(rets.max()), "note": "market-neutral spread return; shorting required"}


def main():
    t0 = time.time()
    data = load()
    print(f"loaded {len(data)} symbols", flush=True)
    close_by_sym = {s: d["close"].to_numpy() for s, d in data.items()}

    res = {"universe": sorted(data.keys()), "universe_n": len(data),
           "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    # gap strategies
    res["gap"] = {}
    for direction in ("down", "up"):
        for k in GAP_HORIZONS:
            tr = run_gap(data, direction, k)
            key = f"{direction}_k{k}"
            res["gap"][key] = {"n_raw": len(tr)}
            for bps in BPS:
                s = summarize(tr, close_by_sym, bps, 0)
                res["gap"][key][f"bps{int(bps*1e4)}"] = s if s else {"n": 0}
            for cents in CENTS:
                s = summarize(tr, close_by_sym, 0.0, cents)
                res["gap"][key][f"c{cents}"] = s if s else {"n": 0}
            print(f"gap {key}: n={len(tr)} ({time.time()-t0:.0f}s)", flush=True)

    # Donchian
    tr = run_donch(data)
    res["donch20"] = {"n_raw": len(tr)}
    for bps in BPS:
        res["donch20"][f"bps{int(bps*1e4)}"] = summarize(tr, close_by_sym, bps, 0) or {"n": 0}
    for cents in CENTS:
        res["donch20"][f"c{cents}"] = summarize(tr, close_by_sym, 0.0, cents) or {"n": 0}
    print(f"donch20: n={len(tr)} ({time.time()-t0:.0f}s)", flush=True)

    # mom5
    tr = run_mom5(data)
    res["mom5"] = {"n_raw": len(tr)}
    for bps in BPS:
        res["mom5"][f"bps{int(bps*1e4)}"] = summarize(tr, close_by_sym, bps, 0) or {"n": 0}
    for cents in CENTS:
        res["mom5"][f"c{cents}"] = summarize(tr, close_by_sym, 0.0, cents) or {"n": 0}
    print(f"mom5: n={len(tr)} ({time.time()-t0:.0f}s)", flush=True)

    # pairs
    ptr = run_pairs(data)
    res["pairs"] = {"n_raw": len(ptr), "pairs_tested": [f"{a}/{b}" for a, b in PAIRS
                                                       if a in data and b in data]}
    res["pairs"]["bps0"] = pairs_summary(ptr, 0.0, 0) or {"n": 0}
    res["pairs"]["bps10"] = pairs_summary(ptr, 0.0010, 0) or {"n": 0}
    print(f"pairs: n={len(ptr)} ({time.time()-t0:.0f}s)", flush=True)

    with open(OUT, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\nwrote {OUT} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
