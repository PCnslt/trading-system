"""US equity universe discovery + liquidity ranking for the data engine.

Two jobs:
  1. build_us_common_stocks()  — full US common-stock universe (~6,000 symbols)
     from Nasdaq Trader's free listing files (canonical, keyless), filtered to
     common stocks only (ETF=N, test issue=N, no preferred/warrant/unit/ADR-class
     suffix noise).
  2. rank_liquid()             — top ~1,000 by average dollar volume
     (close * volume over the last 20 sessions), read from the daily-collector's
     metrics JSONL, plus a screener seed that is available immediately.

Artifacts are cached locally (data_engine/cache/) AND mirrored to S3
(data-engine/universe/…, data-engine/meta/…) so the engine is self-healing and
portable.

Usage:
  python -m data_engine.universe --refresh      # rebuild universe + seed, cache+mirror
  python -m data_engine.universe --rank-liquid  # rank top-N from daily metrics
"""
import argparse
import datetime as dt
import json
import os

import requests

from . import config, s3store

_NASDAQ_COLS = ["Symbol", "Security Name", "Market Category", "Test Issue",
                "Financial Status", "Round Lot Size", "ETF", "NextShares"]
_OTHER_COLS = ["ACT Symbol", "Security Name", "Exchange", "CQS Symbol", "ETF",
               "Round Lot Size", "Test Issue", "NASDAQ Symbol"]

# Suffixes / patterns that indicate a non-common-stock security. A plain ticker
# with these is usually a preferred (PR), warrant (WS/WT), unit (U), right (R),
# or ADR class (e.g. BRK.B has a '.', GOOGL/GOOG are fine but 'GOOG.L' is not).
_BAD_SUFFIX_MARKERS = (".", "-", "=", "^", "/")


def _clean(s):
    return (s or "").strip()


def _parse_pipe(lines, cols):
    """Yield dict rows from a '|'-delimited, header-first listing."""
    header = None
    for raw in lines:
        raw = raw.rstrip("\r\n")
        if not raw:
            continue
        parts = raw.split("|")
        if header is None:
            header = [p.strip() for p in parts]
            continue
        row = {header[i]: parts[i].strip() for i in range(min(len(header), len(parts)))}
        yield row


def _is_common_stock_symbol(sym):
    if not sym:
        return False
    if any(m in sym for m in _BAD_SUFFIX_MARKERS):
        return False
    return sym.isalpha() or (len(sym) <= 5 and sym[:-1].isalpha() and sym[-1].isdigit())


def fetch_us_common_stocks(timeout=30):
    """Fetch + filter the Nasdaq/other listings -> sorted common-stock symbol list.

    Returns (symbols, meta) where symbols is a list of {symbol, name, exchange}.
    """
    cfg = config.universe_cfg()
    out = {}
    for key, url in cfg["urls"].items():
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        rows = list(_parse_pipe(r.text.splitlines(), _NASDAQ_COLS if key == "nasdaq" else _OTHER_COLS))
        for row in rows:
            if key == "nasdaq":
                sym = _clean(row.get("Symbol"))
                etf = _clean(row.get("ETF")).upper() == "Y"
                test = _clean(row.get("Test Issue")).upper() == "Y"
                name = _clean(row.get("Security Name"))
                exch = "NASDAQ"
            else:
                sym = _clean(row.get("ACT Symbol"))
                etf = _clean(row.get("ETF")).upper() == "Y"
                test = _clean(row.get("Test Issue")).upper() == "Y"
                name = _clean(row.get("Security Name"))
                exch = _clean(row.get("Exchange")) or "NYSE"
            if not sym or etf or test:
                continue
            if not _is_common_stock_symbol(sym):
                continue
            out.setdefault(sym, {"symbol": sym, "name": name, "exchange": exch})
    symbols = [out[s] for s in sorted(out)]
    return symbols, {"source": cfg["source"], "count": len(symbols)}


def seed_liquid_from_screeners(timeout=60):
    """Union Yahoo predefined screeners, ranked by avg dollar volume.

    Returns a list of {symbol, dollar_volume} sorted desc. Does NOT require
    collected bars — used to start intraday collection before daily completes.
    """
    import yfinance as yf
    cfg = config.liquid_cfg()
    seen = {}
    for q in cfg["seed_screeners"]:
        try:
            d = yf.screen(q, count=250)
            quotes = d.get("quotes") or []
        except Exception as e:
            print(f"  [seed] screener {q} failed: {e!r}")
            continue
        for item in quotes:
            if not isinstance(item, dict):
                continue
            sym = item.get("symbol")
            qtype = item.get("quoteType")
            if not sym or qtype != "EQUITY":
                continue
            if not _is_common_stock_symbol(sym):
                continue
            price = item.get("regularMarketPrice") or 0
            adv10 = item.get("averageDailyVolume10Day") or item.get("regularMarketVolume") or 0
            dv = float(price) * float(adv10)
            if dv > 0:
                prev = seen.get(sym)
                if prev is None or dv > prev["dollar_volume"]:
                    seen[sym] = {"symbol": sym, "dollar_volume": dv,
                                 "name": item.get("shortName") or item.get("longName") or ""}
    ranked = sorted(seen.values(), key=lambda x: -x["dollar_volume"])
    return ranked


