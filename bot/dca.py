"""DCA base layer — $25/week, 50/50 SPY:QQQ, fractional.

Computes a BUY ORDER PLAN (symbol, dollars, shares) from current prices. NO order
placement — execution happens on the laptop Robinhood MCP (this VPS has no Robinhood
access). Idempotent: safe to re-run the same day; DynamoDB (pk=DCA#PLAN, sk=YYYY-MM-DD)
is overwritten with the same logical plan (prices may drift slightly between runs, but a
plan is not an execution — no side effects beyond the log).

Config lives at the top of this file.
"""
import os
import time
import datetime as dt

import yfinance as yf
import pandas as pd
import boto3
from dotenv import load_dotenv

load_dotenv()

# ===== config =====
AMOUNT = 25.0                          # total dollars per contribution
ALLOCATION = {'SPY': 0.5, 'QQQ': 0.5}  # symbol -> fraction of AMOUNT (must sum to ~1.0)
FREQUENCY = 'weekly'                   # informational only
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')


def fetch_prices(symbols):
    """Return {symbol: last_close} via yfinance. Fails loud on empty data."""
    prices = {}
    for sym in symbols:
        df = yf.download(sym, period='5d', interval='1d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty or df['Close'].dropna().empty:
            raise RuntimeError(f"no price data for {sym}")
        prices[sym] = float(df['Close'].dropna().iloc[-1])
    return prices


def build_plan(prices):
    """Allocate AMOUNT across symbols, compute fractional shares."""
    plan = []
    for sym, frac in ALLOCATION.items():
        dollars = round(AMOUNT * frac, 2)
        price = prices[sym]
        plan.append({
            'symbol': sym,
            'dollars': dollars,
            'price': round(price, 2),
            'shares': dollars / price,
        })
    return plan


def emit(plan):
    """Print a clear, human-readable buy order plan."""
    print('=' * 62)
    print(f"DCA BUY ORDER PLAN — ${AMOUNT:.2f} total, {FREQUENCY}")
    print(f"allocation: {ALLOCATION}")
    print('=' * 62)
    print(f"{'Symbol':<8} {'Dollars':>9} {'Price':>10} {'Shares':>12}")
    print('-' * 62)
    for r in plan:
        print(f"{r['symbol']:<8} ${r['dollars']:>8.2f} {r['price']:>9.2f} {r['shares']:>11.6f}")
    print('-' * 62)
    total = sum(r['dollars'] for r in plan)
    print(f"{'TOTAL':<8} ${total:>8.2f}")
    print()
    print('NOTE: PLAN ONLY — no orders placed. Execute on the laptop Robinhood MCP.')


def log_dynamo(plan, date_str):
    """Persist the plan to DynamoDB single-table (pk/sk). Values stored as strings."""
    items = [{
        'symbol': r['symbol'],
        'dollars': str(r['dollars']),
        'price': str(r['price']),
        'shares': str(round(r['shares'], 6)),
    } for r in plan]
    item = {
        'pk': 'DCA#PLAN',
        'sk': date_str,
        'amount': str(AMOUNT),
        'frequency': FREQUENCY,
        'allocation': str(ALLOCATION),
        'plan': items,
        'ts': int(time.time()),
    }
    dynamo = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    dynamo.put_item(Item=item)
    return item


def main():
    today = dt.date.today().isoformat()
    prices = fetch_prices(list(ALLOCATION.keys()))
    plan = build_plan(prices)
    emit(plan)

    item = log_dynamo(plan, today)
    print(f"[dca] logged plan to DynamoDB '{DYNAMO_TABLE}' (pk=DCA#PLAN, sk={today})")
    return plan


if __name__ == '__main__':
    main()
