#!/usr/bin/env python3
"""Complete Robinhood trade ledger from BROKER ground truth.

Lists every filled order the broker returns, matches buys to sells FIFO per symbol
to get REALIZED P&L, and marks what is still open (unrealized). Broker data only —
no bot state, so nothing here depends on the bot having recorded things correctly.
"""
import os, sys, json
import datetime as dt
from collections import defaultdict, deque
from zoneinfo import ZoneInfo

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()
from hardening.rh_client import RHClient

NY = ZoneInfo('America/New_York')
rh = RHClient()
acct = rh._resolve_account()
orders = rh.list_orders(acct)

fills = []
for o in orders:
    if (o.get('state') or '').lower() != 'filled':
        continue
    q = float(o.get('cumulative_quantity') or 0)
    px = float(o.get('average_price') or 0)
    if q <= 0 or px <= 0:
        continue
    t = dt.datetime.fromisoformat(o['created_at'].replace('Z', '+00:00')).astimezone(NY)
    fills.append({'t': t, 'sym': o['symbol'], 'side': o['side'], 'qty': q, 'px': px,
                  'usd': q * px, 'stop': o.get('stop_price')})
fills.sort(key=lambda x: x['t'])

print('=' * 88)
print('EVERY FILLED ORDER (broker record)')
print('=' * 88)
print(f'{"when (ET)":18}{"sym":7}{"side":6}{"qty":>10}{"price":>10}{"$ value":>10}  note')
for f in fills:
    note = 'stop-triggered sell' if f['stop'] else ''
    print(f'{f["t"].strftime("%Y-%m-%d %H:%M"):18}{f["sym"]:7}{f["side"]:6}'
          f'{f["qty"]:>10.6f}{f["px"]:>10.4f}{f["usd"]:>10.2f}  {note}')

# ---- FIFO round-trip matching ----
lots = defaultdict(deque)
closed = []
for f in fills:
    if f['side'] == 'buy':
        lots[f['sym']].append([f['qty'], f['px'], f['t']])
    else:
        rem = f['qty']
        while rem > 1e-9 and lots[f['sym']]:
            lot = lots[f['sym']][0]
            take = min(rem, lot[0])
            closed.append({'sym': f['sym'], 'qty': take, 'buy_px': lot[1],
                           'sell_px': f['px'], 'buy_t': lot[2], 'sell_t': f['t'],
                           'pnl': (f['px'] - lot[1]) * take})
            lot[0] -= take
            rem -= take
            if lot[0] <= 1e-9:
                lots[f['sym']].popleft()

print('\n' + '=' * 88)
print('CLOSED ROUND-TRIPS (realized)')
print('=' * 88)
if not closed:
    print('  none')
tot = 0.0
for c in closed:
    hold = (c['sell_t'] - c['buy_t']).days
    tot += c['pnl']
    print(f'  {c["sym"]:6} {c["qty"]:.6f} @ {c["buy_px"]:.4f} -> {c["sell_px"]:.4f}  '
          f'{c["buy_t"].date()} -> {c["sell_t"].date()} ({hold}d)  '
          f'P&L ${c["pnl"]:+.2f}')
print(f'\n  TOTAL REALIZED: ${tot:+.2f}  over {len(closed)} round-trip(s)')

# ---- still open ----
held = {p['symbol']: p for p in rh.get_positions(acct) if float(p.get('quantity') or 0) > 0}
qs = {r['quote']['symbol']: r['quote'] for r in rh.get_quotes(list(held)) if r.get('quote')} if held else {}
print('\n' + '=' * 88)
print('STILL OPEN (unrealized)')
print('=' * 88)
u = cost = 0.0
for s in sorted(held):
    p = held[s]
    n = float(p['quantity'])
    e = float(p['average_buy_price'])
    last = float(qs.get(s, {}).get('last_trade_price') or 0)
    pl = (last - e) * n
    u += pl
    cost += e * n
    print(f'  {s:6} {int(n):>3} @ {e:>8.4f}  now {last:>8.4f}  ${e*n:>7.2f}  P&L ${pl:+.2f}')
print(f'\n  cost basis ${cost:,.2f}   unrealized ${u:+.2f} ({(u/cost*100 if cost else 0):+.2f}%)')
print(f'\n  NET (realized {tot:+.2f} + unrealized {u:+.2f}) = ${tot+u:+.2f}')
pf = rh._tool('get_portfolio', account_number=acct).get('data', {})
print(f'  portfolio total_value ${pf.get("total_value")}  equity ${pf.get("equity_value")}  '
      f'cash ${pf.get("cash")}')
print(f'\n  (broker returned {len(orders)} orders total; oldest fill '
      f'{fills[0]["t"].date() if fills else "n/a"})')
