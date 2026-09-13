#!/usr/bin/env python
"""Fetch daily adjusted closes for S&P 500 ADDED names + SPY benchmark, cache to parquet."""
import json, datetime, os, re, time, sys
import yfinance as yf
import pandas as pd

CACHE = "/home/ubuntu/trading-system/research/index_recon/cache"
os.makedirs(CACHE, exist_ok=True)

changes = json.load(open("/tmp/sp500_changes.json"))
adds = [c for c in changes if c["add_ticker"] and c["eff_d"]]

def clean_tk(tk):
    return re.sub(r"[^A-Z0-9.\-]", "", tk.upper().strip())

# Build event list
events = []
for c in adds:
    tk = clean_tk(c["add_ticker"])
    if not tk:
        continue
    eff = datetime.date.fromisoformat(c["eff_d"])
    if eff.year < 1998:  # focus 1998+ for price data (yfinance depth)
        continue
    ann = datetime.date.fromisoformat(c["ann_d"]) if c["ann_d"] else None
    events.append(dict(ticker=tk, eff=eff, ann=ann,
                       add_sec=c["add_sec"], reason=c["reason"]))

print(f"events 1998+ : {len(events)}")
tickers = sorted(set(e["ticker"] for e in events))
print(f"unique tickers: {len(tickers)}")

def fetch(tk, start="1997-01-01"):
    path = os.path.join(CACHE, f"{tk}.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    try:
        t = yf.Ticker(tk)
        h = t.history(start=start, auto_adjust=True, actions=False)
        if h is None or h.empty:
            return None
        # keep only Close (adjusted)
        s = h[["Close"]].rename(columns={"Close": "adjclose"})
        s.index = pd.to_datetime(s.index).tz_localize(None)
        s = s[~s.index.duplicated(keep="last")]
        s.to_parquet(path)
        return s
    except Exception as e:
        print(f"  FAIL {tk}: {type(e).__name__} {e}", flush=True)
        return None

# SPY benchmark
spy = fetch("SPY")
print("SPY rows", len(spy), spy.index[0].date(), spy.index[-1].date())

# fetch all tickers with progress + throttling
ok = 0
fail = []
t0 = time.time()
for i, tk in enumerate(tickers):
    s = fetch(tk)
    if s is not None and len(s) > 0:
        ok += 1
    else:
        fail.append(tk)
    if (i + 1) % 25 == 0:
        print(f"  {i+1}/{len(tickers)} ok={ok} fail={len(fail)} elapsed={time.time()-t0:.0f}s", flush=True)
        time.sleep(1.0)

print(f"DONE ok={ok} fail={len(fail)}")
print("FAILED:", fail)
# save events
json.dump(events, open("/home/ubuntu/trading-system/research/index_recon/events.json", "w"), indent=1, default=str)
print("events saved")
