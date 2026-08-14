"""Live trading bot — bonds/FX FADE-RALLY SHORT (paper forward-test).

Two SHORT-only mean-reversion strategies on ZB (30yr), 6B (GBP/USD),
6A (AUD/USD). This is the ROBUST expression of the range-bound rates/FX
thesis validated in bot/meanrev_scan.py: the LONG mean-reversion lead was
hold-period fragile (1.88 PF @5d -> 1.07 @10d), while the fade-rally SHORT
side is hold-robust. Exact ports of the validated SHORT cells:

  1) RSI2SHORT — RSI(2) fade-the-rally short (meanrev_scan sig_rsi_mr SHORT,
     n=2): pooled OOS PF 1.50, 6/6 markets >= 1.2 (n=362).
       Entry : RSI(2) > 90  (overbought -> sell short)
       Exit  : RSI(2) <= 50 (reversion done), or 5-day time stop. NO stop order
               (the backtest has none; 2*ATR used for position sizing only).

  2) BBANDSHORT — Bollinger fade-short (meanrev_scan sig_bollinger_mr SHORT,
     n=20, k=2.0): pooled OOS PF 1.48 across markets at n=20 (best lookback;
     pooled 1.25 across all lookbacks, 11/18 cells robust).
       Entry : close > upper band (20-day mean + 2*std)  (overbought -> short)
       Exit  : close <= 20-day mean (mid band), or 5-day time stop. NO stop.

SIZING HONESTY: this short edge (OOS PF ~1.3-1.5) is WEAKER than the index
long edge (OOS PF ~2-3). It is a DIVERSIFIER, not the primary. Sized to its
own, smaller risk sleeve — BONDFX_RISK_BUDGET (default 25k = half the index
sleeve) — not the main RISK_BUDGET. Full-size contracts (ZB $100k face,
6B GBP 62.5k, 6A AUD 100k) are large; min_contracts=1 means a single
contract can exceed the 2%-of-sleeve risk target. That is accepted for a
PAPER diversifier and is visible in the logs.

Data: yfinance ZB=F / 6B=F / 6A=F daily (front-month continuation proxies).
Execution: IBKR paper (DUR193467) ZB (CBOT) + 6B/6A (CME), front-month,
  dynamic roll. SHORT mechanics: SELL-to-open on entry, BUY-to-cover on exit.
Logging: DynamoDB pk tagged per strategy —
  SIGNAL#<sym>_<STRAT> / TRADE#<sym>_<STRAT> / POSITION#<sym>_<STRAT>
  (e.g. SIGNAL#ZB_RSI2SHORT, TRADE#6B_BBANDSHORT).
Paper only — LIVE env var stays false. Run daily via cron (after live.py).
"""
import os
import time
import datetime as dt

import yfinance as yf
import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

from risk import RiskEngine, RiskConfig

load_dotenv()

# ===== config =====
IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
DYNAMO_TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')
BONDFX_RISK_BUDGET = float(os.getenv('BONDFX_RISK_BUDGET', '25000'))  # diversifier sleeve
LIVE = os.getenv('LIVE', 'false').lower() == 'true'   # flip to true for real money

BOLL_LOOKBACK = 20     # Bollinger window (n=20 best OOS for the SHORT side)
BOLL_K = 2.0           # Bollinger sigma multiple
MAX_HOLD = 5           # time stop (days)
STOP_ATR = 2.0         # ATR multiple for sizing proxy (no GTC stop in backtest)
RSI2_OVERBOUGHT = 90.0  # RSI(2) short entry (fade the rally)
RSI2_MID = 50.0         # RSI(2) short exit (reversion done)

# data ticker -> execution contract. Point value = $ per 1.0 price unit
# (ZB 1 pt = $1,000 on $100k face; 6B GBP 62.5k notional; 6A AUD 100k notional).
CONTRACTS = [
    {'data': 'ZB=F', 'symbol': 'ZB', 'exchange': 'CBOT', 'point_value': 1000.0},
    {'data': '6B=F', 'symbol': '6B', 'exchange': 'CME',  'point_value': 62500.0},
    {'data': '6A=F', 'symbol': '6A', 'exchange': 'CME',  'point_value': 100000.0},
]


# ===== indicators =====
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def bollinger(close, n=BOLL_LOOKBACK, k=BOLL_K):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid, mid + k * sd, mid - k * sd


