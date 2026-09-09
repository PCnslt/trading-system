"""Fetch SPY 1-min RTH bars from live IBKR gateway (clientId 90, readonly) for 2026-06..2026-09.
Matches the real (non-flat) ES 1-min window in the lake. Saves to local parquet.
"""
import os, sys, time
sys.path.insert(0, '/home/ubuntu/trading-system')
os.environ['PYTHONWARNINGS'] = 'ignore'
from ib_insync import IB, Stock, util
import pandas as pd

ib = IB()
ib.connect('127.0.0.1', 4001, clientId=90, timeout=25, readonly=True)
print('accounts:', ib.managedAccounts())

c = Stock('SPY', 'SMART', 'USD')
allbars = []
# monthly chunks (1-min RTH)
for end in ['20260630 23:59:59', '20260731 23:59:59', '20260831 23:59:59', '20260909 23:59:59']:
    try:
        b = ib.reqHistoricalData(c, endDateTime=end, durationStr='31 D',
                                 barSizeSetting='1 min', whatToShow='TRADES',
                                 useRTH=True, formatDate=1)
        if b:
            allbars += b
            print(f'end={end}: {len(b)} bars')
        time.sleep(1)
    except Exception as e:
        print(f'end={end}: ERR {e!r}')

ib.disconnect()
if not allbars:
    print('NO BARS'); sys.exit(1)

df = util.df(allbars)
df['date'] = pd.to_datetime(df['date'])
df = df[['date','open','high','low','close','volume']].drop_duplicates(subset='date').sort_values('date')
print('total rows:', len(df), 'range:', df['date'].min(), '..', df['date'].max())
df.to_parquet('/home/ubuntu/trading-system/research/atomics/spy_1min_2026.parquet')
print('saved.')
