#!/usr/bin/env python3
"""Pre-close exit run for the Robinhood RSI(2) lane — removes a full session of lag.

THE LAG BEING FIXED
The backtest exits on the CLOSE of the day the exit rule triggers. Live, exits were
only evaluated at the 09:32 run using YESTERDAY's close, so the position was sold
roughly one whole session after the backtest sells it. On a trade whose average hold
is 2.25 sessions that is a large, unmodelled slippage — pure implementation lag, not
strategy.

WHAT THIS DOES
Runs ~15:50 ET, builds today's provisional bar from the LIVE Robinhood quote (the
venue we execute on) appended to IBKR broker history, evaluates the SAME exit rules
in the SAME priority as the lane, and exits into the close.

  stop   : intraday low <= stop, or open gapped below it   (broker stop also covers)
  time   : held >= MAX_HOLD sessions
  revert : close > SMA5 OR RSI(2) > 70

It ONLY exits. It never enters, never writes RUN#live_equities (so the 09:32 entry
run still happens), and on any failure leaves the position OPEN with its stop intact
(fail-closed — never mark a broker position closed on an unconfirmed exit).

  python bot/rh_preclose_exit.py --dry-run
  python bot/rh_preclose_exit.py
"""
from __future__ import annotations
import argparse, os, sys, time
import datetime as dt
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.environ.setdefault('RH_DATA_SOURCE', 'IBKR')
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap as _sb
_sb()

import boto3
import pandas as pd
from bot.live_equities import (fetch_ibkr, indicators, load_book, put_item,
                               flush_writes, _live_exit_position, _f, _s,
                               MAX_HOLD, EXECUTION_MODE)
from hardening.rh_client import RHClient

NY = ZoneInfo('America/New_York')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
RESTING = ('confirmed', 'queued', 'unconfirmed', 'partially_filled')


def log(m):
    print(f'[{dt.datetime.now(NY).strftime("%H:%M:%S")}] {m}', flush=True)


def append_live_bar(df, quote):
    """Append today's provisional bar from the live quote.

    IBKR history is refreshed post-close, so at 15:50 it ends at yesterday. The
    exit rules need TODAY's near-final price — which is exactly the live RH quote.
    high/low are widened by the day's observed range where available so an intraday
    stop touch is not missed.
    """
    last = _f(quote.get('last_trade_price'))
    if last is None or last <= 0:
        return None
    today = dt.datetime.now(NY).date()
    if df.index[-1].date() == today:
        df = df.iloc[:-1]
    hi = max(_f(quote.get('high_price')) or last, last)
    lo = min(_f(quote.get('low_price')) or last, last)
    row = pd.DataFrame({'open': [_f(quote.get('open_price')) or last], 'high': [hi],
                        'low': [lo], 'close': [last], 'volume': [0.0]},
                       index=[pd.Timestamp(today)])
    return pd.concat([df, row])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    now = dt.datetime.now(NY)
    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    book = {s: p for s, p in load_book(table, False).items()
            if p.get('status') == 'OPEN'}
    if not book:
        log('no OPEN positions — nothing to evaluate')
        return 0
    log(f'{len(book)} OPEN positions at {now.strftime("%H:%M ET")}: {sorted(book)}')

    rh = RHClient()
    acct = rh._resolve_account()
    held = {p['symbol']: p for p in rh.get_positions(acct)
            if float(p.get('quantity') or 0) > 0}
    quotes = {r['quote']['symbol']: r['quote']
              for r in rh.get_quotes(list(book)) if r.get('quote')}
    bars = fetch_ibkr(list(book))

    exits = []
    for sym in sorted(book):
        pos = book[sym]
        df, q = bars.get(sym), quotes.get(sym)
        if df is None or not q:
            log(f'{sym:6} SKIP — no {"bars" if df is None else "quote"}')
            continue
        if sym not in held:
            log(f'{sym:6} SKIP — position not at broker (already flat?)')
            continue
        df2 = append_live_bar(df, q)
        if df2 is None:
            log(f'{sym:6} SKIP — no live price')
            continue
        d = indicators(df2)
        L = d.iloc[-1]
        o, h, l, c = (float(L[k]) for k in ('open', 'high', 'low', 'close'))
        ma5, r2 = _f(L['sma5']), _f(L['rsi2'])
        stop = _f(pos.get('stop_price')) or 0.0
        entry = _f(pos.get('entry_price')) or 0.0
        try:
            hold = len(d) - 1 - d.index.get_loc(pd.Timestamp(pos['entry_date']))
        except Exception:
            hold = 0

        reason = exit_px = None
        if stop > 0 and o < stop:
            reason, exit_px = 'gap_stop', o
        elif stop > 0 and l <= stop:
            reason, exit_px = 'stop', stop
        elif hold >= MAX_HOLD:
            reason, exit_px = 'time', c
        elif (ma5 is not None and c > ma5) or (r2 is not None and r2 > 70.0):
            reason, exit_px = 'revert', c
        if reason is None:
            log(f'{sym:6} HOLD  last={c:.2f} sma5={(ma5 or 0):.2f} rsi2={(r2 or 0):.1f} '
                f'hold={hold}/{MAX_HOLD}')
            continue

        shares = float(held[sym]['quantity'])   # keep fractional; market sell supports it
        log(f'{sym:6} EXIT  {reason}  last={c:.2f} sma5={(ma5 or 0):.2f} '
            f'rsi2={(r2 or 0):.1f} hold={hold} shares={shares}')
        if a.dry_run:
            continue
        if EXECUTION_MODE != 'LIVE':
            log(f'  {sym}: EXECUTION_MODE={EXECUTION_MODE}, not placing a real exit')
            continue
        try:
            fill = _live_exit_position(rh, sym, shares)
            exit_px = _f(fill.get('average_price')) or exit_px
        except Exception as e:
            log(f'  {sym}: EXIT FAILED — position left OPEN with stop intact: {e!r}')
            continue
        pnl = (exit_px - entry) * shares
        pnl_pct = (exit_px / entry - 1.0) if entry > 0 else 0.0
        put_item(table, f'RHTRADE#{sym}', pos['entry_date'], {
            'entry_date': pos['entry_date'], 'entry_price': _s(entry),
            'exit_date': str(now.date()), 'exit_price': _s(exit_px),
            'exit_reason': reason, 'hold_days': int(hold),
            'size_usd': pos.get('size_usd', ''), 'pnl_usd': _s(pnl),
            'pnl_pct': _s(pnl_pct), 'venue': 'RH', 'run': 'preclose',
            'ts': int(time.time())}, False)
        put_item(table, f'RHPOS#{sym}', 'current', {
            'status': 'CLOSED', 'entry_date': pos['entry_date'],
            'entry_price': _s(entry), 'exit_date': str(now.date()),
            'exit_price': _s(exit_px), 'exit_reason': reason,
            'pnl_usd': _s(pnl), 'pnl_pct': _s(pnl_pct), 'ts': int(time.time())}, False)
        exits.append((sym, reason, pnl))
        log(f'  {sym}: CLOSED {reason} @ {exit_px:.2f}  P&L ${pnl:+.2f}')

    if not a.dry_run:
        flush_writes(table)
    tot = sum(x[2] for x in exits)
    log(f'preclose done: {len(exits)} EXIT' + (f', realized ${tot:+.2f}' if exits else ''))
    for s, r, p in exits:
        log(f'  {s:6} {r:9} ${p:+.2f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
