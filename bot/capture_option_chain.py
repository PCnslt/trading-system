#!/usr/bin/env python3
"""Point-in-time option-chain capture from IBKR -> S3. Builds our own forward
historical options database (bid/ask/IV/greeks/OI) so we are not dependent on paid data.

Usage: python bot/capture_option_chain.py [SPY QQQ IWM ...] [--dte 60]"""
import os, sys, io, json, time
import datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd
import boto3
from ib_insync import IB, Stock, Option

ET = ZoneInfo('America/New_York')
S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'
DEFAULT_UNI = ['SPY', 'QQQ', 'IWM']

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    syms = args or DEFAULT_UNI
    dte_cap = 60
    if '--dte' in sys.argv:
        dte_cap = int(sys.argv[sys.argv.index('--dte')+1])

    ib = IB()
    ib.connect('127.0.0.1', 4001, clientId=250, timeout=30, readonly=True)
    now = dt.datetime.now(ET)
    ts = now.isoformat()

    rows = []
    for sym in syms:
        try:
            stk = Stock(sym, 'SMART', 'USD')
            ib.qualifyContracts(stk)
            ib.reqMarketDataType(3)  # delayed OK for capture
            # get option params (strikes + expirations)
            cds = ib.reqSecDefOptParams(sym, '', 'STK', stk.conId)
            if not cds:
                continue
            cd = cds[0]
            expiries = [e for e in cd.expirations if (dt.datetime.strptime(e, '%Y%m%d').date() - now.date()).days <= dte_cap]
            expiries = sorted(expiries)[:6]  # nearest 6 expirations
            strikes = [s for s in cd.strikes if float(s).is_integer()]  # drop stale fractional strikes
            und = stk.conId
            # build contracts: ATM +/- 5 strikes, nearest expiries
            px = float(ib.reqMktData(stk, '', False, False).last or 0)
            if px <= 0:
                continue
            atm = min(strikes, key=lambda s: abs(s - px))
            atm_i = strikes.index(atm)
            strike_win = strikes[max(0, atm_i-5): atm_i+6]
            contracts = []
            for exp in expiries:
                for k in strike_win:
                    for right in ('C', 'P'):
                        contracts.append(Option(sym, exp, k, right, 'SMART', tradingClass=sym))
            ib.qualifyContracts(*contracts)
            tickers = ib.reqTickers(*contracts)
            for t in tickers:
                c = t.contract
                mg = t.modelGreeks
                bid, ask = t.bid, t.ask
                if bid <= 0 and ask <= 0:
                    continue
                mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else (bid or ask)
                dte = (dt.datetime.strptime(c.lastTradeDateOrContractMonth, '%Y%m%d').date() - now.date()).days
                rows.append({
                    'ts': ts, 'sym': sym, 'expiry': c.lastTradeDateOrContractMonth,
                    'strike': c.strike, 'right': c.right, 'dte': dte,
                    'bid': bid, 'ask': ask, 'mid': mid,
                    'iv': getattr(mg, 'impliedVol', None),
                    'delta': getattr(mg, 'delta', None),
                    'gamma': getattr(mg, 'gamma', None),
                    'theta': getattr(mg, 'theta', None),
                    'vega': getattr(mg, 'vega', None),
                    'volume': t.volume, 'oi': getattr(t, 'openInterest', None),
                    'und': px,
                })
            print(f"{sym}: {len(tickers)} contracts, ATM={atm}, und={px:.2f}")
        except Exception as e:
            print(f"{sym} ERROR: {e}")
    ib.disconnect()

    if rows:
        df = pd.DataFrame(rows)
        key = f"options/chain/capture_{now.strftime('%Y%m%d_%H%M')}.parquet"
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        S3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
        print(f"SAVED {len(df)} rows -> s3://{BUCKET}/{key}")
    else:
        print("no data captured")

if __name__ == '__main__':
    main()
