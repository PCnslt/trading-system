#!/usr/bin/env python3
"""Discover the FULL CME Group futures universe on the paper account.

Uses reqContractDetails (metadata only, READ-ONLY) to find every root symbol
the CME Group subscription + paper entitlements actually resolve, well beyond
the current 42-symbol registry. Outputs a machine-readable resolved/gapped
table so the registry can be extended honestly.

READ-ONLY on the trading side: reqContractDetails only. No orders, no bars,
no account writes. Own clientId (88) — distinct from all bots.

Usage:
  python research/discover_cme_universe.py            # full candidate list
  python research/discover_cme_universe.py --save     # also write JSON to S3
"""
import os
import sys
import json
import time
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from ib_insync import IB, Future

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
CLIENT_ID = 88           # distinct from live(70)/bonds(71)/intraday(72)/backfill(73)/tick(74)/daily(75)/recon(76)/opts(77)/agent(90)

MONTHLY = tuple(range(1, 13))

# (sym, asset_class, preferred_exchange, contract_months)
# months = valid contract months for front-month resolution + rollover derivation.
CANDIDATES = [
    # --- CME equity index ---
    ('ES',  'index', 'CME',   (3, 6, 9, 12)),
    ('NQ',  'index', 'CME',   (3, 6, 9, 12)),
    ('MES', 'index', 'CME',   (3, 6, 9, 12)),
    ('MNQ', 'index', 'CME',   (3, 6, 9, 12)),
    ('RTY', 'index', 'CME',   (3, 6, 9, 12)),
    ('M2K', 'index', 'CME',   (3, 6, 9, 12)),
    ('YM',  'index', 'CBOT',  (3, 6, 9, 12)),
    ('MYM', 'index', 'CBOT',  (3, 6, 9, 12)),
    ('NKD', 'index', 'CME',   (3, 6, 9, 12)),
    ('NIY', 'index', 'CME',   (3, 6, 9, 12)),
    ('EMD', 'index', 'CME',   (3, 6, 9, 12)),

    # --- CBOT / CME rates ---
    ('ZB',  'rates', 'CBOT',  (3, 6, 9, 12)),
    ('ZN',  'rates', 'CBOT',  (3, 6, 9, 12)),
    ('ZF',  'rates', 'CBOT',  (3, 6, 9, 12)),
    ('ZT',  'rates', 'CBOT',  (3, 6, 9, 12)),
    ('UB',  'rates', 'CBOT',  (3, 6, 9, 12)),
    ('TN',  'rates', 'CBOT',  (3, 6, 9, 12)),
    ('ZQ',  'rates', 'CBOT',  MONTHLY),
    ('SR1', 'rates', 'CME',   MONTHLY),
    ('SR3', 'rates', 'CME',   (3, 6, 9, 12)),
    ('2YY', 'rates', 'CME',   (3, 6, 9, 12)),
    ('5YY', 'rates', 'CME',   (3, 6, 9, 12)),
    ('10Y', 'rates', 'CME',   (3, 6, 9, 12)),
    ('30Y', 'rates', 'CME',   (3, 6, 9, 12)),

    # --- NYMEX energy ---
    ('CL',  'energy', 'NYMEX', MONTHLY),
    ('NG',  'energy', 'NYMEX', MONTHLY),
    ('RB',  'energy', 'NYMEX', MONTHLY),
    ('HO',  'energy', 'NYMEX', MONTHLY),
    ('QM',  'energy', 'NYMEX', MONTHLY),
    ('QG',  'energy', 'NYMEX', MONTHLY),
    ('BZ',  'energy', 'NYMEX', MONTHLY),
    ('MCL', 'energy', 'NYMEX', MONTHLY),
    ('MNG', 'energy', 'NYMEX', MONTHLY),

    # --- COMEX / NYMEX metals ---
    ('GC',  'metals', 'COMEX', (2, 4, 6, 8, 10, 12)),
    ('SI',  'metals', 'COMEX', (1, 3, 5, 7, 9, 12)),
    ('HG',  'metals', 'COMEX', MONTHLY),
    ('PL',  'metals', 'NYMEX', (1, 4, 7, 10)),
    ('PA',  'metals', 'NYMEX', (3, 6, 9, 12)),
    ('MGC', 'metals', 'COMEX', (2, 4, 6, 8, 10, 12)),
    ('ALI', 'metals', 'COMEX', MONTHLY),
    ('MHG', 'metals', 'COMEX', MONTHLY),
    ('SIL', 'metals', 'COMEX', (1, 3, 5, 7, 9, 12)),

    # --- CBOT / MGEX / KCBT ags ---
    ('ZC',  'ags', 'CBOT', (3, 5, 7, 9, 12)),
    ('ZW',  'ags', 'CBOT', (3, 5, 7, 9, 12)),
    ('ZS',  'ags', 'CBOT', (1, 3, 5, 7, 8, 9, 11)),
    ('ZM',  'ags', 'CBOT', (1, 3, 5, 7, 8, 9, 10, 12)),
    ('ZL',  'ags', 'CBOT', (1, 3, 5, 7, 8, 9, 10, 12)),
    ('ZO',  'ags', 'CBOT', (3, 5, 7, 9, 12)),
    ('ZR',  'ags', 'CBOT', (1, 3, 5, 7, 9, 11)),
    ('KE',  'ags', 'CBOT', (3, 5, 7, 9, 12)),
    ('MWE', 'ags', 'CBOT', (3, 5, 7, 9, 12)),
    ('XC',  'ags', 'CBOT', (3, 5, 7, 9, 12)),
    ('XW',  'ags', 'CBOT', (3, 5, 7, 9, 12)),
    ('YK',  'ags', 'CBOT', (1, 3, 5, 7, 8, 9, 11)),

    # --- CME livestock ---
    ('HE',  'ags', 'CME', (2, 4, 5, 6, 7, 8, 10, 12)),
    ('LE',  'ags', 'CME', (2, 4, 6, 8, 10, 12)),
    ('GF',  'ags', 'CME', (1, 3, 4, 5, 8, 9, 10, 11)),

    # --- CME FX ---
    ('6E',  'fx', 'CME', (3, 6, 9, 12)),
    ('6J',  'fx', 'CME', (3, 6, 9, 12)),
    ('6B',  'fx', 'CME', (3, 6, 9, 12)),
    ('6A',  'fx', 'CME', (3, 6, 9, 12)),
    ('6C',  'fx', 'CME', (3, 6, 9, 12)),
    ('6S',  'fx', 'CME', (3, 6, 9, 12)),
    ('6N',  'fx', 'CME', (3, 6, 9, 12)),
    ('6M',  'fx', 'CME', (3, 6, 9, 12)),
    ('6L',  'fx', 'CME', MONTHLY),
    ('6Z',  'fx', 'CME', (3, 6, 9, 12)),
    ('M6E', 'fx', 'CME', (3, 6, 9, 12)),
    ('M6B', 'fx', 'CME', (3, 6, 9, 12)),
    ('M6A', 'fx', 'CME', (3, 6, 9, 12)),
    ('M6J', 'fx', 'CME', (3, 6, 9, 12)),

    # --- CME crypto (separate entitlement likely) ---
    ('BTC', 'crypto', 'CME', MONTHLY),
    ('MBT', 'crypto', 'CME', MONTHLY),
    ('ETH', 'crypto', 'CME', MONTHLY),
    ('MET', 'crypto', 'CME', MONTHLY),
]

