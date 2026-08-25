#!/usr/bin/env python3
"""IBKR equities RSI(2) buy-the-dip — paper forward-test (native bracket stops).

Ports the VALIDATED Robinhood RSI2 edge (bot/live_equities.py) to IBKR paper so the
same equity strategy forward-tests on BOTH venues in parallel (owner directive
2026-08-21). IBKR is NOT futures-only — it trades stocks/ETFs too, and its paper
account (DUR193467) gives us a second, independent execution venue for the edge.

Signal logic is UNCHANGED (reused from live_equities): Wilder RSI(2) < 5 AND
close > SMA200 -> LONG. Exit = 2xATR hard stop (native bracket, broker-side),
5-day time stop, or revert (close>SMA5 / RSI2>70). Universe = UNIVERSE (imported
from live_equities — dynamic broad list).

Fill model (mirrors the backtest "signal at close t -> enter at open t+1"):
run daily at 09:30 ET, compute the signal on the LAST COMPLETED daily bar
(prior close), then enter TODAY at the open via the exec manager. The entry is a
GTC market order + native-bracket protective stop, so it fills immediately at the
open and is broker-protected from the first tick.

Execution: IBKR paper (DUR193467) via hardening/exec_manager.py — the ONLY
submitter. Idempotent TradeIntent, POSITION#/TRADE#/RUN# journal, reconciler tags
`<SYM>_RSI2` (long-only). clientId=81 (distinct from 70/72/78/79/80).

Paper capital is a SIMULATION input, not real money.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import datetime as dt

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from infra.ssm_secrets import bootstrap as _sb  # noqa: E402
_sb()

from bot.live_equities import (  # noqa: E402 — reuse the validated signal helpers
    fetch, indicators, position_size, RSI2_THR, STOP_ATR, MAX_HOLD,
    ETFS, STOCKS, UNIVERSE, MIN_BARS, DATA_START, BEAR_WARNING, _f, _s,
    EARNINGS_GUARD_DAYS,
)
from bot.earnings_guard import load_upcoming_earnings  # noqa: E402

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

# ---- paper sleeve (SIMULATION input, not real money) ----
PAPER_CAPITAL = float(os.getenv('IBEQ_PAPER_CAPITAL', '50000'))
RISK_PCT = float(os.getenv('IBEQ_RISK_PCT', '0.01'))
MAX_POS_PCT = float(os.getenv('IBEQ_MAX_POS_PCT', '0.05'))
MAX_POSITIONS = int(os.getenv('IBEQ_MAX_POSITIONS', '20'))
CLIENT_ID = 81
SCOPE = 'live_equities_ibkr'

# ---- go-live switch (owner flips IBEQ_EXECUTION_MODE=LIVE once the live acct is
# funded + the Jts-live gateway is enabled; PAPER default keeps it safe) ----
EXECUTION_MODE = os.getenv('IBEQ_EXECUTION_MODE', 'PAPER').strip().upper()  # PAPER | LIVE
IBKR_LIVE_PORT = int(os.getenv('IBKR_LIVE_PORT', '4001'))  # Jts-live gateway
LIVE_MAX_POSITIONS = int(os.getenv('IBEQ_LIVE_MAX_POSITIONS', '2'))
DAY_LOSS_CAP = float(os.getenv('IBEQ_DAY_LOSS_CAP', '25'))  # $/day realized-loss cap (LIVE)

# ---- LIVE sizing (a ~$500 account is NOT the $50k paper sleeve) --------------
# The paper sleeve risks 1% and caps a name at 5% of capital. On $506 that cap is
# $25, which is under ONE share for most names — the lane would never trade. LIVE
# therefore concentrates: few positions, each a large % of a small account.
# Commission reality (IBKR US equities, Fixed): $0.005/share, min $1.00/order,
# max 1% of trade value. The $1 minimum is what matters at this size, so cost per
# ROUND TRIP is ~2/notional dollars: a $100 position pays ~2.0%, a $230 position
# ~0.87%. RSI2 holds 2-5 days for ~1-2%, so SMALL positions are negative-EV here.
# Concentration is a cost decision, not a risk appetite decision.
LIVE_MAX_POS_PCT = float(os.getenv('IBEQ_LIVE_MAX_POS_PCT', '0.45'))
LIVE_RISK_PCT = float(os.getenv('IBEQ_LIVE_RISK_PCT', '0.05'))
# Optional hard ceiling on the capital used for sizing (belt-and-braces vs a
# mis-reported NetLiquidation). 0 = use the broker value as-is.
LIVE_CAPITAL_CAP = float(os.getenv('IBEQ_LIVE_CAPITAL_CAP', '0') or 0)
# LIVE trades only affordable whole shares -> the sub-$50 screened universe.
LIVE_UNIVERSE_SUB50 = os.getenv('IBEQ_LIVE_SUB50', '1') not in ('0', 'false', 'no')
# Minimum LIVE notional. IBKR's $1.00 order minimum means a $29 position pays
# ~6.9% round trip and a $121 position ~1.7%; below this floor the trade is
# structurally negative-EV for a 2-5 day RSI2 hold, so it is SKIPPED, not shrunk.
LIVE_MIN_NOTIONAL = float(os.getenv('IBEQ_LIVE_MIN_NOTIONAL', '150'))


def live_position_size(capital, close, atr):
    """LIVE $ per name = min(LIVE_RISK_PCT/stop_pct, LIVE_MAX_POS_PCT) * capital."""
    stop_dist = STOP_ATR * (atr or 0.0)
    stop_pct = stop_dist / close if close > 0 else 1.0
    size_risk = (LIVE_RISK_PCT * capital) / stop_pct if stop_pct > 0 else 0.0
    return min(size_risk, LIVE_MAX_POS_PCT * capital), stop_pct


def resolve_live_capital(ib):
    """Real NetLiquidation for the LIVE account. FAIL-CLOSED: never size blind."""
    net_liq = 0.0
    for row in ib.accountSummary():
        if row.tag == 'NetLiquidation':
            try:
                net_liq = float(row.value or 0)
            except (TypeError, ValueError):
                net_liq = 0.0
            break
    if net_liq <= 0:
        raise SystemExit('ABORT: LIVE mode but NetLiquidation unavailable — '
                         'refusing to size positions blind')
    cap = min(net_liq, LIVE_CAPITAL_CAP) if LIVE_CAPITAL_CAP > 0 else net_liq
    print(f'LIVE capital: NetLiquidation ${net_liq:,.2f}'
          + (f' (capped to ${cap:,.2f})' if cap < net_liq else ''))
    return cap


def _tag(sym: str) -> str:
    return f'{sym}_RSI2'


def load_book(table) -> dict:
    """Current open equity positions: {sym: item} for POSITION#<sym>_RSI2 OPEN."""
    book = {}
    lek = None
    while True:
        kw = dict(FilterExpression='begins_with(pk, :p)',
                  ExpressionAttributeValues={':p': 'POSITION#'})
        if lek:
            kw['ExclusiveStartKey'] = lek
        resp = table.scan(**kw)
        for it in resp.get('Items', []):
            tag = it['pk'].split('#', 1)[1]
            if not tag.endswith('_RSI2'):
                continue
            if it.get('sk') == 'current' and it.get('status') == 'OPEN':
                book[tag.split('_', 1)[0]] = it
        lek = resp.get('LastEvaluatedKey')
        if not lek:
            break
    return book