def compute(df):
    """Last bar's indicator values — exact port of meanrev_scan.py indicators."""
    h, l, c = df['High'], df['Low'], df['Close']
    atr = wilder_atr(h, l, c, 14)
    r2 = rsi(c, 2)
    mid, upper, lower = bollinger(c)
    return pd.DataFrame({'close': c, 'atr': atr, 'rsi2': r2,
                         'boll_mid': mid, 'boll_upper': upper,
                         'boll_lower': lower}).iloc[-1]


# ===== strategy interface: entry/detail -> (bool, reason); exit -> (bool, reason);
#      stop(detail) -> stop price (above entry for a short; sizing proxy). =====
def rsi2short_entry(detail):
    if detail['rsi2'] > RSI2_OVERBOUGHT:
        return True, f"RSI(2) {detail['rsi2']:.1f} > {RSI2_OVERBOUGHT} (overbought, fade rally)"
    return False, f"RSI(2) {detail['rsi2']:.1f} <= {RSI2_OVERBOUGHT}"


def rsi2short_exit(detail, stop, held):
    if held >= MAX_HOLD:
        return True, f"time stop ({held}d >= {MAX_HOLD}d)"
    if detail['rsi2'] <= RSI2_MID:
        return True, f"RSI(2) {detail['rsi2']:.1f} <= {RSI2_MID} (reversion done)"
    return False, "hold"


def rsi2short_stop(detail):
    # no GTC stop in the backtest; 2*ATR distance used for position sizing only.
    return detail['close'] + STOP_ATR * detail['atr']


def bb_short_entry(detail):
    if detail['close'] > detail['boll_upper']:
        return True, (f"close {detail['close']:.4f} > upper band "
                      f"{detail['boll_upper']:.4f} (overbought, fade rally)")
    return False, (f"close {detail['close']:.4f} <= upper band "
                   f"{detail['boll_upper']:.4f}")


def bb_short_exit(detail, stop, held):
    if held >= MAX_HOLD:
        return True, f"time stop ({held}d >= {MAX_HOLD}d)"
    if detail['close'] <= detail['boll_mid']:
        return True, (f"close {detail['close']:.4f} <= mid band "
                      f"{detail['boll_mid']:.4f} (reversion done)")
    return False, "hold"


def bb_short_stop(detail):
    # no GTC stop in the backtest; 2*ATR distance used for position sizing only.
    return detail['close'] + STOP_ATR * detail['atr']


STRATEGIES = [
    {'name': 'RSI2SHORT', 'label': 'RSI(2) fade-rally short',
     'entry': rsi2short_entry, 'exit': rsi2short_exit, 'stop': rsi2short_stop,
     'has_stop_order': False},
    {'name': 'BBANDSHORT', 'label': 'Bollinger fade-short',
     'entry': bb_short_entry, 'exit': bb_short_exit, 'stop': bb_short_stop,
     'has_stop_order': False},
]


# ===== contract =====
def front_month(now=None):
    """Front-month contract (YYYYMM), quarterly Mar/Jun/Sep/Dec (ZB/6B/6A)."""
    now = now or dt.date.today()
    for m in (3, 6, 9, 12):
        if now.month <= m:
            return f"{now.year}{m:02d}"
    return f"{now.year + 1}03"


def held_days(df, entry_date):
    """Number of trading bars strictly after entry date."""
    if not entry_date:
        return 0
    e = pd.Timestamp(entry_date)
    idx = df.index
    if getattr(idx, 'tz', None) is not None:
        e = e.tz_localize(idx.tz)
    return int((idx > e).sum())


# ===== DynamoDB helpers =====
def log_dynamo(table, pk, sk, data):
    table.put_item(Item={'pk': pk, 'sk': sk, **data})


def get_state(table, pk, sk):
    r = table.get_item(Key={'pk': pk, 'sk': sk})
    return r.get('Item')


