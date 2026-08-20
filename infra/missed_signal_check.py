#!/usr/bin/env python3
"""Missed-signal detector — deterministic replay cross-check (index + gold).

The 08-18 failure class: a daily bot evaluated a PARTIAL/unfinalized bar (or
crashed before evaluating), stamped RUN#, and the real EOD signal was silently
lost. Two fixes now make that structurally impossible for the daily bots:
  1. mark_ran only AFTER the signal is evaluated+logged (live.py / live_gc.py).
  2. This detector: after EOD, REPLAY the deterministic signal against the
     FINALIZED close and compare to the SIGNAL# the bot actually logged.

A mismatch (replay says LONG/SHORT but the bot logged NONE, or vice-versa) is an
alert — a signal that was missed or mis-evaluated. Empty stdout = all match =
healthy (no_agent cron delivers only non-empty stdout to Telegram).

Schedule: 19:45 ET Mon-Fri (after the 19:00/19:10 EOD bots + data finalization).
"""
import os
import sys
import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
import boto3
from dotenv import load_dotenv

load_dotenv('/home/ubuntu/trading-system/.env')

NY = ZoneInfo('America/New_York')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
REGION = os.getenv('AWS_REGION', 'us-east-1')

# ---- signal constants (MUST mirror live.py / live_gc.py) ----
LOOKBACK = 20
RSI2_LO = 10.0
RSI2_TREND_SMA = 200
TSMOM_LOOKBACK = 252


def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _fetch(ticker):
    df = yf.download(ticker, period='2y', interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def replay_index(ticker):
    """Return (bar_date, desired) where desired in {'LONG', None} for Donchian/RSI2."""
    df = _fetch(ticker)
    if df is None or df.empty:
        return None, None
    h, l, c = df['High'], df['Low'], df['Close']
    don_hi = h.rolling(LOOKBACK).max().shift(1)
    r2 = rsi(c, 2)
    sma200 = c.rolling(RSI2_TREND_SMA).mean()
    close = float(c.iloc[-1])
    don = (not np.isnan(don_hi.iloc[-1])) and close > float(don_hi.iloc[-1])
    rsi2 = float(r2.iloc[-1]) < RSI2_LO and close > float(sma200.iloc[-1])
    return df.index[-1].date(), {'DONCHIAN': 'LONG' if don else None,
                                 'RSI2': 'LONG' if rsi2 else None}


def replay_gold():
    """Return (bar_date, desired) where desired in {'LONG','SHORT',None} for Donchian/TSMOM."""
    df = _fetch('GC=F')
    if df is None or df.empty:
        return None, None
    h, l, c = df['High'], df['Low'], df['Close']
    don_hi = h.rolling(LOOKBACK).max().shift(1).iloc[-1]
    don_lo = l.rolling(LOOKBACK).min().shift(1).iloc[-1]
    close = float(c.iloc[-1])
    if not np.isnan(don_hi) and close > float(don_hi):
        don = 'LONG'
    elif not np.isnan(don_lo) and close < float(don_lo):
        don = 'SHORT'
    else:
        don = None
    ret_12m = float(c.iloc[-1] / c.iloc[-TSMOM_LOOKBACK] - 1.0)
    tsmom = 'LONG' if ret_12m > 0 else ('SHORT' if ret_12m < 0 else None)
    return df.index[-1].date(), {'DONCHIAN': don, 'TSMOM': tsmom}


def main():
    table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)
    today = dt.datetime.now(NY).date().isoformat()

    # Only meaningful after the EOD bots have run (they run 19:00/19:10 ET).
    if dt.datetime.now(NY).hour < 19:
        return

    alerts = []

    # ---- index edge (live.py): MES/MNQ/MYM Donchian + RSI2 (long-only) ----
    run_marker = table.get_item(Key={'pk': 'RUN#live', 'sk': today}).get('Item')
    for ticker, sym in [('ES=F', 'MES'), ('NQ=F', 'MNQ'), ('YM=F', 'MYM')]:
        bar_date, want = replay_index(ticker)
        if bar_date is None:
            alerts.append(f"[missed-sig] {sym}: replay data fetch failed")
            continue
        if str(bar_date) != today:
            # data not finalized for today yet (or holiday); skip rather than false-alarm
            continue
        for strat in ('DONCHIAN', 'RSI2'):
            tag = f"{sym}_{strat}"
            it = table.get_item(Key={'pk': f'SIGNAL#{tag}', 'sk': today}).get('Item') or {}
            logged = it.get('signal', 'MISSING')
            pos = int(float(it.get('pos', 0) or 0))
            if logged == 'MISSING':
                if run_marker:
                    alerts.append(f"[missed-sig] {tag}: bot ran (RUN#) but NO SIGNAL# logged — missed evaluation")
                continue
            if pos > 0:
                continue  # already holding; entry signal not expected
            want_sig = want[strat]
            if want_sig == 'LONG' and logged != 'LONG':
                alerts.append(f"[missed-sig] {tag}: replay=LONG but bot logged={logged} — MISSED entry")
            elif want_sig is None and logged == 'LONG':
                alerts.append(f"[missed-sig] {tag}: replay=NONE but bot logged=LONG — spurious entry")

    # ---- gold edge (live_gc.py): MGC Donchian + TSMOM (long/short) ----
    bar_date, want = replay_gold()
    if bar_date is None:
        alerts.append("[missed-sig] GC: replay data fetch failed")
    elif str(bar_date) == today:
        for strat in ('DONCHIAN', 'TSMOM'):
            tag = f"MGC_{strat}"
            it = table.get_item(Key={'pk': f'SIGNAL#{tag}', 'sk': today}).get('Item') or {}
            logged = it.get('signal', 'MISSING')
            pos = int(float(it.get('pos', 0) or 0))
            if logged == 'MISSING':
                if run_marker or True:  # gold runs 19:10; flag missing regardless
                    alerts.append(f"[missed-sig] {tag}: NO SIGNAL# logged — missed evaluation")
                continue
            if pos > 0:
                continue
            want_sig = want[strat]
            if want_sig in ('LONG', 'SHORT') and logged not in (want_sig,):
                alerts.append(f"[missed-sig] {tag}: replay={want_sig} but bot logged={logged} — MISSED entry")
            elif want_sig is None and logged in ('LONG', 'SHORT'):
                alerts.append(f"[missed-sig] {tag}: replay=NONE but bot logged={logged} — spurious entry")

    if alerts:
        print('\n'.join(alerts))


if __name__ == '__main__':
    main()
