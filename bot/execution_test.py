"""Execution path validation — places a 1-contract MES paper round-trip.

Proves the full pipeline: connect -> qualify contract -> market data ->
place BUY -> fill -> place SELL -> fill -> positions. Run manually on VPS.
"""
import sys
from ib_insync import IB, Future, MarketOrder
# --- SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb
_sb()

def main():
    ib = IB()
    ib.connect('127.0.0.1', 4002, clientId=77, timeout=10)
    print('CONNECTED accounts:', ib.managedAccounts())

    mes = ib.qualifyContracts(Future('MES', '202609', 'CME'))[0]
    print('contract:', mes.localSymbol, '| month:', mes.lastTradeDateOrContractMonth)

    # delayed market data (free) — just to read a price
    ib.reqMarketDataType(3)
    t = ib.reqMktData(mes, '', False, False)
    ib.sleep(3)
    print('market price (delayed):', t.marketPrice())
    ib.cancelMktData(mes)

    # BUY 1 @ market (paper)
    t1 = ib.placeOrder(mes, MarketOrder('BUY', 1))
    ib.sleep(3)
    s1 = t1.orderStatus
    print(f'BUY -> status={s1.status} filled={s1.filled} avg={s1.avgFillPrice}')

    # SELL 1 @ market (close)
    t2 = ib.placeOrder(mes, MarketOrder('SELL', 1))
    ib.sleep(3)
    s2 = t2.orderStatus
    print(f'SELL -> status={s2.status} filled={s2.filled} avg={s2.avgFillPrice}')

    print('positions:', [(p.contract.symbol, p.position) for p in ib.positions()])
    print('openOrders:', [(o.order.action, o.order.totalQuantity, o.orderStatus.status) for o in ib.openOrders()])
    ib.disconnect()
    print('ROUND-TRIP OK' if s1.filled and s2.filled else 'ROUND-TRIP INCOMPLETE')

if __name__ == '__main__':
    main()

