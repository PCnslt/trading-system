"""Live trading bot — Donchian/ATR LONG-ONLY breakout, MES + MNQ (paper forward-test).

Strategy (exact port of bot/futures_scan.py `sig_donchian` long-only — the
VALIDATED edge: full-period PF 2.23/1.80, walk-forward OOS PF 2.08/2.14 on
ES/NQ, ~155 trades/ticker, MaxDD -7%/-8.5%):

  Entry : close > prior 20-day high   (h.rolling(20).max().shift(1))
          Long only. NO SMA200, NO ADX (those were the over-selective ADX
          variant — dropped; short and long-short legs collapse — dropped).
  Stop  : FIXED 2*ATR below entry, placed as GTC stop order. NOT trailed —
          trailing is NOT part of the backtested edge.
  Exits (checked in this order, close-based):
          1) 5-day time stop
          2) close <= 2*ATR stop
          3) close < prior 20-day low (opposite breakout -> exit, do not flip)

Data: yfinance ES=F / NQ=F daily (same % action as MES/MNQ).
Execution: IBKR paper (DUR193467) MES + MNQ, front-month, dynamic roll.
Logging: DynamoDB SIGNAL#<contract> / TRADE#<contract> / POSITION#<contract>.
Run daily via cron 23:00 UTC.
"""
import os
import time
import datetime as dt

import yfinance as yf
import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

from risk import RiskEngine, RiskConfig

load_dotenv()

# ===== config =====
IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
RISK_BUDGET = float(os.getenv('RISK_BUDGET', '50000'))
LIVE = os.getenv('LIVE', 'false').lower() == 'true'   # flip to true for real money

LOOKBACK = 20
STOP_ATR = 2.0
MAX_HOLD = 5

# data ticker -> execution contract. MES/MNQ are 1/10 size; % returns identical.
CONTRACTS = [
    {'data': 'ES=F', 'symbol': 'MES', 'point_value': 5.0},
    {'data': 'NQ=F', 'symbol': 'MNQ', 'point_value': 2.0},
]


# ===== indicators =====
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def compute(df):
    """Last bar's indicator values. don_hi/don_lo are PRIOR 20-day extremes
    (shift(1) — today excluded), matching futures_scan.py exactly."""
    h, l, c = df['High'], df['Low'], df['Close']
    don_hi = h.rolling(LOOKBACK).max().shift(1)
    don_lo = l.rolling(LOOKBACK).min().shift(1)
    atr = wilder_atr(h, l, c, 14)
    return pd.DataFrame({'close': c, 'don_hi': don_hi, 'don_lo': don_lo, 'atr': atr}).iloc[-1]


def entry_signal(detail):
    if not np.isnan(detail['don_hi']) and detail['close'] > detail['don_hi']:
        return True, f"close {detail['close']:.1f} > 20d-high {detail['don_hi']:.1f}"
    return False, f"close {detail['close']:.1f} <= 20d-high {detail['don_hi']:.1f}"


def exit_signal(detail, stop, held_days):
    """Close-based exits, in backtest order: time stop -> ATR stop -> breakout."""
    if held_days >= MAX_HOLD:
        return True, f"time stop ({held_days}d >= {MAX_HOLD}d)"
    if stop is not None and detail['close'] <= stop:
        return True, f"close {detail['close']:.1f} <= stop {stop:.1f}"
    if not np.isnan(detail['don_lo']) and detail['close'] < detail['don_lo']:
        return True, f"close {detail['close']:.1f} < 20d-low {detail['don_lo']:.1f}"
    return False, "hold"


# ===== contract =====
def front_month(now=None):
    """Front-month contract (YYYYMM), quarterly Mar/Jun/Sep/Dec. MES & MNQ share it."""
    now = now or dt.date.today()
    for m in (3, 6, 9, 12):
        if now.month <= m:
            return f"{now.year}{m:02d}"
    return f"{now.year + 1}03"


def held_days(df, entry_date):
    """Number of trading bars strictly after entry date."""
    if not entry_date:
        return 0
    e = pd.Timestamp(entry_date)
    idx = df.index
    if getattr(idx, 'tz', None) is not None:
        e = e.tz_localize(idx.tz)
    return int((idx > e).sum())


# ===== DynamoDB helpers =====
def log_dynamo(table, pk, sk, data):
    table.put_item(Item={'pk': pk, 'sk': sk, **data})


def get_state(table, pk, sk):
    r = table.get_item(Key={'pk': pk, 'sk': sk})
    return r.get('Item')


