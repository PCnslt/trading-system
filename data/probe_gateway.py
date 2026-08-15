#!/usr/bin/env python3
"""Gateway probe: verify exchange mappings for the expanded CME Group universe.

READ-ONLY. reqContractDetails + reqSecDefOptParams + reqHistoricalData probes
only. No orders, no writes. clientId 91 (distinct from all others).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from ib_insync import IB, Future, ContFuture, util
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))

# (symbol, exchange) representatives per new asset class
PROBES = [
    ('CL', 'NYMEX'), ('NG', 'NYMEX'), ('QM', 'NYMEX'),
    ('GC', 'COMEX'), ('SI', 'COMEX'), ('HG', 'COMEX'), ('PL', 'NYMEX'), ('PA', 'NYMEX'),
    ('ZC', 'CBOT'), ('ZW', 'CBOT'), ('ZS', 'CBOT'), ('HE', 'CME'), ('LE', 'CME'),
    ('6E', 'CME'), ('6J', 'CME'), ('6M', 'CME'),
    ('M2K', 'CME'), ('MYM', 'CBOT'),
    ('MGC', 'COMEX'), ('SIL', 'COMEX'),
    ('RB', 'NYMEX'), ('HO', 'NYMEX'), ('QG', 'NYMEX'),
    ('ZM', 'CBOT'), ('ZL', 'CBOT'), ('ZO', 'CBOT'),
]

def main():
    ib = IB()
    ib.connect(IBKR_HOST, IBKR_PORT, clientId=91, timeout=15, readonly=True)
    print(f"accounts={ib.managedAccounts()}")
    for sym, ex in PROBES:
        try:
            cd = ib.reqContractDetails(Future(sym, exchange=ex))
            if not cd:
                # try alternate
                for alt in ('CME', 'CBOT', 'NYMEX', 'COMEX', 'GLOBEX'):
                    if alt == ex:
                        continue
                    cd = ib.reqContractDetails(Future(sym, exchange=alt))
                    if cd:
                        print(f"[{sym}] {ex}->EMPTY, FOUND via {alt}: n={len(cd)} first.expiry={cd[0].contract.lastTradeDateOrContractMonth}")
                        break
                else:
                    print(f"[{sym}] {ex}->EMPTY (all alts empty)")
                continue
            c = cd[0].contract
            print(f"[{sym}] {ex} OK n={len(cd)} front={c.lastTradeDateOrContractMonth} class={c.tradingClass} mult={c.multiplier} cur={c.currency}")
        except Exception as e:
            print(f"[{sym}] {ex} ERR {e!r}")
        ib.sleep(0.3)

    # ContFuture probes for the asset classes (daily-backfill depth)
    print("\n--- ContFuture probes ---")
    for sym, ex in [('CL','NYMEX'), ('GC','COMEX'), ('ZC','CBOT'), ('6E','CME'), ('M2K','CME'), ('HE','CME')]:
        try:
            q = ib.qualifyContracts(ContFuture(sym, ex, 'USD'))
            print(f"ContFuture[{sym}] {ex}: {'OK' if q else 'EMPTY'}")
        except Exception as e:
            print(f"ContFuture[{sym}] {ex}: ERR {e!r}")

    # Options chain metadata probe
    print("\n--- reqSecDefOptParams probe ---")
    try:
        es = ib.qualifyContracts(Future('ES', '202609', 'CME'))[0]
        chains = ib.reqSecDefOptParams(es.symbol, es.exchange, es.secType, es.conId)
        for ch in chains:
            print(f"ES options: exchange={ch.exchange} underlyingConId={ch.underlyingConId} "
                  f"expirations={len(ch.expirations)} strikes={len(ch.strikes)}")
    except Exception as e:
        print(f"reqSecDefOptParams ERR {e!r}")

    ib.disconnect()

if __name__ == '__main__':
    main()
