"""Live paper-trading loop — MES trend breakout on IBKR paper.

Portable: laptop (now) → VPS (24/7) by changing IBKR host/port via env.
Reuses the risk engine (risk.py). Logs signals + fills to the data lake.
"""
import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from ib_insync import IB, Future, Stock, LimitOrder, MarketOrder

sys.path.insert(0, os.path.dirname(__file__))
from risk import RiskEngine, RiskConfig

# ===== CONFIG (env-overridable) =====
IBKR_HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.environ.get("IBKR_PORT", "4002"))
IBKR_ACCOUNT = os.environ.get("IBKR_ACCOUNT", "DUR193467")
MES_CONTRACT = ("MES", "202609", "CME")  # symbol, expiry, exchange
RISK_BUDGET = float(os.environ.get("RISK_BUDGET", "50000"))

# ===== INDICATORS =====
def wilder_atr(df, n=14):
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift()).abs(),
        (df['Low'] - df['Close'].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def adx(df, n=14):
    up = df['High'].diff()
    dn = -df['Low'].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = wilder_atr(df, n)
    atr = tr.replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/n, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/n, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()

def compute_signal(df):
    """Returns (signal, detail) for the latest bar. signal in {'LONG','EXIT','NONE'}."""
    close = df['Close']
    sma200 = close.rolling(200).mean()
    don_hi = df['High'].shift(1).rolling(20).max()
    adx_v = adx(df, 14)
    atr_v = wilder_atr(df, 14)

    trend_up = close.iloc[-1] > sma200.iloc[-1]
    trending = adx_v.iloc[-1] > 25
    breakout = close.iloc[-1] > don_hi.iloc[-1] and close.iloc[-2] <= don_hi.iloc[-2]

    detail = {
        'close': round(close.iloc[-1], 2), 'sma200': round(sma200.iloc[-1], 2),
        'don_hi': round(don_hi.iloc[-1], 2), 'adx': round(adx_v.iloc[-1], 1),
        'atr': round(atr_v.iloc[-1], 2), 'trend_up': bool(trend_up), 'trending': bool(trending),
    }
    if trend_up and trending and breakout:
        return 'LONG', detail
    if close.iloc[-1] < sma200.iloc[-1]:
        return 'EXIT', detail
    return 'NONE', detail

def main():
    risk = RiskEngine(RiskConfig(risk_budget_usd=RISK_BUDGET))
    ib = IB()
    ib.connect(IBKR_HOST, IBKR_PORT, clientId=60, timeout=10)
    print(f"connected to IBKR {IBKR_HOST}:{IBKR_PORT} (acct {IBKR_ACCOUNT})")

    mes = ib.qualifyContracts(Future(*MES_CONTRACT))[0]
    bars = ib.reqHistoricalData(mes, '', '2 Y', '1 day', 'TRADES', False, 1)
    df = pd.DataFrame([{ 'Date': b.date, 'Open': b.open, 'High': b.high, 'Low': b.low, 'Close': b.close, 'Volume': b.volume } for b in bars]).set_index('Date')
    df = df.dropna()
    print(f"bars: {len(df)} (last close {df['Close'].iloc[-1]})")

    signal, detail = compute_signal(df)
    print("signal:", signal)
    for k, v in detail.items():
        print(f"  {k}: {v}")

    # ===== current position =====
    positions = ib.positions()
    mes_pos = next((p for p in positions if p.contract.symbol == 'MES'), None)
    pos_qty = int(mes_pos.position) if mes_pos else 0
    print(f"current MES position: {pos_qty}")

    # ===== act =====
    if signal == 'LONG' and pos_qty <= 0:
        allowed, reason = risk.can_enter()
        if allowed:
            stop = detail['close'] - 2 * detail['atr']
            stop_distance = detail['close'] - stop
            size = risk.position_size(stop_distance, point_value=5.0)
            if size > 0:
                order = MarketOrder('BUY', size)
                ib.placeOrder(mes, order)
                print(f">>> PAPER ORDER: BUY {size} MES @ market (stop ~{round(stop,1)})")
                ib.sleep(2)
                risk.record_fill()
            else:
                print(">>> size=0 (stop too tight) — no order")
        else:
            print(f">>> blocked by risk: {reason}")
    elif signal == 'EXIT' and pos_qty > 0:
        order = MarketOrder('SELL', pos_qty)
        trade = ib.placeOrder(mes, order)
        print(f">>> PAPER ORDER: SELL {pos_qty} MES @ market (trend break exit)")
        ib.sleep(2)
    else:
        print(f">>> no action (signal={signal}, pos={pos_qty})")

    ib.disconnect()
    print("done")

if __name__ == '__main__':
    main()