def put_item(table, pk, sk, fields, dry_run):
    if dry_run:
        print(f'  [dry] {pk} / {sk} : ' + ', '.join(f'{k}={v}' for k, v in fields.items()))
        return
    try:
        table.put_item(Item={'pk': pk, 'sk': sk, **fields})
    except Exception as e:
        print(f'  [put] {pk}/{sk} failed: {e!r}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='compute + print signals, no broker/AWS writes')
    ap.add_argument('--limit', type=int, default=0, help='cap symbols for a smoke test')
    args = ap.parse_args()

    table = boto3.resource('dynamodb', region_name=AWS_REGION).Table(DYNAMO_TABLE)
    now = dt.datetime.now(ZoneInfo('America/New_York'))
    today = now.date().isoformat()

    # RTH-only: entries are market orders placed AT the open; skip outside RTH.
    if not args.dry_run:
        if now.weekday() >= 5 or not (dt.time(9, 30) <= now.time() <= dt.time(16, 0)):
            print(f'[{today}] live_equities_ibkr SKIP — outside RTH (09:30–16:00 ET)')
            return
        if table.get_item(Key={'pk': 'RUN#live_equities_ibkr', 'sk': today}).get('Item'):
            print(f'[{today}] live_equities_ibkr already ran today — skip')
            return

        # Kill-switch: NEVER place orders unless CONTROL/system == RUNNING (fail-closed).
        from control import get_control, control_allows_entry, ControlUnavailable
        try:
            ctrl = get_control(table)
        except ControlUnavailable as e:
            print(f'[{today}] HALT — CONTROL unreadable (fail-closed): {e}')
            return
        if not control_allows_entry(ctrl):
            print(f'[{today}] HALT — CONTROL state={ctrl.get("state")} (kill-switch); no orders')
            return

    if EXECUTION_MODE == 'LIVE' and LIVE_UNIVERSE_SUB50:
        # $506 cannot buy one share of a $300 name; screen to sub-$50 liquid names.
        from bot.live_equities import _load_smallcap_universe
        full = _load_smallcap_universe()
        print(f'LIVE universe: {len(full)} sub-$50 liquid names (blocklist-filtered)')
    else:
        full = UNIVERSE
    syms = full[:args.limit] if args.limit else full
    earnings_blacklist = load_upcoming_earnings(table, days_ahead=EARNINGS_GUARD_DAYS)
    if earnings_blacklist:
        print(f'  earnings guard: will not ENTER {len(earnings_blacklist)} symbols '
              f'reporting within {EARNINGS_GUARD_DAYS}d')
    print(f'fetching {len(syms)} symbols (start={DATA_START})…')
    bars = fetch(syms)
    print(f'  got {len(bars)}/{len(syms)} symbols')

    if EXECUTION_MODE == 'LIVE':
        # With only LIVE_MAX_POSITIONS slots against many candidates, ORDER decides
        # what we own. Rank most-oversold first (lower RSI(2) = stronger snap-back
        # signal in the mean-reversion family) instead of taking whatever the
        # universe file happened to list first.
        def _rsi2_rank(s):
            df = bars.get(s)
            if df is None:
                return 999.0
            try:
                dd = indicators(df)
                cc = dd[dd.index.date < dt.date.today()]
                if cc.empty:
                    return 999.0
                v = _f(cc.iloc[-1]['rsi2'])
                return v if v is not None else 999.0
            except Exception:
                return 999.0
        syms = sorted(syms, key=_rsi2_rank)
        print(f'LIVE ranking: most-oversold first (top 5: {syms[:5]})')

    book = load_book(table) if not args.dry_run else {}
    committed = len(book)
    pos_cap = LIVE_MAX_POSITIONS if EXECUTION_MODE == 'LIVE' else MAX_POSITIONS
    day_loss_used = 0.0

    # ---- broker connection (only when not dry-run) ----
    ib = None
    exec_mgr = None
    if not args.dry_run:
        from ib_insync import IB, Stock
        from hardening.exec_manager import ExecutionManager, TradeIntent
        ib = IB()
        port = IBKR_LIVE_PORT if EXECUTION_MODE == 'LIVE' else int(os.getenv('IBKR_PORT', '4002'))
        ib.connect('127.0.0.1', port, clientId=CLIENT_ID, timeout=10)
        # FAIL-CLOSED account/mode guard: refuse to trade a live account in PAPER
        # mode or a paper account in LIVE mode (wrong-account protection).
        from bot.control import account_mode_ok
        ok_mode, why = account_mode_ok(EXECUTION_MODE, ib.managedAccounts())
        if not ok_mode:
            raise SystemExit(f'ABORT: {why}')
        print(f'{EXECUTION_MODE} mode on account(s) {ib.managedAccounts()} — mode guard OK')
        exec_mgr = ExecutionManager(ib, table, scope=SCOPE)

    # sizing capital: real broker equity in LIVE, the simulated sleeve in PAPER
    capital = PAPER_CAPITAL
    if EXECUTION_MODE == 'LIVE':
        if ib is not None:
            capital = resolve_live_capital(ib)
        elif LIVE_CAPITAL_CAP > 0:
            capital = LIVE_CAPITAL_CAP
            print(f'DRY-RUN LIVE preview: sizing off IBEQ_LIVE_CAPITAL_CAP ${capital:,.2f}')
        else:
            print('WARNING: dry-run LIVE without IBEQ_LIVE_CAPITAL_CAP — '
                  'preview sizes use the PAPER sleeve and are NOT representative')

    enters, exits = [], []

    for sym in syms:
        df = bars.get(sym)
        if df is None:
            continue
        # Signal on the LAST COMPLETED daily bar only (prior close). Today's bar
        # (if yfinance already returned it) is still forming at the 09:30 open.
        d = indicators(df)
        completed = d[d.index.date < dt.date.today()]
        if completed.empty:
            continue
        last = completed.iloc[-1]
        sig_date = str(completed.index[-1].date())
        o, h, l, c = (float(last[k]) for k in ('open', 'high', 'low', 'close'))
        r2 = _f(last['rsi2']); ma200 = _f(last['sma200'])
        ma5 = _f(last['sma5']); atr = _f(last['atr14'])

        pos = book.get(sym)
        exited = False

        # --- manage OPEN: time / revert exit on the completed close ---
        # (the 2xATR stop is broker-side; a stop fill shows up as a missing
        #  broker position and is reconciled by the reconciler next cycle)
        if pos is not None:
            stop = _f(pos.get('stop_price')) or 0.0
            entry_price = _f(pos.get('entry_price')) or 0.0
            entry_date = str(pos.get('entry_date', ''))
            hold = 0
            try:
                hold = (completed.index[-1].date() - pd.Timestamp(entry_date).date()).days
            except Exception:
                hold = MAX_HOLD
            reason = None; exit_price = None
            if hold >= MAX_HOLD:
                reason, exit_price = 'time', c
            elif (ma5 is not None and c > ma5) or (r2 is not None and r2 > 70.0):
                reason, exit_price = 'revert', c
            if reason is not None and not args.dry_run:
                shares = float(pos.get('size_shares') or 0) or 0.0
                if shares <= 0 and entry_price > 0:
                    shares = float(pos.get('size_usd') or 0) / entry_price
                con = Stock(sym, 'SMART', 'USD')
                ib.qualifyContracts(con)
                exit_intent = TradeIntent(scope=SCOPE, tag=_tag(sym), symbol=sym,
                                          action='SELL', side='LONG', qty=shares,
                                          order_type='MKT', stop_price=0.0,
                                          contract_month='', bar_time=sig_date,
                                          signal_reason=reason)
                res = exec_mgr.submit_exit(exit_intent, con, cancel_stop=True)
                if res.status == 'FILLED' or res.status == 'PARTIAL':
                    exit_price = _f(getattr(res, 'fill_price', None)) or c
                elif res.status == 'DUPLICATE':
                    print(f'  {sym} duplicate exit — skip'); exited = True; pos = None; continue
            if reason is not None:
                size_usd = float(pos.get('size_usd') or 0)
                shares = float(pos.get('size_shares') or 0) or 0.0
                if shares <= 0 and entry_price > 0:
                    shares = size_usd / entry_price
                pnl = (exit_price - entry_price) * shares if exit_price else 0.0
                if pnl < 0:
                    day_loss_used += -pnl
                pnl_pct = (exit_price / entry_price - 1.0) if entry_price else 0.0
                put_item(table, f'TRADE#{_tag(sym)}', str(pos.get('entry_date', '')), {
                    'entry_date': pos.get('entry_date', ''), 'entry_price': _s(entry_price),
                    'exit_date': today, 'exit_price': _s(exit_price), 'exit_reason': reason,
                    'hold_days': int(hold), 'size_usd': pos.get('size_usd', ''),
                    'pnl_usd': _s(pnl), 'pnl_pct': _s(pnl_pct), 'ts': int(time.time())},
                    args.dry_run)
                put_item(table, f'POSITION#{_tag(sym)}', 'current', {
                    'status': 'CLOSED', 'entry_date': pos.get('entry_date', ''),
                    'entry_price': _s(entry_price), 'exit_date': today,
                    'exit_price': _s(exit_price), 'exit_reason': reason,
                    'pnl_usd': _s(pnl), 'ts': int(time.time())}, args.dry_run)
                exits.append({'symbol': sym, 'exit_reason': reason, 'pnl_usd': _s(pnl)})
                exited = True
                pos = None
                book.pop(sym, None)
                committed -= 1

        # --- new entry: signal on completed close, enter today at open ---
        if pos is None and not exited and r2 is not None and ma200 is not None:
            if sym.upper() in earnings_blacklist:
                continue
            if r2 < RSI2_THR and c > ma200:
                if committed < pos_cap and day_loss_used < DAY_LOSS_CAP:
                    if EXECUTION_MODE == 'LIVE':
                        size_usd, stop_pct = live_position_size(capital, c, atr or 0.0)
                    else:
                        size_usd, stop_pct = position_size(capital, c, atr or 0.0)
                    stop_price = c - STOP_ATR * (atr or 0.0)
                    # WHOLE shares only: IBKR STP orders are whole-share, so a
                    # fractional-qty bracket stop is REJECTED and the parent market
                    # order never transmits (root cause of the 2026-08-24 NVDA/INTC
                    # ENTRY UNKNOWN timeout). Round down; skip if under 1 share.
                    shares = int(size_usd / c) if c > 0 else 0
                    if EXECUTION_MODE == 'LIVE' and shares >= 1:
                        notional = shares * c
                        if notional < LIVE_MIN_NOTIONAL:
                            print(f'  {sym} skip: ${notional:.0f} notional < '
                                  f'${LIVE_MIN_NOTIONAL:.0f} floor (commission drag)')
                            continue
                    if shares >= 1 and stop_price > 0:
                        reason = (f'RSI(2) {r2:.2f} < {RSI2_THR} AND close {c:.2f} > '
                                  f'SMA200 {ma200:.2f}')
                        if args.dry_run:
                            enters.append({'sym': sym, 'shares': shares,
                                           'stop': round(stop_price, 2), 'size_usd': _s(size_usd)})
                        else:
                            from ib_insync import Stock
                            from hardening.exec_manager import TradeIntent
                            con = Stock(sym, 'SMART', 'USD')
                            ib.qualifyContracts(con)
                            intent = TradeIntent(scope=SCOPE, tag=_tag(sym), symbol=sym,
                                                 action='BUY', side='LONG', qty=shares,
                                                 order_type='MKT', stop_price=float(stop_price),
                                                 contract_month='', bar_time=sig_date,
                                                 signal_reason=reason)
                            res = exec_mgr.submit_entry(intent, con)
                            if res.status == 'DUPLICATE':
                                print(f'  {sym} duplicate entry — skip (idempotent)'); continue
                            if res.status == 'UNKNOWN':
                                print(f'  {sym} ENTRY UNKNOWN (timeout) — no state written; '
                                      f'reconcile will resolve'); continue
                            ep = _f(getattr(res, 'fill_price', None)) or c
                            put_item(table, f'POSITION#{_tag(sym)}', 'current', {
                                'status': 'OPEN', 'entry_date': today,
                                'entry_price': _s(ep), 'stop_price': _s(stop_price),
                                'size_usd': _s(size_usd), 'size_shares': str(shares),
                                'pos': str(shares),  # whole-share count for the reconciler
                                'atr': _s(atr or 0), 'side': 'LONG', 'ts': int(time.time())},
                                args.dry_run)
                            enters.append({'sym': sym, 'shares': shares,
                                           'stop': round(stop_price, 2), 'size_usd': _s(size_usd)})
                            committed += 1

    put_item(table, 'RUN#live_equities_ibkr', today, {'ts': int(time.time())}, args.dry_run)
    print(f'\nlive_equities_ibkr done [{today}]: {len(enters)} ENTER, {len(exits)} EXIT, '
          f'committed={committed}/{MAX_POSITIONS}')
    for e in enters:
        print(f'  ENTER {e["sym"]:6s} {e["shares"]} sh stop={e["stop"]} size=${e["size_usd"]}')
    for x in exits:
        print(f'  EXIT  {x["symbol"]:6s} {x["exit_reason"]:6s} pnl=${x["pnl_usd"]}')

    if ib is not None:
        ib.disconnect()


if __name__ == '__main__':
    main()
