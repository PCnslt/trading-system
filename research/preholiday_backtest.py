#!/usr/bin/env python3
"""Pre-holiday drift backtest (Ariel 1990 JF; Lakonishok-Smidt 1988 RFS).

Claim: the last trading session before a US market holiday earns 9-14x a normal
session's return — over 1/3 of the annual return in 1963-82. Index-level anomaly,
best traded long the broad index (SPY/QQQ/IWM, fractional on Robinhood).

Test: fetch daily bars from IBKR (read-only), mark each session where the NEXT
calendar day is a holiday, compare close-to-close return on pre-holiday sessions
vs all others. Uses pandas USFederalHolidayCalendar (approximation of NYSE market
holidays — flags Good Friday/Juneteenth imprecision).
"""
from __future__ import annotations
import sys, time
import datetime as dt
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

sys.path.insert(0, '/home/ubuntu/trading-system')
from ib_insync import IB, Stock
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

SYMS = ['SPY', 'QQQ', 'IWM']
HOLD = 1  # close-to-close one session


def main():
    ib = IB()
    ib.connect('127.0.0.1', 4001, clientId=191, timeout=25, readonly=True)
    cal = USFederalHolidayCalendar()
    hol_dates = set(d.date() for d in cal.holidays(start='2005-01-01', end='2027-12-31'))

    for sym in SYMS:
        c = Stock(sym, 'SMART', 'USD')
        ib.qualifyContracts(c)
        bars = ib.reqHistoricalData(c, endDateTime='', durationStr='20 Y',
                                    barSizeSetting='1 day', whatToShow='TRADES', useRTH=1)
        df = pd.DataFrame([{'date': (b.date.date() if hasattr(b.date, 'date') else b.date),
                            'close': b.close} for b in bars])
        df = df.dropna().reset_index(drop=True)
        df['ret'] = df['close'].pct_change()
        # a session is "pre-holiday" if the NEXT calendar day is a holiday
        df['prehol'] = df['date'].shift(-1).isin(hol_dates)
        pre = df[df['prehol'] & df['ret'].notna()]['ret']
        nrm = df[~df['prehol'] & df['ret'].notna()]['ret']
        t = (pre.mean() - nrm.mean()) / (pre.std(ddof=1) / np.sqrt(len(pre))) if len(pre) > 2 else 0
        print(f'{sym}: pre-holiday n={len(pre)} mean={pre.mean()*1e4:+.1f}bp '
              f'win={100*(pre>0).mean():.0f}%  |  normal n={len(nrm)} mean={nrm.mean()*1e4:+.1f}bp '
              f'|  excess t={t:+.2f}')
        time.sleep(0.3)
    ib.disconnect()


if __name__ == '__main__':
    main()
