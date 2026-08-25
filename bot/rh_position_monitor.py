#!/usr/bin/env python3
"""Intraday position monitor for the Robinhood LIVE lane.

THE GAP THIS CLOSES: exits were evaluated exactly ONCE per day, at the 09:32 run.
Between 09:32 and the next 09:32 the ONLY thing that could act was the broker-side
stop — and RH stops are RTH-only. Nothing looked at a position's profit target,
time stop, or distance to stop in between.

Two modes:
  monitor  (default) — read-only. Reports every position vs its exit rules and
                       exits non-zero ONLY when something needs attention, so it
                       can drive a silent cron that alerts on exception.
  report            — always print the table (for on-demand use).

It does NOT place orders. Exits stay with the validated daily rule in
bot/live_equities.py (close > SMA5 or RSI2 > 70, time stop 5 sessions, 2xATR stop)
— acting intraday on a rule fitted to closes would be an unvalidated strategy
change. This tells us what is about to happen; the lane executes it.

Alert conditions (exit code 1):
  * a held position has NO resting protective stop
  * price is within ALERT_STOP_PCT of the stop
  * an exit rule is already satisfied (revert / time) -> the lane should act
  * an orphan stop exists for a symbol no longer held
"""
import os, sys
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
os.environ.setdefault('RH_DATA_SOURCE', 'IBKR')
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()

import boto3
import pandas as pd
from hardening.rh_client import RHClient
from bot.live_equities import (fetch_ibkr, indicators, load_book, MAX_HOLD,
                               STOP_ATR, _f)

NY = ZoneInfo('America/New_York')
RESTING = ('confirmed', 'queued', 'unconfirmed', 'partially_filled')
ALERT_STOP_PCT = float(os.getenv('RH_ALERT_STOP_PCT', '1.5'))
MODE = (sys.argv[1] if len(sys.argv) > 1 else 'monitor').lower()


def is_resting_stop(o):
    return (o.get('side') == 'sell'
            and o.get('stop_price') not in (None, '', '0', '0.000000')
            and (o.get('state') or '').lower() in RESTING)


def main():
    now = dt.datetime.now(NY)
    rh = RHClient()
    acct = rh._resolve_account()
    table = boto3.resource('dynamodb', region_name=os.getenv('AWS_REGION', 'us-east-1')) \
        .Table(os.getenv('DYNAMODB_TABLE', 'trading-data'))

    held = {p['symbol']: p for p in rh.get_positions(acct)
            if float(p.get('quantity') or 0) > 0}
    orders = rh.list_orders(acct)
    stops = {o['symbol']: o for o in orders if is_resting_stop(o)}
    book = load_book(table, False)
    quotes = {r['quote']['symbol']: r['quote']
              for r in rh.get_quotes(list(held)) if r.get('quote')} if held else {}
    bars = fetch_ibkr(list(held)) if held else {}

    alerts, rows = [], []
    tot_pl = tot_cost = 0.0
    for s in sorted(held):
        p = held[s]
        qty = int(float(p['quantity']))
        entry = float(p.get('average_buy_price') or 0)
        last = _f(quotes.get(s, {}).get('last_trade_price')) or 0.0
        st = stops.get(s)
        sp = float(st['stop_price']) if st else 0.0
        pl = (last - entry) * qty if last else 0.0
        tot_pl += pl
        tot_cost += entry * qty
        to_stop = ((last - sp) / last * 100) if (last and sp) else None
        pos = book.get(s)

        # exit-rule state from the lane's own indicators
        trig, held_n = '', None
        df = bars.get(s)
        if df is not None and pos:
            d = indicators(df)
            L = d.iloc[-1]
            ma5, r2 = _f(L['sma5']), _f(L['rsi2'])
            c = float(L['close'])
            try:
                held_n = len(d) - 1 - d.index.get_loc(pd.Timestamp(pos['entry_date']))
            except Exception:
                held_n = None
            if ma5 is not None and c > ma5:
                trig = 'REVERT-READY (close>SMA5)'
            elif r2 is not None and r2 > 70:
                trig = 'REVERT-READY (RSI2>70)'
            elif held_n is not None and held_n >= MAX_HOLD:
                trig = 'TIME-STOP-READY'
            else:
                trig = f'hold ({MAX_HOLD - held_n} left)' if held_n is not None else 'hold'

        if not st:
            alerts.append(f'{s}: NO RESTING STOP (naked)')
        elif to_stop is not None and to_stop <= ALERT_STOP_PCT:
            alerts.append(f'{s}: {to_stop:.1f}% from stop {sp:.2f} (last {last:.2f})')
        if trig.endswith('READY'):
            alerts.append(f'{s}: {trig} — lane should exit on next run')
        if s not in book:
            alerts.append(f'{s}: held at broker but NOT in the lane book (unmanaged)')
        rows.append((s, qty, entry, last, sp, to_stop, pl, trig))

    orphans = [s for s in stops if s not in held]
    for s in orphans:
        alerts.append(f'{s}: ORPHAN resting stop but no position — cancel it')

    if MODE == 'report' or alerts:
        print(f'RH LIVE positions @ {now.strftime("%Y-%m-%d %H:%M ET")}  '
              f'(exits: 2xATR stop | {MAX_HOLD}-session time | close>SMA5 or RSI2>70; no trailing)')
        print(f'{"sym":6}{"qty":>4}{"entry":>8}{"now":>8}{"stop":>8}{"toStop%":>9}'
              f'{"P&L$":>8}  status')
        for s, qty, entry, last, sp, ts, pl, trig in rows:
            print(f'{s:6}{qty:>4}{entry:>8.2f}{last:>8.2f}{sp:>8.2f}'
                  f'{(ts if ts is not None else float("nan")):>9.1f}{pl:>8.2f}  {trig}')
        if tot_cost:
            print(f'\ncost ${tot_cost:,.2f}  unrealized ${tot_pl:+,.2f} '
                  f'({tot_pl / tot_cost * 100:+.2f}%)  positions={len(held)} '
                  f'stops={len(stops)}')
    if alerts:
        print('\n*** ATTENTION ***')
        for a in alerts:
            print('  - ' + a)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