# ===== per-strategy runner (SHORT) =====
def run_strategy(ib, dynamo, con, sym, df, detail, c, strat, today, mode):
    sname = strat['name']
    tag = f"{sym}_{sname}"                       # e.g. ZB_RSI2SHORT, 6B_BBANDSHORT
    state = get_state(dynamo, f"POSITION#{tag}", 'current') or {}
    pos = int(state.get('pos', 0))               # >0 = short contracts open
    stop = float(state['stop']) if state.get('stop') else None
    entry_date = state.get('entry_date')
    held = held_days(df, entry_date)

    entry, ereason = strat['entry'](detail)

    sig = {
        'signal': 'SHORT' if entry else ('COVER' if pos > 0 else 'NONE'),
        'strategy': sname,
        'close': str(round(detail['close'], 2)),
        'pos': pos, 'held_days': held, 'reason': ereason, 'ts': int(time.time()),
    }
    if sname == 'BBANDSHORT':
        sig.update({
            'boll_upper': str(round(detail['boll_upper'], 4)),
            'boll_mid': str(round(detail['boll_mid'], 4)),
            'atr': str(round(detail['atr'], 4)),
        })
    else:
        sig['rsi2'] = str(round(detail['rsi2'], 2))
    log_dynamo(dynamo, f"SIGNAL#{tag}", today, sig)

    if pos > 0:
        should_exit, xreason = strat['exit'](detail, stop, held)
        if should_exit:
            ib.placeOrder(con, MarketOrder('BUY', pos, tif='DAY'))   # cover short
            ib.sleep(1)
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'COVER', 'qty': pos, 'reason': xreason, 'strategy': sname,
                'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': 0, 'stop': '0', 'entry': '0', 'entry_date': '', 'ts': int(time.time())})
            print(f">>> {mode} {tag} COVER {pos} ({xreason})")
        else:
            print(f">>> {mode} {tag} hold short pos={pos} held={held}d | "
                  f"close {detail['close']:.4f} {strat['label']}")
    elif entry:
        risk = RiskEngine(RiskConfig(risk_budget_usd=BONDFX_RISK_BUDGET))
        allowed, why = risk.can_enter()
        if not allowed:
            print(f">>> {mode} {tag} blocked by risk: {why}")
            return
        stop_price = strat['stop'](detail)       # above entry (short)
        size = risk.position_size(stop_price - detail['close'], point_value=c['point_value'])
        if size > 0:
            ib.placeOrder(con, MarketOrder('SELL', size, tif='DAY'))  # sell-to-open short
            ib.sleep(1)
            log_dynamo(dynamo, f"TRADE#{tag}", f"{today}#{int(time.time())}", {
                'side': 'SELL', 'qty': size, 'entry': str(round(detail['close'], 4)),
                'stop': str(round(stop_price, 4)), 'contract': front_month(),
                'strategy': sname, 'ts': int(time.time())})
            log_dynamo(dynamo, f"POSITION#{tag}", 'current', {
                'pos': size, 'stop': str(round(stop_price, 4)),
                'entry': str(round(detail['close'], 4)),
                'entry_date': today, 'contract': front_month(), 'ts': int(time.time())})
            print(f">>> {mode} {tag} ENTRY: SELL {size} @ market (fade rally), "
                  f"stop {round(stop_price, 4)} ({ereason})")
        else:
            print(f">>> {mode} {tag} size=0 (stop too wide for budget), skip")
    else:
        print(f"[{today}] {mode} {tag} flat, no entry ({ereason})")


# ===== main =====
def main():
    dynamo = boto3.resource('dynamodb', region_name='us-east-1').Table(DYNAMO_TABLE)
    today = dt.date.today().isoformat()
    mode = 'LIVE' if LIVE else 'PAPER'

    # 1. data (fetch before IBKR so we can still log signals if connect fails)
    data = {}
    for c in CONTRACTS:
        df = yf.download(c['data'], period='2y', interval='1d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[c['symbol']] = df

    # 2. connect IBKR (distinct clientId from live.py's 70)
    from ib_insync import IB, Future, MarketOrder
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=71, timeout=8)
    except Exception as e:
        print(f"[{today}] {mode} IBKR connect failed: {e}")
        return

    try:
        for c in CONTRACTS:
            sym = c['symbol']
            df = data[sym]
            if df.empty or len(df) < BOLL_LOOKBACK + 5:
                print(f"[{today}] {sym}: insufficient data ({len(df)} bars)")
                continue
            detail = compute(df)

            # 3. qualify contract (front-month, dynamic roll) — once per symbol
            try:
                con = ib.qualifyContracts(Future(sym, front_month(), c['exchange']))[0]
            except Exception as e:
                print(f"[{today}] {sym}: contract qualify failed "
                      f"(missing trading permission / data subscription?): {e}")
                continue

            for strat in STRATEGIES:
                run_strategy(ib, dynamo, con, sym, df, detail, c, strat, today, mode)
    finally:
        ib.disconnect()


if __name__ == '__main__':
    main()
