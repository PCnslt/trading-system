"""Bar-by-bar Connors RSI(2) mean-reversion engine — long-only equities.

Honest fill model (per trading-backtest-validation / trading-edge-validation skills):
  * ENTRY: signal computed at bar t close -> enter at bar t+1 OPEN (no lookahead).
    Signal = RSI(2) < threshold AND close > SMA200.
  * STOP: intraday GTC. If open gaps through stop -> fill at open; elif low <= stop
    -> fill at stop. One entry OR exit per bar.
  * SIGNAL EXITS: close-based (time stop, revert close>SMA5, RSI2>70) -> fill at close.
  * One open position per symbol (no pyramiding). Force-close at end-of-data (reason='end').

Costs are NOT applied here: raw entry/exit prices are recorded, and bps-per-side
slippage is post-applied in the analysis layer (single run, multiple cost levels).

Exit priority (owner spec): hard/trailing stop -> 5-day time stop -> revert
(close > SMA5) OR RSI2 > 70.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

THRESHOLDS = (2, 5, 10)
STOP_MODES = ("fixed", "trail")
MAX_HOLD = 5          # force-close at close of the 5th trading day after entry
STOP_ATR = 2.0        # initial hard stop = entry - 2*ATR(entry bar)
TRAIL_ATR = 1.0       # trailing ratchet distance = 1*ATR below highest close


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add rsi2, sma200, sma5, atr14. Assumes df has open/high/low/close (lowercase)."""
    d = df.copy()
    close = d["close"]
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder RSI, period 2
    avg_gain = gain.ewm(alpha=1 / 2, adjust=False, min_periods=2).mean()
    avg_loss = loss.ewm(alpha=1 / 2, adjust=False, min_periods=2).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    d["rsi2"] = (100 - 100 / (1 + rs)).fillna(100.0)
    d["sma200"] = close.rolling(200).mean()
    d["sma5"] = close.rolling(5).mean()
    # Wilder ATR, period 14
    prev_close = close.shift(1)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - prev_close).abs(),
        (d["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    d["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    return d


def _stop_exit(d: pd.DataFrame, entry_i: int, entry_price: float,
               stop_mode: str) -> tuple:
    """Walk bars from entry_i forward; return (exit_i, exit_price, reason).

    Returns exit index and price for the FIRST triggering rule, or
    (last_index, close, 'end') if nothing fires before end-of-data.
    """
    n = len(d)
    o = d["open"].to_numpy()
    h = d["high"].to_numpy()
    l = d["low"].to_numpy()
    c = d["close"].to_numpy()
    rsi2 = d["rsi2"].to_numpy()
    sma5 = d["sma5"].to_numpy()
    atr14 = d["atr14"].to_numpy()

    atr_entry = atr14[entry_i]
    stop = entry_price - STOP_ATR * atr_entry          # initial hard stop
    highest_close = c[entry_i]

    for i in range(entry_i, n):
        # 1) trailing ratchet (tighten only), before checking the bar's stop
        if stop_mode == "trail" and i > entry_i:
            highest_close = max(highest_close, c[i - 1])
            cand = highest_close - TRAIL_ATR * atr14[i]
            if cand > stop:
                stop = cand
        # 2) intraday GTC stop (gap-aware)
        if l[i] <= stop:
            fill = o[i] if o[i] < stop else stop      # gap-through -> open
            return i, float(fill), "stop"
        # 3) time stop
        if i - entry_i >= MAX_HOLD:
            return i, float(c[i]), "time"
        # 4) revert / overbought signal exit
        if c[i] > sma5[i] or rsi2[i] > 70.0:
            return i, float(c[i]), "revert"
    # force-close at end of data
    return n - 1, float(c[n - 1]), "end"


def run_symbol(d: pd.DataFrame, symbol: str, thr: int, stop_mode: str) -> list:
    """Generate trades for one symbol. Returns list of dicts."""
    d = indicators(d)
    n = len(d)
    o = d["open"].to_numpy()
    c = d["close"].to_numpy()
    rsi2 = d["rsi2"].to_numpy()
    sma200 = d["sma200"].to_numpy()

    trades = []
    warmup = 200
    i = warmup
    while i < n - 1:
        # flat: check signal at bar i close, enter at bar i+1 open
        if rsi2[i] < thr and c[i] > sma200[i] and not np.isnan(sma200[i]):
            entry_i = i + 1
            entry_price = float(o[entry_i])
            if entry_price > 0 and not np.isnan(entry_price):
                exit_i, exit_price, reason = _stop_exit(d, entry_i, entry_price, stop_mode)
                trades.append({
                    "symbol": symbol,
                    "entry_date": d.index[entry_i],
                    "entry_i": entry_i,
                    "entry_price": entry_price,
                    "exit_date": d.index[exit_i],
                    "exit_i": exit_i,
                    "exit_price": exit_price,
                    "reason": reason,
                    "hold_days": int(exit_i - entry_i),
                })
                i = exit_i + 1   # next bar after exit; flat again
                continue
        i += 1
    return trades
