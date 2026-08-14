"""Live trading bot — daily MES trend breakout, VPS-ready (24/7).

Strategy (matches backtest: long-only + trailing + ADX>25, PF 2.73):
  Entry  : close > 20-day high AND close > SMA200 AND ADX > 25
  Stop   : trailing 2*ATR (moved up daily, never down)
  Exit   : close < SMA200 (trend broken) -> close position

Data: yfinance ES=F (free). Execution: IBKR (paper MES, micro).
Logging: DynamoDB (signals + trades + position state). S3 archive.

Run daily via cron. Portable: IBKR_HOST/PORT via env.
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
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
RISK_BUDGET = float(os.getenv('RISK_BUDGET', '50000'))
LIVE = os.getenv('LIVE', 'false').lower() == 'true'   # flip to true for real money

TICKER = 'ES=F'          # data ticker (same price action as MES)
TRADE_SYMBOL = 'MES'     # execution (micro E-mini)
POINT_VALUE = 5.0        # $5 / point for MES
STOP_ATR = 2.0
ADX_MIN = 25


# ===== indicators =====
def compute(df):
    h, l, c = df['High'], df['Low'], df['Close']
    sma200 = c.rolling(200).mean()
    don_hi = h.rolling(20).max().shift(1)
    atr = _wilder_atr(h, l, c, 14)
    adx = _adx(h, l, c, 14)
    return pd.DataFrame({
        'close': c, 'sma200': sma200, 'don_hi': don_hi, 'atr': atr, 'adx': adx,
    }).iloc[-1]


def _wilder_atr(h, l, c, n):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _adx(h, l, c, n=14):
    up = h.diff().to_numpy()
    dn = (-l.diff()).to_numpy()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = _wilder_atr(h, l, c, n)
    idx = h.index
    plus_di = 100 * pd.Series(plus_dm, index=idx).ewm(alpha=1 / n, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=idx).ewm(alpha=1 / n, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def entry_signal(detail):
    if detail['close'] > detail['don_hi'] and detail['close'] > detail['sma200'] and detail['adx'] > ADX_MIN:
        return True, f"breakout {round(detail['close'],1)} > {round(detail['don_hi'],1)} & ADX {detail['adx']:.1f}>25"
    return False, f"close {round(detail['close'],1)} | ADX {detail['adx']:.1f} | don_hi {round(detail['don_hi'],1)}"


def exit_signal(detail):
    return detail['close'] < detail['sma200'], f"close {round(detail['close'],1)} < SMA200 {round(detail['sma200'],1)}"


# ===== contract =====
def front_month(now=None):
    """Front-month MES contract (YYYYMM). Rolls quarterly Mar/Jun/Sep/Dec."""
    now = now or dt.date.today()
    for m in (3, 6, 9, 12):
        if now.month <= m:
            return f"{now.year}{m:02d}"
    return f"{now.year + 1}03"


# ===== DynamoDB helpers =====
def log_dynamo(table, pk, sk, data):
    table.put_item(Item={'pk': pk, 'sk': sk, **data})


def get_state(table, pk, sk):
    r = table.get_item(Key={'pk': pk, 'sk': sk})
    return r.get('Item')


# ===== main =====
def main():
    dynamo = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)

    # 1. data
    df = yf.download(TICKER, period='2y', interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        print("no data"); return
    detail = compute(df)
    today = dt.date.today().isoformat()
    mode = 'LIVE' if LIVE else 'PAPER'

    # 2. connect IBKR
    from ib_insync import IB, Future, MarketOrder, StopOrder
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=70, timeout=8)
    except Exception as e:
        print(f"[{today}] {mode} IBKR connect failed: {e}")
        return
    try:
        mes = ib.qualifyContracts(Future(TRADE_SYMBOL, front_month(), 'CME'))[0]
    except Exception as e:
        print(f"[{today}] contract qualify failed: {e}"); ib.disconnect(); return

    # 3. current position (source of truth)
    pos = next((p.position for p in ib.positions() if p.contract.symbol == TRADE_SYMBOL), 0)
    state = get_state(dynamo, f"POSITION#{TRADE_SYMBOL}", 'current')
    stop_level = float(state['stop']) if state and state.get('stop') else None

    print(f"[{today}] {mode} pos={pos} stop={stop_level} | {detail['close']:.1f} ADX {detail['adx']:.1f}")

    # log signal
    entry, reason = entry_signal(detail)
    log_dynamo(dynamo, f"SIGNAL#{TICKER}", today, {
        'signal': 'LONG' if entry else 'NONE', 'close': str(round(detail['close'], 2)),
        'adx': str(round(detail['adx'], 2)), 'reason': reason, 'ts': int(time.time()),
    })

    # 4. manage open position
    if pos > 0:
        exit_sig, ereason = exit_signal(detail)
        if exit_sig:
            # close position + cancel stop
            ib.placeOrder(mes, MarketOrder('SELL', pos, tif='DAY'))
            for o in ib.openOrders():
                if o.order.action == 'SELL' and o.order.orderType == 'STP':
                    ib.cancelOrder(o.order)
            ib.sleep(2)
            log_dynamo(dynamo, f"TRADE#{TRADE_SYMBOL}", today, {
                'side': 'EXIT', 'qty': pos, 'reason': ereason, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{TRADE_SYMBOL}", 'current', {
                'pos': 0, 'stop': '0', 'entry': '0', 'ts': int(time.time())})
            print(f">>> {mode} EXIT {pos} MES ({ereason})")
        else:
            # trail stop up: new = max(current, close - 2*ATR)
            new_stop = detail['close'] - STOP_ATR * detail['atr']
            if stop_level is None or new_stop > stop_level:
                for o in ib.openOrders():
                    if o.order.action == 'SELL' and o.order.orderType == 'STP':
                        ib.cancelOrder(o.order)
                ib.placeOrder(mes, StopOrder('SELL', pos, new_stop, tif='GTC'))
                log_dynamo(dynamo, f"POSITION#{TRADE_SYMBOL}", 'current', {
                    'pos': pos, 'stop': str(round(new_stop, 2)), 'ts': int(time.time())})
                print(f">>> {mode} trailing stop -> {round(new_stop,1)}")
            else:
                print(f">>> {mode} hold, stop unchanged @ {round(stop_level,1)}")
    # 5. entry
    elif entry:
        risk = RiskEngine(RiskConfig(risk_budget_usd=RISK_BUDGET))
        allowed, why = risk.can_enter()
        if not allowed:
            print(f">>> blocked by risk: {why}"); ib.disconnect(); return
        stop = detail['close'] - STOP_ATR * detail['atr']
        size = risk.position_size(detail['close'] - stop, point_value=POINT_VALUE)
        if size > 0:
            ib.placeOrder(mes, MarketOrder('BUY', size, tif='DAY'))
            ib.sleep(2)
            ib.placeOrder(mes, StopOrder('SELL', size, stop, tif='GTC'))
            log_dynamo(dynamo, f"TRADE#{TRADE_SYMBOL}", today, {
                'side': 'BUY', 'qty': size, 'entry': str(round(detail['close'], 2)),
                'stop': str(round(stop, 2)), 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{TRADE_SYMBOL}", 'current', {
                'pos': size, 'stop': str(round(stop, 2)), 'entry': str(round(detail['close'], 2)),
                'ts': int(time.time())})
            print(f">>> {mode} ENTRY: BUY {size} MES @ market, stop {round(stop,1)} ({reason})")

    ib.disconnect()


if __name__ == '__main__':
    main()
