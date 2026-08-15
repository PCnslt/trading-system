#!/usr/bin/env python3
"""Intraday-bar collector (1h + 1m) for the LIQUID subset (~1,000 symbols).

Decoupled from the trading system: yfinance only, no IBKR, no clientId.
Writes date-partitioned objects to S3 `yf/stocks/intraday/<sym>/<interval>/<date>.json`
(idempotent — same date key overwritten each run).

Liquidity gating: the symbol list is the top ~1,000 by average dollar volume
(computed from the daily collector's metrics), falling back to a yfinance
screener seed if daily metrics are not yet available. Do NOT run this on the
full ~6,000 universe — 1m is rate-limit + storage expensive.

Honest depth (measured 2026-08-15, yfinance 1.6.0):
  - 1h : period '730d' → ~2 years (session-timed bars)
  - 1m : period '7d'  → 8 calendar days ONLY (Yahoo hard-cap: "Only 8 days worth
         of 1m granularity data are allowed"). 30d/60d requests FAIL.
         Not the ~30-60d some notes assumed — treat 1m as a rolling 1-week window.

Usage:
  python -m data_engine.collect_intraday                      # liquid subset, 1h+1m
  python -m data_engine.collect_intraday --interval 1h
  python -m data_engine.collect_intraday --symbols AAPL,MSFT
  python -m data_engine.collect_intraday --top 500            # only top-500 liquid
  python -m data_engine.collect_intraday --dry-run
"""
import argparse
import datetime as dt
import time

import pandas as pd
import yfinance as yf

from . import config, s3store, universe as _universe

_RATE_LIMIT_MARKERS = ("rate limit", "429", "too many requests", "slow down")


def _flatten(df):
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _f(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _download(sym, interval, period):
    df = yf.download(sym, period=period, interval=interval,
                     progress=False, auto_adjust=False)
    return _flatten(df)


def _intraday_key(sym, interval, date):
    return config.prefix("intraday").format(sym=sym, interval=interval, date=date)


def _date_of(idx):
    return idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]


def collect_symbol(sym, intervals):
    """Fetch + archive one symbol's intraday bars. Returns dict of counts."""
    counts = {}
    depth = config.depth()
    for interval in intervals:
        period = depth["intraday_1h_period"] if interval == "1h" else depth["intraday_1m_period"]
        try:
            df = _download(sym, interval, period)
        except Exception as e:
            print(f"    [{sym}] {interval}: download error {e!r}")
            counts[interval] = -1
            continue
        if df is None or df.empty:
            print(f"    [{sym}] {interval}: NO DATA")
            counts[interval] = 0
            continue
        # partition by session date
        by_date = {}
        for idx, r in df.iterrows():
            d = _date_of(idx)
            by_date.setdefault(d, []).append({
                "ts": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                "open": _f(r.get("Open")), "high": _f(r.get("High")),
                "low": _f(r.get("Low")), "close": _f(r.get("Close")),
                "volume": _f(r.get("Volume")),
            })
        for d in sorted(by_date):
            payload = {"symbol": sym, "interval": interval, "date": d,
                       "nbars": len(by_date[d]), "bars": by_date[d],
                       "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat()}
            s3store.put_json(payload, _intraday_key(sym, interval, d))
        counts[interval] = sum(len(v) for v in by_date.values())
        print(f"    [{sym}] {interval}: {counts[interval]} bars across {len(by_date)} dates")
        time.sleep(config.pacing()["intraday_between_intervals_s"])
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="comma subset (overrides liquid list)")
    ap.add_argument("--interval", default="", help="1h or 1m (default both)")
    ap.add_argument("--top", type=int, default=0, help="only top-N liquid symbols")
    ap.add_argument("--limit", type=int, default=0, help="max symbols this run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config.ensure_dirs()
    pacing = config.pacing()

    lock, lockpath = config.acquire_lock("collect_intraday")
    if lock is None:
        print(f"[collect_intraday] another instance holds {lockpath} — exiting (serialize).")
        return

    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        syms = _universe.load_liquid_symbols()
        print(f"[liquid] {len(syms)} symbols (dollar-volume rank + screener seed)")
        if args.top:
            syms = syms[:args.top]
            print(f"[liquid] trimmed to top {len(syms)}")

    if args.interval:
        intervals = [args.interval]
    else:
        intervals = config.intervals()["intraday"]

    if args.limit:
        syms = syms[:args.limit]

    print(f"[collect_intraday] {len(syms)} symbols x {intervals} "
          f"(dry_run={args.dry_run})")

    if args.dry_run:
        for s in syms[:20]:
            print(f"  (dry) {s}")
        print(f"  … {len(syms)} total")
        return

    ok = 0
    failed = 0
    backoff = pacing["rate_limit_backoff_s"]
    for i, sym in enumerate(syms):
        try:
            counts = collect_symbol(sym, intervals)
            if any(v and v > 0 for v in counts.values()):
                ok += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            s = str(e).lower()
            if any(m in s for m in _RATE_LIMIT_MARKERS):
                print(f"  [{i+1}/{len(syms)}] {sym}: RATE LIMITED — backoff {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 600)
            else:
                print(f"  [{i+1}/{len(syms)}] {sym}: FAILED {e!r}")
        time.sleep(pacing["intraday_between_symbols_s"])

    print(f"\n=== collect_intraday DONE === ok={ok} failed={failed} / {len(syms)}")


if __name__ == "__main__":
    main()
