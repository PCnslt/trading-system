#!/usr/bin/env python3
"""Daily-bar collector for the FULL US common-stock universe (~6,000 symbols).

Decoupled from the trading system: yfinance only, no IBKR, no clientId, no
DynamoDB trading keys. Writes one JSON object per symbol to S3
`yf/stocks/daily/<sym>.json` (full daily history back to IPO).

Idempotent + self-healing:
  - A local checkpoint (data_engine/state/daily_checkpoint.json) records, per
    symbol, whether it is COMPLETE and its last bar date. Re-runs SKIP completed
    symbols (that is the "skip collected dates" behaviour).
  - Symbols that failed are left incomplete and retried on the next run.
  - `--incremental` (default) re-fetches the last ~5d and merges-by-date into the
    existing object for already-complete symbols, healing recent gaps / catching
    new bars.
  - `--full` forces a full `period='max'` re-download (deep gap healing).

Rate-limit aware: paced with a backoff multiplier on 429/rate-limit errors; a
run is allowed to span many hours (continuous background batch) and resumes
from the checkpoint. `--limit N` caps a single run so cron can do bounded daily
increments.

Usage:
  python -m data_engine.collect_daily                    # incremental, resume, all symbols
  python -m data_engine.collect_daily --limit 100        # bounded batch (cron)
  python -m data_engine.collect_daily --symbols AAPL,MSFT
  python -m data_engine.collect_daily --full --symbols AAPL   # deep heal one symbol
  python -m data_engine.collect_daily --dry-run
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

import pandas as pd
import yfinance as yf

from . import config, s3store, universe as _universe

_CHECKPOINT = os.path.join(config.STATE_DIR, "daily_checkpoint.json")

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


def _records(df):
    out = []
    for idx, r in df.iterrows():
        out.append({
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
            "open": _f(r.get("Open")), "high": _f(r.get("High")),
            "low": _f(r.get("Low")), "close": _f(r.get("Close")),
            "volume": _f(r.get("Volume")),
        })
    return out


def _download(sym, interval, period):
    df = yf.download(sym, period=period, interval=interval,
                     progress=False, auto_adjust=False)
    return _flatten(df)


def _is_rate_limited(exc):
    s = str(exc).lower()
    return any(m in s for m in _RATE_LIMIT_MARKERS)


def _daily_key(sym):
    return config.prefix("daily").format(sym=sym)


def _load_checkpoint():
    if os.path.isfile(_CHECKPOINT):
        with open(_CHECKPOINT, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "symbols": {}}


def _save_checkpoint(cp):
    os.makedirs(os.path.dirname(_CHECKPOINT), exist_ok=True)
    tmp = _CHECKPOINT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cp, f)
    os.replace(tmp, _CHECKPOINT)


def _merge(existing_records, new_records):
    merged = {r["date"]: r for r in existing_records}
    for r in new_records:
        merged[r["date"]] = r  # new bars overwrite same-date (idempotent)
    return [merged[d] for d in sorted(merged)]


def collect_one(sym, force_full, incremental):
    """Collect/merge one symbol's daily history. Returns (status, nbars, first, last)."""
    key = _daily_key(sym)
    existing = s3store.get_json(key)
    existing_records = existing.get("bars", []) if existing else []

    if existing and force_full:
        df = _download(sym, "1d", config.depth()["daily_period"])
    elif existing and incremental:
        # merge recent bars (heal recent gaps + catch new bars)
        df = _download(sym, "1d", config.depth()["daily_incremental_period"])
    else:
        # first visit (or non-incremental): full history
        df = _download(sym, "1d", config.depth()["daily_period"])

    new_records = _records(df)
    if not new_records:
        return ("empty", 0, None, None)

    bars = _merge(existing_records, new_records) if existing else new_records

    # metrics for the liquidity ranking
    closes = [b["close"] for b in bars if b.get("close") is not None]
    vols = [b["volume"] for b in bars if b.get("volume") is not None]
    n = min(len(closes), len(vols))
    window = closes[-config.liquid_cfg()["metrics_window_days"]:], vols[-config.liquid_cfg()["metrics_window_days"]:]
    if n > 0:
        c = closes[-config.liquid_cfg()["metrics_window_days"]:]
        v = vols[-config.liquid_cfg()["metrics_window_days"]:]
        adv20 = sum(a * b for a, b in zip(c, v)) / len(c) if c else 0.0
    else:
        adv20 = 0.0

    payload = {
        "symbol": sym, "source": "yfinance", "interval": "1d",
        "firstDate": bars[0]["date"], "lastDate": bars[-1]["date"],
        "nbars": len(bars), "bars": bars,
        "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    s3store.put_json(payload, key)

    return ("ok", len(bars), bars[0]["date"], bars[-1]["date"])


def _append_metrics(sym, bars, metrics_file):
    closes = [b["close"] for b in bars if b.get("close") is not None]
    vols = [b["volume"] for b in bars if b.get("volume") is not None]
    n = min(len(closes), len(vols))
    if n == 0:
        return
    win = config.liquid_cfg()["metrics_window_days"]
    c = closes[-win:]
    v = vols[-win:]
    adv20 = sum(a * b for a, b in zip(c, v)) / len(c) if c else 0.0
    row = {"symbol": sym, "last_close": c[-1], "avg_dollar_volume_20d": adv20,
           "nbars": len(bars), "last_date": bars[-1]["date"]}
    with open(metrics_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="comma subset")
    ap.add_argument("--limit", type=int, default=0, help="max symbols to process this run")
    ap.add_argument("--full", action="store_true", help="force full re-download (deep gap heal)")
    ap.add_argument("--no-incremental", action="store_true", help="disable incremental merge for completed syms")
    ap.add_argument("--all", action="store_true", help="process completed symbols too (incremental refresh)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config.ensure_dirs()
    cfg = config.pacing()

    lock, lockpath = config.acquire_lock("collect_daily")
    if lock is None:
        print(f"[collect_daily] another instance holds {lockpath} — exiting (serialize).")
        return

    print("[universe] loading common-stock universe…")
    all_syms = _universe.load_symbols()
    print(f"[universe] {len(all_syms)} symbols")

    syms = list(all_syms)
    if args.symbols:
        want = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        syms = [s for s in syms if s in want]

    cp = _load_checkpoint()
    metrics_file = config.local_path(config.liquid_cfg()["metrics_file"])
    os.makedirs(os.path.dirname(metrics_file), exist_ok=True)

    # resume order: incomplete first, then (optionally) completed for incremental
    incomplete = [s for s in syms if not cp["symbols"].get(s, {}).get("done")]
    complete = [s for s in syms if cp["symbols"].get(s, {}).get("done")]
    if args.all:
        ordered = incomplete + complete
    else:
        ordered = incomplete

    if args.limit:
        ordered = ordered[:args.limit]

    print(f"[collect_daily] queue={len(ordered)} (incomplete={len(incomplete)}, "
          f"complete={len(complete)}, full={args.full}, incremental={not args.no_incremental}, "
          f"dry_run={args.dry_run})")

    backoff = cfg["rate_limit_backoff_s"]
    consecutive_errors = 0
    done_this_run = 0
    ok = 0
    empty = 0
    failed = 0

    for i, sym in enumerate(ordered):
        try:
            st, nbars, first, last = collect_one(sym, force_full=args.full,
                                                 incremental=not args.no_incremental)
            if st == "ok":
                ok += 1
                # metrics: re-read just-written object is expensive; recompute from a cheap path
                key = _daily_key(sym)
                payload = s3store.get_json(key)
                if payload and payload.get("bars"):
                    _append_metrics(sym, payload["bars"], metrics_file)
                cp["symbols"][sym] = {"done": True, "lastDate": last, "nbars": nbars}
                print(f"  [{i+1}/{len(ordered)}] {sym}: {nbars} bars {first}..{last}")
            elif st == "empty":
                empty += 1
                print(f"  [{i+1}/{len(ordered)}] {sym}: NO DATA (delisted/bad ticker) — marking done")
                cp["symbols"][sym] = {"done": True, "lastDate": None, "nbars": 0, "empty": True}
            consecutive_errors = 0
            done_this_run += 1
        except Exception as e:
            failed += 1
            consecutive_errors += 1
            if _is_rate_limited(e):
                print(f"  [{i+1}/{len(ordered)}] {sym}: RATE LIMITED ({e!r}) — backoff {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 600)
            else:
                print(f"  [{i+1}/{len(ordered)}] {sym}: FAILED ({e!r})")
            if consecutive_errors >= cfg["max_consecutive_errors"]:
                print(f"  [abort] {consecutive_errors} consecutive errors — stopping, will resume next run")
                break

        if (i + 1) % cfg["checkpoint_every_symbols"] == 0:
            _save_checkpoint(cp)
            print(f"  [checkpoint] saved at {i+1} symbols")

        time.sleep(cfg["daily_between_symbols_s"])

    _save_checkpoint(cp)

    # mirror manifest to S3 for cross-process visibility
    manifest = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "universe_size": len(all_syms),
        "complete": sum(1 for s in cp["symbols"].values() if s.get("done")),
        "total": len(cp["symbols"]),
    }
    s3store.put_json(manifest, config.prefix("meta").format(name="daily_manifest.json"))

    print(f"\n=== collect_daily DONE === ok={ok} empty={empty} failed={failed} "
          f"complete_total={manifest['complete']}/{manifest['universe_size']} "
          f"(dry_run={args.dry_run})")
    print(f"checkpoint: {_CHECKPOINT}")


if __name__ == "__main__":
    main()
