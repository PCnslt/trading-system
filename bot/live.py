"""Live trading bot — daily MES trend breakout, VPS-ready (24/7).

Data: yfinance ES=F (free, consistent with backtest) — runs anywhere.
Execution: IBKR paper (MES micro) — connects only when a signal fires.
Logging: DynamoDB (signals + fills) + S3 archive.

Run daily via cron. Portable: IBKR_HOST/PORT via env.
"""
import os
import json
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

TICKER = 'ES=F'          # E-mini S&P (data) — same price action as MES
TRADE_SYMBOL = 'MES'     # micro (execution)


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


def signal(detail):
    """Return 'LONG' / 'NONE' + a reason string."""
    if detail['close'] > detail['don_hi'] and detail['close'] > detail['sma200'] and detail['adx'] > 25:
        return 'LONG', f"breakout {round(detail['close'],1)} > {round(detail['don_hi'],1)} & ADX {detail['adx']:.1f}>25"
    return 'NONE', f"close {round(detail['close'],1)} | ADX {detail['adx']:.1f} | don_hi {round(detail['don_hi'],1)} | sma200 {round(detail['sma200'],1)}"


def log_dynamo(table, pk, sk, data):
    table.put_item(Item={'pk': pk, 'sk': sk, **data})


def main():
    dynamo = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)

    # 1. data (yfinance — free, works on VPS)
    df = yf.download(TICKER, period='2y', interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        print("no data"); return
    detail = compute(df)
    sig, reason = signal(detail)
    today = dt.date.today().isoformat()

    print(f"[{today}] signal={sig} | {reason}")

    # 2. log signal to data lake
    log_dynamo(dynamo, f"SIGNAL#{TICKER}", today, {
        'signal': sig, 'close': str(round(detail['close'], 2)),
        'adx': str(round(detail['adx'], 2)), 'reason': reason,
        'ts': int(time.time()),
    })

    # 3. act if signal (IBKR execution — only when needed)
    if sig == 'LONG':
        risk = RiskEngine(RiskConfig(risk_budget_usd=RISK_BUDGET))
        allowed, why = risk.can_enter()
        if not allowed:
            print(f">>> blocked by risk: {why}"); return
        try:
            from ib_insync import IB, Future, MarketOrder
            ib = IB()
            ib.connect(IBKR_HOST, IBKR_PORT, clientId=70, timeout=8)
            mes = ib.qualifyContracts(Future(TRADE_SYMBOL, '202609', 'CME'))[0]
            stop = detail['close'] - 2 * detail['atr']
            size = risk.position_size(detail['close'] - stop, point_value=5.0)
            if size > 0:
                ib.placeOrder(mes, MarketOrder('BUY', size))
                print(f">>> PAPER ORDER: BUY {size} MES @ market (stop ~{round(stop,1)})")
                ib.sleep(2)
                risk.record_fill()
                log_dynamo(dynamo, f"TRADE#{TRADE_SYMBOL}", today, {
                    'side': 'BUY', 'qty': size, 'entry': str(round(detail['close'], 2)),
                    'stop': str(round(stop, 2)), 'ts': int(time.time()),
                })
            ib.disconnect()
        except Exception as e:
            print(f">>> IBKR unavailable (signal logged, no order): {e}")
            log_dynamo(dynamo, f"TRADE#{TRADE_SYMBOL}", today, {
                'side': 'BUY', 'status': 'SKIPPED_IBKR_DOWN', 'reason': str(e)[:80],
                'ts': int(time.time()),
            })


if __name__ == '__main__':
    main()
