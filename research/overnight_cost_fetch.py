#!/usr/bin/env python3
"""READ-ONLY: fetch IBKR 5-min TRADES bars (useRTH=False) for a sub-$50 sample.

No orders. No DynamoDB writes. Writes one JSON per symbol to
research/overnight_bars/<SYM>.json so a timeout never loses progress.

IBKR entitlement note (measured 2026-08-25 on LIVE U26949861):
  - whatToShow='TRADES'  useRTH=False -> WORKS (04:00-20:00 ET coverage)
  - whatToShow='BID_ASK' -> Error 162 "No market data permissions" (blocked)
  - whatToShow='MIDPOINT' -> Error 162 (blocked)
  - NO bars exist for 20:00-04:00 ET (the true overnight/24h session)
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ib_insync import IB, Stock

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'overnight_bars')
os.makedirs(OUT, exist_ok=True)

SAMPLE = [
    # liquid sub-$50 large/mid caps
    'F', 'T', 'PFE', 'SOFI', 'NOK', 'KVUE', 'WBD', 'CMCSA', 'HBAN', 'KHC',
    'BP', 'VALE', 'AAL', 'CCL', 'LUV', 'TEVA', 'GRAB', 'SIRI', 'RIVN', 'LCID',
    # speculative / retail small caps (same universe, thinner)
    'SNAP', 'MARA', 'RIOT', 'PLUG', 'IONQ', 'OPEN', 'HL', 'CDE', 'WULF', 'APLD',
    'RGTI', 'QBTS', 'SOUN', 'ACHR', 'JOBY', 'CLSK',
]

DURATION = os.getenv('OC_DURATION', '20 D')
BARSIZE = os.getenv('OC_BARSIZE', '5 mins')
PACE_S = float(os.getenv('OC_PACE_S', '11'))


def main():
    ib = IB()
    ib.connect('127.0.0.1', 4001, clientId=int(os.getenv('OC_CLIENT_ID', '141')),
               timeout=30, readonly=True)
    print('accounts', ib.managedAccounts(), flush=True)
    for i, sym in enumerate(SAMPLE):
        path = os.path.join(OUT, f'{sym}.json')
        if os.path.exists(path) and os.path.getsize(path) > 200:
            print(f'[{i}] {sym} cached', flush=True)
            continue
        rec = {'symbol': sym, 'source': 'ibkr_reqHistoricalData',
               'whatToShow': 'TRADES', 'useRTH': False,
               'duration': DURATION, 'barSize': BARSIZE, 'bars': [], 'error': None}
        try:
            c = Stock(sym, 'SMART', 'USD')
            q = ib.qualifyContracts(c)
            if not q:
                rec['error'] = 'qualify_failed'
            else:
                rec['conId'] = c.conId
                rec['primaryExchange'] = c.primaryExchange
                bars = ib.reqHistoricalData(c, endDateTime='', durationStr=DURATION,
                                            barSizeSetting=BARSIZE, whatToShow='TRADES',
                                            useRTH=False, formatDate=1, timeout=180)
                rec['bars'] = [{'t': b.date.isoformat(), 'o': b.open, 'h': b.high,
                                'l': b.low, 'c': b.close, 'v': b.volume,
                                'a': b.average, 'n': b.barCount} for b in bars]
        except Exception as e:
            rec['error'] = repr(e)
        with open(path, 'w') as f:
            json.dump(rec, f)
        print(f'[{i}] {sym} bars={len(rec["bars"])} err={rec["error"]}', flush=True)
        ib.sleep(PACE_S)
    ib.disconnect()
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