# ===== main =====
def main():
    dynamo = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()
    mode = 'LIVE' if LIVE else 'PAPER'

    # 1. data (fetch before IBKR so we can still log signals if connect fails)
    data = {}
    for c in CONTRACTS:
        df = yf.download(c['data'], period='2y', interval='1d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[c['symbol']] = df

    # 2. connect IBKR
    from ib_insync import IB, Future, MarketOrder, StopOrder
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=70, timeout=8)
    except Exception as e:
        print(f"[{today}] {mode} IBKR connect failed: {e}")
        return

    try:
        for c in CONTRACTS:
            sym = c['symbol']
            df = data[sym]
            if df.empty or len(df) < LOOKBACK + 5:
                print(f"[{today}] {sym}: insufficient data ({len(df)} bars)")
                continue
            detail = compute(df)

            # 3. qualify contract (front-month, dynamic roll)
            try:
                con = ib.qualifyContracts(Future(sym, front_month(), 'CME'))[0]
            except Exception as e:
                print(f"[{today}] {sym}: contract qualify failed: {e}")
                continue

            # 4. position + state
            pos = next((p.position for p in ib.positions() if p.contract.symbol == sym), 0)
            state = get_state(dynamo, f"POSITION#{sym}", 'current') or {}
            was_long = int(state.get('pos', 0)) > 0
            stop = float(state['stop']) if state.get('stop') else None
            entry_date = state.get('entry_date')
            held = held_days(df, entry_date)

            entry, ereason = entry_signal(detail)
            log_dynamo(dynamo, f"SIGNAL#{sym}", today, {
                'signal': 'LONG' if entry else ('EXIT' if was_long else 'NONE'),
                'close': str(round(detail['close'], 2)),
                'don_hi': str(round(detail['don_hi'], 2)) if not np.isnan(detail['don_hi']) else '',
                'don_lo': str(round(detail['don_lo'], 2)) if not np.isnan(detail['don_lo']) else '',
                'atr': str(round(detail['atr'], 2)),
                'pos': pos, 'held_days': held, 'reason': ereason, 'ts': int(time.time()),
            })

            if pos > 0:
                should_exit, xreason = exit_signal(detail, stop, held)
                if should_exit:
                    ib.placeOrder(con, MarketOrder('SELL', pos, tif='DAY'))
                    for o in ib.openOrders():
                        if o.contract.symbol == sym and o.order.action == 'SELL' and o.order.orderType == 'STP':
                            ib.cancelOrder(o)
                    ib.sleep(1)
                    log_dynamo(dynamo, f"TRADE#{sym}", f"{today}#{int(time.time())}", {
                        'side': 'EXIT', 'qty': pos, 'reason': xreason, 'ts': int(time.time())})
                    log_dynamo(dynamo, f"POSITION#{sym}", 'current', {
                        'pos': 0, 'stop': '0', 'entry': '0', 'entry_date': '', 'ts': int(time.time())})
                    print(f">>> {mode} {sym} EXIT {pos} ({xreason})")
                else:
                    print(f">>> {mode} {sym} hold pos={pos} held={held}d stop={stop} | "
                          f"close {detail['close']:.1f} 20d-hi {detail['don_hi']:.1f} 20d-lo {detail['don_lo']:.1f}")

            elif was_long and pos == 0:
                # state says long but IBKR is flat -> protective stop filled intraday
                log_dynamo(dynamo, f"TRADE#{sym}", f"{today}#{int(time.time())}", {
                    'side': 'EXIT', 'qty': 0, 'reason': 'stop-filled (intraday)', 'ts': int(time.time())})
                log_dynamo(dynamo, f"POSITION#{sym}", 'current', {
                    'pos': 0, 'stop': '0', 'entry': '0', 'entry_date': '', 'ts': int(time.time())})
                print(f">>> {mode} {sym} EXIT via protective stop (intraday fill)")

            elif entry:
                risk = RiskEngine(RiskConfig(risk_budget_usd=RISK_BUDGET))
                allowed, why = risk.can_enter()
                if not allowed:
                    print(f">>> {mode} {sym} blocked by risk: {why}")
                    continue
                stop = detail['close'] - STOP_ATR * detail['atr']
                size = risk.position_size(detail['close'] - stop, point_value=c['point_value'])
                if size > 0:
                    ib.placeOrder(con, MarketOrder('BUY', size, tif='DAY'))
                    ib.sleep(1)
                    ib.placeOrder(con, StopOrder('SELL', size, stop, tif='GTC'))
                    log_dynamo(dynamo, f"TRADE#{sym}", f"{today}#{int(time.time())}", {
                        'side': 'BUY', 'qty': size, 'entry': str(round(detail['close'], 2)),
                        'stop': str(round(stop, 2)), 'contract': front_month(), 'ts': int(time.time())})
                    log_dynamo(dynamo, f"POSITION#{sym}", 'current', {
                        'pos': size, 'stop': str(round(stop, 2)),
                        'entry': str(round(detail['close'], 2)),
                        'entry_date': today, 'contract': front_month(), 'ts': int(time.time())})
                    print(f">>> {mode} {sym} ENTRY: BUY {size} @ market, stop {round(stop,1)} ({ereason})")
                else:
                    print(f">>> {mode} {sym} size=0 (stop too wide for budget), skip")
            else:
                print(f"[{today}] {mode} {sym} flat, no entry ({ereason})")
    finally:
        ib.disconnect()


if __name__ == '__main__':
    main()
