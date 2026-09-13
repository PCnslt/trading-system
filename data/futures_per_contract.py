import json, time, io, boto3, pandas as pd, numpy as np
from ib_insync import IB, Future, util

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'

# Underlying -> (exchange, months, micro-of)
UND = {
    'ES':  ('CME', 'HMUZ', None),     # quarterly
    'MES': ('CME', 'HMUZ', None),     # micro ES, quarterly
    'CL':  ('NYMEX', 'FGHJKMNQUVXZ', None),  # monthly
    'MCL': ('NYMEX', 'FGHJKMNQUVXZ', None),  # micro crude
    'GC':  ('NYMEX', 'GJMQVZ', None),        # bimonthly (Feb/Apr/Jun/Aug/Oct/Dec)
    'MGC': ('NYMEX', 'GJMQVZ', None),        # micro gold
}

MONTH_CODE = {'F':1,'G':2,'H':3,'J':4,'K':5,'M':6,'N':7,'Q':8,'U':9,'V':10,'X':11,'Z':12}

def contract_months(schedule: str, start_yr: int, end_yr: int):
    out = []
    for y in range(start_yr, end_yr + 1):
        for c in schedule:
            m = MONTH_CODE[c]
            out.append((y, m, c))
    out.sort(key=lambda t: (t[0], t[1]))
    return out

def fetch_contract(ib, sym, exch, y, m, code, bar='1 day', dur='1 Y'):
    c = Future(sym, f'{y}{m:02d}', exch)
    try:
        b = ib.reqHistoricalData(c, '', dur, bar, 'TRADES', useRTH=False, formatDate=1)
    except Exception:
        return None
    if not b:
        return None
    df = util.df(b)
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date')[['open','high','low','close','volume']]

ib = IB(); ib.connect('127.0.0.1', 4001, clientId=99, timeout=20)

report = []
for sym, (exch, schedule, _) in UND.items():
    # discover contracts over the last ~4 years
    months = contract_months(schedule, 2022, 2026)
    contracts = {}
    for (y, m, code) in months:
        df = fetch_contract(ib, sym, exch, y, m, code)
        if df is not None and len(df) > 5:
            flat = ((df['open']==df['high'])&(df['high']==df['low'])&(df['low']==df['close'])).mean()
            contracts[f'{y}{m:02d}'] = df
            print(f'{sym} {y}{m:02d}: {len(df)} bars, flat={flat:.2f}, range={df.index.min().date()}..{df.index.max().date()}', flush=True)
            time.sleep(0.2)
    # store raw + build front/second term structure
    if contracts:
        allm = sorted(contracts.keys())
        oldest = min(df.index.min() for df in contracts.values())
        report.append(dict(sym=sym, contracts=len(contracts), oldest=str(oldest.date()),
                           months=sorted(allm)))
        # raw store (canonical, never adjusted)
        for mth, df in contracts.items():
            buf = io.BytesIO(); df.to_parquet(buf)
            s3.put_object(Bucket=B, Key=f'ibkr/futures/raw/{sym}/{mth}.parquet', Body=buf.getvalue())
        # term structure: front vs second (contemporaneous raw close)
        ts = []
        for mth in allm:
            ts.append(contracts[mth]['close'].rename(mth))
        curve = pd.concat(ts, axis=1).sort_index()
        curve.to_parquet('curve_'+sym+'.parquet')
        print(f'  -> stored raw + curve for {sym} (oldest {oldest.date()})', flush=True)

print('\n=== HISTORY LIMIT REPORT ===')
for r in report:
    print(f"{r['sym']}: {r['contracts']} contracts, oldest {r['oldest']}")
ib.disconnect()
