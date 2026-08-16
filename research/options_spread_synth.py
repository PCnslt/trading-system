"""Synthetic defined-risk credit-spread backtest (honest model — NO real options bars).

DATA REALITY: S3 has NO historical options bars and no equity options — only
futures-options chain METADATA (expirations + strikes, no prices/greeks). A true
spread backtest needs paid historical options data (IV surface per strike/expiry).
This model prices spreads with Black-Scholes using REALIZED vol as the IV proxy,
so it is a NO-EDGE BASELINE (IV == realized, no volatility risk premium baked in).
It answers: "does a mechanical short-premium spread, priced at realized vol, make
money net of the structural risks?" — and it stress-tests how big a vol premium
(IV > realized) would need to be to flip it.

Model (per name, monthly rebalance, 30 calendar-day hold to expiry):
  * sigma = 60d realized vol (annualized) of daily log returns.
  * Iron condor: short 0.30-delta-ish put + short 0.30-delta-ish call, long wings
    `width` away (width = max($5, 5% of spot)).
  * Premium via Black-Scholes (math.erf normal CDF).
  * P&L at expiry = credit - max(put_payoff, call_payoff); margin = width.
  * Premium scale factor `vp` = 1.0 (realized) and 1.15 (index-style vol premium)
    to show sensitivity.

Assignment risk (honest flag, not modeled numerically): a short leg ITM at expiry
is auto-assigned 100 shares; at Robinhood L2 a spread is NOT marginable the way a
broker treats it — pin risk near expiry (underlying pinned between strikes) is the
real tail. We note it; we cannot price early-exercise dynamics without intraday
options data.

Output: /home/ubuntu/trading-system/research/options_spread_synth_results.json
"""
from __future__ import annotations

import json
import math
import time
from collections import defaultdict

import numpy as np
import pandas as pd

PKL = "/tmp/stock_mr_ohlcv.pkl"
OUT = "/home/ubuntu/trading-system/research/options_spread_synth_results.json"
DTE = 30
WIDTH = 0.05          # 5% of spot, min $5 enforced in $
VP_GRID = (1.0, 1.15)
HORIZON = 21          # trading days ~ 30 calendar


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S, K, T, sigma, r, is_call):
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if is_call else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


def load():
    df = pd.read_pickle(PKL)
    data = {}
    for sym, g in df.groupby(level=0):
        if g.index.nlevels > 1:
            g = g.droplevel(0)
        data[sym] = g
    return data


def realized_vol(d, i, win=60):
    c = d["close"].to_numpy()
    lo = max(1, i - win)
    rets = np.diff(np.log(c[lo:i + 1]))
    if len(rets) < 20:
        return np.nan
    return float(np.std(rets, ddof=1) * math.sqrt(252))


def run_condors(data, vp):
    """Monthly iron condors. Returns list of trade dicts with P&L fraction of margin."""
    trades = []
    for sym, df in data.items():
        c = df["close"].to_numpy()
        n = len(df)
        i = 120
        while i < n - HORIZON:
            S = c[i]
            sig = realized_vol(df, i)
            if S <= 0 or np.isnan(sig) or sig <= 0:
                i += 21
                continue
            iv = sig * vp
            T = DTE / 365.0
            r = 0.0
            # short put ~0.30 delta: K = S*exp(-0.35*sig*sqrt(T)); short call symmetric
            k_put_short = S * math.exp(-0.35 * iv * math.sqrt(T))
            k_call_short = S * math.exp(0.35 * iv * math.sqrt(T))
            width = max(5.0, WIDTH * S)
            k_put_long = k_put_short - width
            k_call_long = k_call_short + width
            if k_put_long <= 0.0 or k_call_long <= 0.0:
                i += 21
                continue
            prem = (bs_price(S, k_put_short, T, iv, r, False) -
                    bs_price(S, k_put_long, T, iv, r, False) +
                    bs_price(S, k_call_short, T, iv, r, True) -
                    bs_price(S, k_call_long, T, iv, r, True))
            if prem <= 0:
                i += 21
                continue
            S_T = c[i + HORIZON]
            put_pay = max(k_put_short - S_T, 0) - max(k_put_long - S_T, 0)
            call_pay = max(S_T - k_call_short, 0) - max(S_T - k_call_long, 0)
            payoff = max(put_pay, call_pay)
            margin = width
            pnl = prem - payoff
            trades.append({"symbol": sym, "entry_i": i, "entry_date": df.index[i],
                           "spot": float(S), "iv": iv, "credit": float(prem),
                           "width": float(width), "pnl_frac_margin": float(pnl / margin),
                           "win": bool(pnl > 0)})
            i += 21
    return trades


def summarize(trades):
    if not trades:
        return {"n": 0}
    r = np.array([t["pnl_frac_margin"] for t in trades])
    wins = r[r > 0].sum()
    losses = -r[r < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    # daily equity curve for maxDD (mark-to-market at entry, realized at exit)
    daily = defaultdict(float)
    for t in trades:
        daily[t["entry_i"]] += t["pnl_frac_margin"]
    eq = pd.Series(daily).sort_index().cumsum()
    dd = float((eq - eq.cummax()).min())
    return {
        "n": int(len(r)), "pf": float(pf), "win": float((r > 0).mean()),
        "net": float(r.sum()), "avg_pnl": float(r.mean()),
        "worst": float(r.min()), "best": float(r.max()),
        "maxdd_frac": dd,
        "avg_credit": float(np.mean([t["credit"] for t in trades])),
        "avg_credit_pct": float(np.mean([t["credit"] / t["width"] for t in trades])),
        "avg_width": float(np.mean([t["width"] for t in trades])),
        "avg_iv": float(np.mean([t["iv"] for t in trades])),
    }


def main():
    t0 = time.time()
    data = load()
    res = {"universe": sorted(data.keys()), "universe_n": len(data),
           "model": "BS iron condor, IV=realized*vp, 30DTE, 5% width, monthly",
           "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    for vp in VP_GRID:
        tr = run_condors(data, vp)
        res[f"vp_{vp}"] = summarize(tr)
        print(f"vp={vp}: {summarize(tr)} ({time.time()-t0:.0f}s)", flush=True)
    with open(OUT, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"wrote {OUT} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
