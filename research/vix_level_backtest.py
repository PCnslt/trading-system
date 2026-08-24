"""Spot-VIX LEVEL contrarian lane (Simon-Wiggins 2001 "fear premium") — tradeable build.

Signal (confirmed upstream in vix_term_structure_backtest.py): when the CBOE spot
VIX is >2 sigma ABOVE its trailing mean (fear spike), buy equities and hold ~1
week. This is the LEVEL of VIX, NOT the term-structure slope (lane 44 = NO-GO).

This script turns the confirmed signal into a TRADEABLE lane and answers the open
questions from the queue:
  1. z-window: 1y (252d) vs 2y (504d) rolling mean/std.
  2. entry timing: close[t] (VIX close known at SPY close) vs next-open[t+1].
  3. universe: SPY, QQQ (+ leveraged SSO/UPRO/TQQQ via yfinance if reachable).
  4. exit: fixed 5d and 10d hold + a 2xATR(14) broker stop variant.
  5. sizing: equal-weight per symbol (market-timing overlay; vol note in doc).
  6. overlap: BOTH event-study (overlapping, matches n=594 upstream) and
     NON-OVERLAPPING (skip H bars after entry — the actual tradeable lane).

Cost model: equities round-trip >=5 bps baseline, 10 bps = 2x stress. PF >= 1.3
OOS @5bps to PASS (repo gate). IS = 1993..2019-12-31, OOS = 2020-01..2026.

Data: FRED VIXCLS (free) + S3 yf/etfs/{SPY,QQQ}.json + yfinance for leveraged ETFs.

HONEST CAVEATS (also printed): overlap dedup, VIX-only universe (no small-cap
test), close-entry assumes VIX close known at equity close (true: VIX prints in
real time all session), no dividend adjustment on yf leveraged ETFs, survivorship
n/a (index ETFs), the whole family is LONG-beta (drift-inflated in bull markets).

Run:  ./venv/bin/python -u research/vix_level_backtest.py
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd
import boto3
import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"))

S3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")

IS_END = pd.Timestamp("2019-12-31")
HORIZONS = (5, 10)
THRESH = (1.5, 2.0, 2.5)
WINDOWS = (252, 504)
COST_BPS = 5.0
COST = COST_BPS / 10000.0
COST_2X = 2 * COST
ATR_N = 14
STOP_MULT = 2.0

RESULT = {"idea": "spot-VIX level contrarian", "rows": [], "verdict": {}}


# ---------------------------------------------------------------- data load
def fred(sid: str) -> pd.DataFrame:
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                     params={"id": sid}, timeout=60)
    rows = []
    for ln in r.text.strip().splitlines()[1:]:
        p = ln.split(",")
        if len(p) >= 2 and p[1] not in ("", "."):
            try:
                rows.append((pd.to_datetime(p[0]), float(p[1])))
            except (ValueError, TypeError):
                pass
    return pd.DataFrame(rows, columns=["date", sid]).set_index("date")


def s3_etf(sym: str) -> pd.DataFrame:
    d = json.loads(S3.get_object(Bucket=BUCKET, Key=f"yf/etfs/{sym}.json")
                   ["Body"].read().decode())["daily"]
    df = pd.DataFrame(d)
    df["date"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
    df = df.set_index("date")[["open", "high", "low", "close"]].astype(float)
    return df[~df.index.duplicated(keep="last")].sort_index()


def yf_etf(sym: str) -> pd.DataFrame | None:
    """Leveraged ETFs via yfinance (graceful if offline)."""
    try:
        import yfinance as yf
        df = yf.download(sym, start="1990-01-01", progress=False,
                         auto_adjust=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        df = df[["Open", "High", "Low", "Close"]].rename(
            columns={"Open": "open", "High": "high",
                     "Low": "low", "Close": "close"})
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except Exception as e:  # noqa: BLE001
        print(f"    [yf] {sym} unavailable: {e!r}")
        return None


def atr14(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / ATR_N, adjust=False).mean()


# ---------------------------------------------------------------- metrics
def pf_of(x: np.ndarray) -> float:
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return float("nan")
    wins = x[x > 0].sum()
    losses = -x[x < 0].sum()
    return float(wins / losses) if losses > 1e-12 else float("inf")


def fmt(p: float) -> str:
    return "inf" if np.isinf(p) else f"{p:.2f}"


def row_metrics(net: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    net = np.asarray(net, float)
    dates = pd.DatetimeIndex(dates)
    m = ~np.isnan(net)
    net, dates = net[m], dates[m]
    ism = dates <= IS_END
    oos = dates > IS_END
    return {
        "n": int(len(net)),
        "win": float((net > 0).mean()) if len(net) else float("nan"),
        "mean_bp": float(net.mean() * 1e4) if len(net) else float("nan"),
        "pf": pf_of(net),
        "is_pf": pf_of(net[ism]) if ism.any() else float("nan"),
        "oos_pf": pf_of(net[oos]) if oos.any() else float("nan"),
        "is_n": int(ism.sum()), "oos_n": int(oos.sum()),
    }


# ---------------------------------------------------------------- engine
def run_symbol(sym: str, df: pd.DataFrame, vix: pd.Series, tag: str) -> None:
    j = df.join(vix, how="inner")
    atr = atr14(j)
    for W in WINDOWS:
        mu = j["vix"].rolling(W).mean()
        sd = j["vix"].rolling(W).std(ddof=0)
        z = (j["vix"] - mu) / sd
        for th in THRESH:
            sig = z >= th
            for H in HORIZONS:
                close_ret = j["close"].shift(-H) / j["close"] - 1.0
                open_ret = j["close"].shift(-H) / j["open"].shift(-1) - 1.0
                # --- 2xATR stop variant (close-entry): exit at stop if low crosses
                stop_price = j["close"] - STOP_MULT * atr
                stop_ret = close_ret.copy()
                earlier = np.zeros(len(j), dtype=bool)
                for k in range(1, H + 1):
                    first_hit = (j["low"].shift(-k) <= stop_price) & ~earlier
                    earlier |= first_hit
                    if first_hit.any():
                        stop_ret[first_hit.values] = (
                            stop_price[first_hit.values]
                            / j["close"][first_hit.values] - 1.0)
                for entry_label, ret in [("close", close_ret),
                                         ("open", open_ret),
                                         ("close+stop", stop_ret)]:
                    for cost_bps, cost in [(5.0, COST), (10.0, COST_2X)]:
                        for overlap, dedup in [("overlap", False), ("dedup", True)]:
                            idx = np.where(sig.values)[0]
                            if dedup:
                                keep = []
                                last = -10**9
                                for i in idx:
                                    if i - last >= H:
                                        keep.append(i)
                                        last = i
                                idx = np.array(keep)
                            if len(idx) == 0:
                                continue
                            net = ret.values[idx] - cost
                            r = row_metrics(net, j.index[idx])
                            r.update(sym=sym, tag=tag, window=W, th=th, H=H,
                                     entry=entry_label, cost=cost_bps,
                                     overlap=overlap)
                            RESULT["rows"].append(r)


def main() -> None:
    print("loading VIXCLS from FRED ...", flush=True)
    vix = fred("VIXCLS").rename(columns={"VIXCLS": "vix"})["vix"]
    print(f"  vix {vix.index[0].date()}..{vix.index[-1].date()} n={len(vix)}")

    data = {"SPY": ("index", s3_etf("SPY")), "QQQ": ("index", s3_etf("QQQ"))}
    for sym in ("SSO", "UPRO", "TQQQ"):
        df = yf_etf(sym)
        if df is not None:
            data[sym] = ("leveraged", df)
    print(f"  symbols: {', '.join(data)}")

    for sym, (tag, df) in data.items():
        print(f"\n=== {sym} ({tag}) {df.index[0].date()}..{df.index[-1].date()} "
              f"n={len(df)} ===", flush=True)
        run_symbol(sym, df, vix, tag)

    # ---- print summary ----
    R = pd.DataFrame(RESULT["rows"])
    print("\n" + "=" * 100)
    print("TRADEABLE-LANE summary (dedup, 5d hold, th=2.0, 1y window) — "
          "IS 1993..2019 / OOS 2020..2026")
    print("=" * 100)
    view = R[(R.overlap == "dedup") & (R.H == 5) & (R.th == 2.0) & (R.window == 252)]
    print(f"  {'sym':<6}{'entry':<6}{'cost':>4}  "
          f"{'n':>5}{'win%':>6}{'meanbp':>8}{'PF':>6}{'ISPF':>6}{'OOSPF':>6}")
    for _, r in view.sort_values(["sym", "entry", "cost"]).iterrows():
        print(f"  {r.sym:<6}{r.entry:<6}{r.cost:>4.0f}  "
              f"{r.n:>5}{100*r.win:>5.0f}%{r.mean_bp:>+8.1f}"
              f"{fmt(r.pf):>6}{fmt(r.is_pf):>6}{fmt(r.oos_pf):>6}")

    print("\n  z-threshold robustness (SPY, close, 5d, dedup, @5bps):")
    v = R[(R.sym == "SPY") & (R.entry == "close") & (R.H == 5) &
          (R.overlap == "dedup") & (R.cost == 5.0)]
    for _, r in v.sort_values(["window", "th"]).iterrows():
        print(f"    window={r.window}d th={r.th}  n={r.n}  PF={fmt(r.pf)}  "
              f"IS={fmt(r.is_pf)}  OOS={fmt(r.oos_pf)}")

    print("\n  window 1y vs 2y (SPY, close, 5d, th=2.0, dedup, @5bps):")
    v = R[(R.sym == "SPY") & (R.entry == "close") & (R.H == 5) &
          (R.overlap == "dedup") & (R.th == 2.0) & (R.cost == 5.0)]
    for _, r in v.iterrows():
        print(f"    window={r.window}d  n={r.n}  PF={fmt(r.pf)}  IS={fmt(r.is_pf)}  "
              f"OOS={fmt(r.oos_pf)}")

    out = os.path.join(_ROOT, "research", "vix_level_backtest_results.json")
    json.dump(RESULT, open(out, "w"), indent=2, default=str)
    print(f"\nwrote {out} ({len(R)} rows)")
    print("\nCAVEATS: index-ETF universe (no small caps); long-beta family "
          "(drift-inflated in bulls); dedup = skip H bars post-entry; close-entry "
          "assumes VIX close known at equity close (true in-session).")


if __name__ == "__main__":
    main()