def rank_liquid_from_metrics(metrics_file=None, top_n=None):
    """Rank symbols by avg dollar volume from the daily-collector metrics JSONL.

    Returns (ranked_list, total_symbols_with_metrics). Each row:
    {symbol, avg_dollar_volume_20d, last_close, nbars}.
    """
    cfg = config.liquid_cfg()
    top_n = top_n or cfg["target_count"]
    metrics_file = metrics_file or config.local_path(cfg["metrics_file"])
    rows = []
    if not os.path.isfile(metrics_file):
        return [], 0
    with open(metrics_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("symbol"):
                rows.append(r)
    # dedupe by symbol (last occurrence = most recent); keep max dollar volume
    by_sym = {}
    for r in rows:
        s = r["symbol"]
        if s not in by_sym or (r.get("avg_dollar_volume_20d") or 0) >= (by_sym[s].get("avg_dollar_volume_20d") or 0):
            by_sym[s] = r
    rows = list(by_sym.values())
    rows = [r for r in rows if (r.get("avg_dollar_volume_20d") or 0) > 0]
    rows.sort(key=lambda r: -(r.get("avg_dollar_volume_20d") or 0))
    return rows[:top_n], len(rows)


def _save_and_mirror(obj, cache_path, s3_key):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    s3store.put_json(obj, s3_key)
    return s3store.put_json(obj, s3_key)


def build_and_cache_universe():
    config.ensure_dirs()
    cfg = config.universe_cfg()
    symbols, meta = fetch_us_common_stocks()
    payload = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
               "meta": meta, "symbols": symbols}
    cache = config.local_path(cfg["cache_file"])
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    s3store.put_json(payload, cfg["s3_key"])
    return payload


def build_and_cache_seed():
    config.ensure_dirs()
    cfg = config.liquid_cfg()
    seed = seed_liquid_from_screeners()
    payload = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
               "method": "yfinance_screeners_union",
               "count": len(seed), "symbols": seed}
    cache = config.local_path(cfg["seed_cache_file"])
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return payload


def load_cached_universe():
    cfg = config.universe_cfg()
    cache = config.local_path(cfg["cache_file"])
    if not os.path.isfile(cache):
        # fall back to S3 mirror
        obj = s3store.get_json(cfg["s3_key"])
        if obj and obj.get("symbols"):
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=2)
        else:
            return build_and_cache_universe()
    with open(cache, "r", encoding="utf-8") as f:
        return json.load(f)


def load_symbols():
    """Return the flat sorted symbol list (strings) for the full universe."""
    payload = load_cached_universe()
    return [s["symbol"] for s in payload.get("symbols", [])]


def load_liquid_symbols():
    """Best available liquid list: ranked-from-metrics first, screener seed as fallback."""
    cfg = config.liquid_cfg()
    ranked, _ = rank_liquid_from_metrics()
    if ranked:
        return [r["symbol"] for r in ranked]
    # seed fallback (cached or fresh)
    cache = config.local_path(cfg["seed_cache_file"])
    seed = None
    if os.path.isfile(cache):
        with open(cache, "r", encoding="utf-8") as f:
            seed = json.load(f)
    if not seed or not seed.get("symbols"):
        seed = build_and_cache_seed()
    return [s["symbol"] for s in seed.get("symbols", [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="rebuild universe + seed, cache + mirror to S3")
    ap.add_argument("--rank-liquid", action="store_true", help="rank top-N by dollar volume from daily metrics")
    ap.add_argument("--top", type=int, default=None)
    args = ap.parse_args()

    if args.refresh:
        u = build_and_cache_universe()
        print(f"universe: {u['meta']['count']} common stocks -> {u['meta']}")
        s = build_and_cache_seed()
        print(f"liquid seed: {s['count']} symbols (yfinance screeners)")
        return

    if args.rank_liquid:
        ranked, total = rank_liquid_from_metrics(top_n=args.top)
        print(f"liquid ranking: {len(ranked)} of {total} symbols with metrics")
        for i, r in enumerate(ranked[:20]):
            print(f"  {i+1:3d} {r['symbol']:8s} ${r.get('avg_dollar_volume_20d',0):,.0f} "
                  f"({r.get('nbars')} bars, close={r.get('last_close')})")
        return

    u = load_cached_universe()
    print(f"universe: {u['meta']['count']} common stocks (cached)")
    print("sample:", [s['symbol'] for s in u['symbols'][:10]])


if __name__ == "__main__":
    main()