# CME-group listing exchanges, preference order for fallback.
EXCHANGES = ('CME', 'CBOT', 'NYMEX', 'COMEX', 'GLOBEX', 'KCBT', 'MGEX')


def discover(ib, sym, pref_exchange):
    """Return (resolved_dict, None) or (None, gap_reason)."""
    attempts = [pref_exchange] + [e for e in EXCHANGES if e != pref_exchange]
    last_err = None
    for ex in attempts:
        try:
            cd = ib.reqContractDetails(Future(sym, exchange=ex))
        except Exception as e:
            last_err = repr(e)
            continue
        if cd:
            # capture metadata from the contracts
            expiries = sorted({c.contract.lastTradeDateOrContractMonth for c in cd
                               if c.contract.lastTradeDateOrContractMonth})
            con = cd[0].contract
            months = sorted({int(e[4:6]) for e in expiries})
            return {
                'sym': sym,
                'exchange': ex,
                'currency': con.currency,
                'tradingClass': con.tradingClass,
                'multiplier': con.multiplier,
                'n_contracts': len(cd),
                'months': months,
                'expiries': expiries,
            }, None
    # also try empty exchange (SMART) once
    try:
        cd = ib.reqContractDetails(Future(sym, exchange=''))
        if cd:
            expiries = sorted({c.contract.lastTradeDateOrContractMonth for c in cd
                               if c.contract.lastTradeDateOrContractMonth})
            con = cd[0].contract
            months = sorted({int(e[4:6]) for e in expiries})
            return {
                'sym': sym, 'exchange': con.exchange or '(SMART)',
                'currency': con.currency, 'tradingClass': con.tradingClass,
                'multiplier': con.multiplier, 'n_contracts': len(cd),
                'months': months, 'expiries': expiries,
            }, None
    except Exception as e:
        last_err = repr(e)
    return None, (last_err or 'no security definition')


def main():
    do_save = '--save' in sys.argv
    ib = IB()
    resolved, gapped = [], []
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=20, readonly=True)
        print(f"connected clientId={CLIENT_ID} accounts={ib.managedAccounts()} (READ-ONLY, reqContractDetails only)")
        for sym, ac, pref, months in CANDIDATES:
            d, err = discover(ib, sym, pref)
            if d:
                d['asset_class'] = ac
                d['months_hint'] = list(months)
                resolved.append(d)
                print(f"[RESOLVE] {sym:5s} {d['exchange']:6s} {d['tradingClass']:6s} "
                      f"mult={d['multiplier']} cur={d['currency']} "
                      f"{d['n_contracts']:2d} contracts months={d['months']}")
            else:
                gapped.append({'sym': sym, 'asset_class': ac, 'reason': err})
                print(f"[GAP    ] {sym:5s} ({ac}) — {err}")
            time.sleep(0.5)
    finally:
        ib.disconnect()

    print("\n=== SUMMARY ===")
    print(f"resolved: {len(resolved)}   gapped: {len(gapped)}")
    for g in gapped:
        print(f"  GAP: {g['sym']} ({g['asset_class']}) — {g['reason']}")

    out = {
        'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'account': 'DUR193467',
        'resolved': resolved,
        'gapped': gapped,
    }
    if do_save:
        import boto3
        s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
        bucket = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
        s3.put_object(Bucket=bucket, Key='research/cme-universe/discovery.json',
                      Body=json.dumps(out, indent=2, default=str))
        print("saved -> s3://" + bucket + "/research/cme-universe/discovery.json")

    # also write local copy for the registry-extension step
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'cme_discovery.json'), 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print("local -> research/cme_discovery.json")


if __name__ == '__main__':
    main()
