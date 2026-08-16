#!/usr/bin/env python
"""Fetch yfinance split+dividend-adjusted daily OHLCV for the fixed stock-MR universe.

Universe = S&P 100 constituents (Wikipedia, ~100) ranked by avg dollar volume
(20d, from data_engine daily metrics), top-50, dropping GOOG (Alphabet dual
class, keep GOOGL) and adding rank-51 BKNG. Deterministic liquidity rule —
NOT cherry-picked by past returns.
"""
import json
import time
import pandas as pd
import yfinance as yf

# Build universe deterministically from the ranked S&P100 list.
ranked = json.load(open("/tmp/sp100_ranked.json"))  # sorted desc by dv20d
UNIVERSE = [s for s in ranked if s != "GOOG"][:50]
assert len(UNIVERSE) == 50, len(UNIVERSE)
print(f"Universe ({len(UNIVERSE)}): {UNIVERSE}")

# Fetch adjusted daily (split + dividend adjusted = total return, matches the
# equities-lane convention). period='max' gives deep history for old names.
def fetch():
    ok, failed = {}, []
    for i, sym in enumerate(UNIVERSE):
        for attempt in range(3):
            try:
                df = yf.download(sym, period="max", interval="1d",
                                 auto_adjust=True, progress=False)
                if df is None or df.empty:
                    raise RuntimeError("empty")
                # flatten MultiIndex columns if present
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                df.columns = [c.lower() for c in df.columns]
                df.index = pd.to_datetime(df.index).tz_localize(None)
                df = df[~df.index.duplicated(keep="last")].sort_index()
                df = df[df["close"].notna() & (df["close"] > 0)]
                if len(df) < 200:
                    raise RuntimeError(f"only {len(df)} bars")
                ok[sym] = df
                print(f"[{i+1:2d}/{len(UNIVERSE)}] {sym:6s} {len(df):5d} bars "
                      f"{df.index.min().date()} -> {df.index.max().date()} "
                      f"close={df['close'].iloc[-1]:.2f}")
                break
            except Exception as e:
                if attempt == 2:
                    failed.append((sym, str(e)))
                else:
                    time.sleep(2)
    return ok, failed

ok, failed = fetch()
print(f"\nfetched {len(ok)} / {len(UNIVERSE)}; failed {failed}")

# Persist to a pickle (gitignored local cache) + a manifest.
out = pd.concat(ok, names=["symbol", "date"])
out.to_pickle("/tmp/stock_mr_ohlcv.pkl")
json.dump({"universe": list(ok.keys()), "failed": failed,
           "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
          open("/tmp/stock_mr_manifest.json", "w"), indent=2)
print("saved /tmp/stock_mr_ohlcv.pkl")
for s, df in ok.items():
    print(f"  {s}: {df.index.min().date()} -> {df.index.max().date()}, {len(df)} bars")
