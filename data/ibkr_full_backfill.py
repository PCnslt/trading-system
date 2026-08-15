#!/usr/bin/env python3
"""IBKR FULL-DEPTH historical backfill -> S3 `ibkr/` prefix family.

The ONE collector for the IBKR-only pivot (owner directive 2026-08-15):
"get everything as much as possible, all data in our database; IBKR is the
source; stop yfinance for broker-available assets."

Empirical depth caps (verified live 2026-08-15 against gateway :4002, paper
DUR193467 — treat as authoritative):

  - 1-second bars: Error 162 "invalid step: 1" -> NO second-level history.
    Finest history = 1-min.
  - US equities daily: 20y+ (AAPL 5027 bars back to 2006-08). Entitled.
  - Futures daily: CONTFUT ~3y index (ES 785 bars -> 2023-06) / ~16mo rates
    (ZB 342 bars -> 2025-04). **20y futures is NOT achievable on this paper
    account**: `reqContractDetails(includeExpired=True)` returns 0 expired
    contracts (only the full FUTURE chain), and an expired contract month
    (e.g. Future('ES','202006','CME')) -> Error 200 "No security definition".
    Verified 2026-08-15. Deep 20y futures remains yfinance `yf/futures/` only.
  - 1-min bars: monthly chunks only ("1 M" = ~8.6k equity bars / 75s;
    "3 M" times out ~25k bars). ~1-2y achievable month-by-month.
  - Crypto micros MBT/MET: daily ~9-12mo (MBT 249 bars -> 2025-08); 1-min
    ~12mo. Entitled.
  - US options: chains metadata only (options_chains.py). Historical option
    BARS are a SEPARATE paid subscription — NOT entitled. Tag "shallow by design".

Pacing (IBKR historical data limits, TWS API reference):
  - max 60 requests / 10 min; identical req within 15s or 6+ same-contract
    reqs within 2s = pacing violation. Default pacing ~5s/req with exponential
    backoff on pacing violations.

Storage (parquet, per-object S3 metadata `quality=BROKER`):
  ibkr/equities/daily/{sym}.parquet          full daily history
  ibkr/equities/1min/{sym}/{yyyy-mm}.parquet 1-min, month-partitioned
  ibkr/futures/daily/{sym}_continuous.parquet CONTFUT daily (continuous)
  ibkr/futures/daily/{sym}/{expiry}.parquet   per-contract daily (current chain)
  ibkr/futures/1min/{sym}/{yyyy-mm}.parquet  1-min, front contract
  ibkr/crypto/daily/{sym}.parquet             MBT/MET daily
  ibkr/crypto/1min/{sym}/{yyyy-mm}.parquet   MBT/MET 1-min
  ibkr/options/{sym}/chains.json              (options_chains.py, existing)

READ-ONLY on the trading side: reqHistoricalData + reqContractDetails + S3
put_object only. No orders, no DynamoDB writes, no RUN#/SIGNAL/POSITION items.
clientId 50 (never 70/71/72/73/74/75/76/77 trading/collector clients).

Resumable + idempotent: checkpoint `data/ibkr_backfill_state.json` records each
finished object key; re-runs skip completed keys. A gateway 2FA gap resumes
without re-pulling.

Usage:
  python data/ibkr_full_backfill.py --mode equities --kind daily [--symbols AAPL,MSFT] [--limit N] [--dry-run]
  python data/ibkr_full_backfill.py --mode equities --kind 1min
  python data/ibkr_full_backfill.py --mode futures  --kind daily
  python data/ibkr_full_backfill.py --mode futures  --kind 1min
  python data/ibkr_full_backfill.py --mode crypto   --kind daily|1min
  python data/ibkr_full_backfill.py --mode options
  python data/ibkr_full_backfill.py --verify     # per-prefix counts + date ranges
  python data/ibkr_full_backfill.py --gaps       # list 0-bar (gapped) symbols
"""
import os
import sys
import json
import time
import math
import argparse
import calendar
import datetime as dt

import boto3
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from ib_insync import IB, Future, ContFuture, Stock, util  # noqa: E402

IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', '4002'))
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

CLIENT_ID = 50            # distinct from all trading/collector clients (70-77, 90)
PACING_S = float(os.getenv('IBKR_FULLBACKFILL_PACING_S', '5'))
PACING_BACKOFF_S = float(os.getenv('IBKR_FULLBACKFILL_BACKOFF_S', '60'))
FETCH_TIMEOUT = 240       # per reqHistoricalData (1-min monthly chunks need ~75-120s)
DAILY_TIMEOUT = 120       # daily requests are fast
RETRIES = 1

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ibkr_backfill_state.json')

NY = 'America/New_York'

EQUITY_DAILY_DUR = '20 Y'
EQUITY_1MIN_MONTHS = 24       # ~2y of 1-min (month-partitioned)
FUTURES_DAILY_DUR = '5 Y'     # requested; CONTFUT returns ~3y index / ~16mo rates
FUTURES_1MIN_MONTHS = 24
CRYPTO_DAILY_DUR = '2 Y'
CRYPTO_1MIN_MONTHS = 12

# 16 liquid futures for 1-min (owner-specified), plus MBT/MET handled as crypto.
FUTURES_1MIN_SYMBOLS = ['ES', 'NQ', 'MES', 'MNQ', 'RTY', 'YM',
                        'ZB', 'ZN', 'ZF', 'ZT', 'GC', 'SI', 'CL', 'NG', 'HG', '6M']
CRYPTO_SYMBOLS = ['MBT', 'MET']

QUALITY_META = {'quality': 'BROKER'}


class GatewayDown(BaseException):
    """Gateway unreachable (2FA gap / maintenance). Propagates past the per-symbol
    `except Exception` handlers so the run EXITS (systemd Restart=on-failure
    relaunches it; the checkpoint resumes) instead of churning every remaining
    symbol as FAILED."""


_s3 = None


def s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client('s3', region_name=AWS_REGION)
    return _s3


def put_parquet(key, df):
    """DataFrame -> parquet bytes -> S3 (streamed, per-object). quality=BROKER."""
    import io
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine='pyarrow')
    s3().put_object(Bucket=S3_BUCKET, Key=key, Body=buf.getvalue(),
                    Metadata=QUALITY_META)
    return f's3://{S3_BUCKET}/{key}'


# ---- checkpoint ----
def load_state():
    if os.path.isfile(STATE_PATH):
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'version': 1, 'jobs': {}}


def save_state(state):
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)


def is_done(state, key):
    return bool(state['jobs'].get(key, {}).get('done'))


def mark_done(state, key, nbars, first=None, last=None, gapped=False):
    state['jobs'][key] = {'done': True, 'nbars': nbars, 'first': first,
                          'last': last, 'gapped': gapped,
                          'ts': int(time.time())}


# ---- request + bar helpers (mirror the proven bot/backfill_bars.py path) ----
def _ensure_connected(ib):
    """Reconnect if the gateway dropped us (04:00 daily restart etc.)."""
    if ib.isConnected():
        return True
    try:
        ib.disconnect()
    except Exception:
        pass
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=15, readonly=True)
        ib.sleep(2)
        print(f"      [reconnect] clientId={CLIENT_ID} accounts={ib.managedAccounts()}", flush=True)
        return True
    except Exception as e:
        print(f"      [reconnect] FAILED {e!r}", flush=True)
        return False


def req_hist(ib, con, duration, bar_size, end='', use_rth=True, timeout=None):
    """reqHistoricalData with pacing + backoff on pacing violations / timeouts.

    Auto-reconnects on gateway disconnect (04:00 restart) so a long backfill
    survives the daily gateway cycle; the checkpoint makes any 2FA gap
    resumable on restart.
    """
    timeout = timeout or FETCH_TIMEOUT
    backoff = PACING_BACKOFF_S
    for attempt in range(RETRIES + 1):
        if not ib.isConnected() and not _ensure_connected(ib):
            time.sleep(30)
            if not _ensure_connected(ib):
                raise GatewayDown('gateway not reachable (2FA/maintenance)')
        try:
            return ib.reqHistoricalData(con, endDateTime=end, durationStr=duration,
                                        barSizeSetting=bar_size, whatToShow='TRADES',
                                        useRTH=use_rth, formatDate=2, timeout=timeout)
        except Exception as e:
            msg = str(e).lower()
            if 'pacing' in msg:
                print(f"      [pacing] backoff {backoff:.0f}s ({e!r})", flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, 600)
            elif any(k in msg for k in ('connect', 'socket', 'not connected', 'broken pipe')):
                print(f"      [disconnect] reconnect attempt ({e!r})", flush=True)
                if not _ensure_connected(ib):
                    raise GatewayDown('gateway not reachable (2FA/maintenance)')
            elif 'cancelled' in msg or 'timeout' in msg:
                if attempt < RETRIES:
                    print(f"      [timeout/cancelled] retry {attempt + 1}", flush=True)
                    time.sleep(10)
                else:
                    raise
            else:
                raise
    return []


def load_bars_df(ib, con, duration, bar_size, end='', use_rth=True, timeout=None):
    """reqHistoricalData -> OHLCV DataFrame with America/New_York tz index.

    Mirrors bot/backfill_bars._load_bars (proven). Empty -> empty DF.
    """
    bars = req_hist(ib, con, duration, bar_size, end=end, use_rth=use_rth, timeout=timeout)
    if not bars:
        return pd.DataFrame()
    df = util.df(bars).rename(columns=str.title)
    df = df.set_index('Date')
    if getattr(df.index, 'tz', None) is None:
        df.index = pd.to_datetime(df.index, utc=True)
    df.index = df.index.tz_convert(NY)
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]


def _session_date(idx):
    """Recover the IBKR session date (daily bars carry date-only)."""
    if idx.tz is None:
        return idx.date()
    return idx.tz_convert('UTC').date()


def daily_out(df):
    """NY-index daily DF -> {date, open, high, low, close, volume}."""
    out = pd.DataFrame({
        'date': [_session_date(i).isoformat() for i in df.index],
        'open': df['Open'].astype(float),
        'high': df['High'].astype(float),
        'low': df['Low'].astype(float),
        'close': df['Close'].astype(float),
        'volume': df['Volume'].astype(float),
    })
    return out


def min_out(df, y, m):
    """NY-index 1-min DF -> month-filtered, deduped {ts(epoch), o/h/l/c/v}."""
    mask = [i.strftime('%Y-%m') == f'{y}-{m:02d}' for i in df.index]
    d = df[mask].copy()
    if d.empty:
        return d
    d = d[~d.index.duplicated(keep='last')]
    out = pd.DataFrame({
        'ts': [int(i.timestamp()) for i in d.index],
        'open': d['Open'].astype(float),
        'high': d['High'].astype(float),
        'low': d['Low'].astype(float),
        'close': d['Close'].astype(float),
        'volume': d['Volume'].astype(float),
    })
    return out


# ---- month window generator ----
def month_windows(n_months_back, today=None):
    """Yield (y, m, end, duration) for each month going back from the current."""
    today = today or dt.date.today()
    y, m = today.year, today.month
    for _ in range(n_months_back):
        if (y, m) == (today.year, today.month):
            end = ''          # now (partial month)
            dur = '1 M'
        else:
            last = calendar.monthrange(y, m)[1]
            end = f"{y}{m:02d}{last:02d} 23:59:59"
            dur = f"{last} D"   # exactly the calendar month
        yield y, m, end, dur
        m -= 1
        if m == 0:
            y, m = y - 1, 12


# ================= EQUITIES =================
def equity_symbols(liquid=False):
    """Full common-stock universe or the ~1000 liquid subset (from data_engine)."""
    try:
        from data_engine.universe import load_symbols, load_liquid_symbols
        if liquid:
            syms = load_liquid_symbols()
            print(f"[universe] liquid subset: {len(syms)} symbols", flush=True)
            return syms
        syms = load_symbols()
        print(f"[universe] full common-stock universe: {len(syms)} symbols", flush=True)
        return syms
    except Exception as e:
        print(f"[universe] data_engine load failed ({e!r}); falling back to S3 mirror", flush=True)
        try:
            obj = s3().get_object(Bucket=S3_BUCKET,
                                  Key='data-engine/universe/us_common_stocks.json')
            payload = json.loads(obj['Body'].read().decode())
            return [s['symbol'] for s in payload.get('symbols', [])]
        except Exception as e2:
            print(f"[universe] S3 mirror also failed: {e2!r}", flush=True)
            return []


def collect_equity_daily(ib, syms, dry_run=False, state=None):
    print(f"\n=== EQUITIES DAILY ({len(syms)} symbols, {EQUITY_DAILY_DUR}) ===", flush=True)
    ok = empty = failed = 0
    gaps = []
    for i, sym in enumerate(syms):
        key = f'equities/daily/{sym}'
        if is_done(state, key):
            continue
        try:
            con = Stock(sym, 'SMART', 'USD')
            ib.qualifyContracts(con)
            df = load_bars_df(ib, con, EQUITY_DAILY_DUR, '1 day', timeout=DAILY_TIMEOUT)
            if df.empty:
                empty += 1
                gaps.append(sym)
                mark_done(state, key, 0, gapped=True)
                print(f"  [{i + 1}/{len(syms)}] {sym}: 0 bars (GAPPED)", flush=True)
            else:
                out = daily_out(df)
                if not dry_run:
                    put_parquet(f'ibkr/{key}.parquet', out)
                ok += 1
                first, last = out['date'].iloc[0], out['date'].iloc[-1]
                mark_done(state, key, len(out), first, last)
                print(f"  [{i + 1}/{len(syms)}] {sym}: {len(out)} bars {first}..{last}", flush=True)
        except Exception as e:
            failed += 1
            print(f"  [{i + 1}/{len(syms)}] {sym}: FAILED {e!r}", flush=True)
            if 'no security definition' in str(e).lower():
                gaps.append(sym)
                mark_done(state, key, 0, gapped=True)
        if (i + 1) % 100 == 0:
            save_state(state)
            print(f"  [checkpoint] saved at {i + 1} symbols (ok={ok} empty={empty} failed={failed})", flush=True)
        time.sleep(PACING_S)
    save_state(state)
    print(f"[equities/daily] ok={ok} empty={empty} failed={failed}", flush=True)
    return ok, empty, failed, gaps


def collect_equity_1min(ib, syms, dry_run=False, state=None):
    print(f"\n=== EQUITIES 1-MIN ({len(syms)} symbols, {EQUITY_1MIN_MONTHS} months) ===", flush=True)
    ok = failed = 0
    for i, sym in enumerate(syms):
        con = Stock(sym, 'SMART', 'USD')
        try:
            ib.qualifyContracts(con)
        except Exception as e:
            print(f"  [{i + 1}/{len(syms)}] {sym}: qualify FAILED {e!r}", flush=True)
            failed += 1
            continue
        n_sym = 0
        for (y, m, end, dur) in month_windows(EQUITY_1MIN_MONTHS):
            key = f'equities/1min/{sym}/{y}-{m:02d}'
            if is_done(state, key):
                continue
            try:
                df = load_bars_df(ib, con, dur, '1 min', end=end)
                if df.empty:
                    mark_done(state, key, 0, gapped=True)
                    continue
                out = min_out(df, y, m)
                if out.empty:
                    mark_done(state, key, 0, gapped=True)
                    continue
                if not dry_run:
                    put_parquet(f'ibkr/{key}.parquet', out)
                ok += 1
                n_sym += len(out)
                mark_done(state, key, len(out))
            except Exception as e:
                failed += 1
                print(f"    {sym} {y}-{m:02d}: FAILED {e!r}", flush=True)
            time.sleep(PACING_S)
        print(f"  [{i + 1}/{len(syms)}] {sym}: {n_sym} 1-min bars total", flush=True)
        save_state(state)
    save_state(state)
    print(f"[equities/1min] ok={ok} failed={failed}", flush=True)
    return ok, failed


# ================= FUTURES =================
def future_symbols():
    from data.symbol_registry import FUTURES
    return [(d['sym'], d['exchange']) for d in FUTURES]


def _resolve_contfuture(ib, sym, exchange):
    try:
        cf = ib.qualifyContracts(ContFuture(sym, exchange, 'USD'))
        return cf[0] if cf else None
    except Exception:
        return None


def _resolve_front(ib, sym, exchange):
    from bot.futures_contracts import resolve_front
    try:
        return resolve_front(ib, sym, exchange)
    except Exception:
        return None


def collect_futures_daily(ib, dry_run=False, state=None):
    specs = future_symbols()
    print(f"\n=== FUTURES DAILY ({len(specs)} symbols: CONTFUT + per-contract chain) ===", flush=True)
    ok = empty = failed = 0
    gaps = []
    for i, (sym, exchange) in enumerate(specs):
        # (a) continuous series
        key_cont = f'futures/daily/{sym}/_continuous'
        if not is_done(state, key_cont):
            cf = _resolve_contfuture(ib, sym, exchange)
            if cf is not None:
                try:
                    df = load_bars_df(ib, cf, FUTURES_DAILY_DUR, '1 day', timeout=DAILY_TIMEOUT)
                    if not df.empty:
                        out = daily_out(df)
                        if not dry_run:
                            put_parquet(f'ibkr/futures/daily/{sym}_continuous.parquet', out)
                        ok += 1
                        mark_done(state, key_cont, len(out), out['date'].iloc[0], out['date'].iloc[-1])
                        print(f"  [{i + 1}/{len(specs)}] {sym}: CONTFUT {len(out)} bars "
                              f"{out['date'].iloc[0]}..{out['date'].iloc[-1]}", flush=True)
                    else:
                        empty += 1
                        gaps.append(sym)
                        mark_done(state, key_cont, 0, gapped=True)
                except Exception as e:
                    failed += 1
                    print(f"  [{i + 1}/{len(specs)}] {sym}: CONTFUT FAILED {e!r}", flush=True)
            else:
                empty += 1
                gaps.append(sym)
                mark_done(state, key_cont, 0, gapped=True)
                print(f"  [{i + 1}/{len(specs)}] {sym}: CONTFUT no contract (GAPPED)", flush=True)
            time.sleep(PACING_S)

        # (b) per-contract daily for the current chain
        try:
            cd = ib.reqContractDetails(Future(sym, exchange=exchange))
            if not cd and exchange != '':
                cd = ib.reqContractDetails(Future(sym, exchange=''))
        except Exception:
            cd = []
        for c in cd[:6]:  # current chain, front ~6 expiries
            exp = c.contract.lastTradeDateOrContractMonth
            key = f'futures/daily/{sym}/{exp}'
            if is_done(state, key):
                continue
            try:
                df = load_bars_df(ib, c.contract, FUTURES_DAILY_DUR, '1 day', timeout=DAILY_TIMEOUT)
                if df.empty:
                    mark_done(state, key, 0, gapped=True)
                    continue
                out = daily_out(df)
                if not dry_run:
                    put_parquet(f'ibkr/{key}.parquet', out)
                ok += 1
                mark_done(state, key, len(out), out['date'].iloc[0], out['date'].iloc[-1])
                print(f"    {sym} {exp}: {len(out)} bars {out['date'].iloc[0]}..{out['date'].iloc[-1]}", flush=True)
            except Exception as e:
                failed += 1
                print(f"    {sym} {exp}: FAILED {e!r}", flush=True)
            time.sleep(PACING_S)
        save_state(state)
    save_state(state)
    print(f"[futures/daily] ok={ok} empty={empty} failed={failed}", flush=True)
    return ok, empty, failed, gaps


def collect_futures_1min(ib, dry_run=False, state=None):
    specs = future_symbols()
    exmap = dict(specs)
    syms = [s for s in FUTURES_1MIN_SYMBOLS if s in exmap]
    print(f"\n=== FUTURES 1-MIN ({len(syms)} liquid symbols, front contract, "
          f"{FUTURES_1MIN_MONTHS} months) ===", flush=True)
    ok = failed = 0
    for i, sym in enumerate(syms):
        exchange = exmap[sym]
        con = _resolve_front(ib, sym, exchange)
        if con is None:
            print(f"  [{i + 1}/{len(syms)}] {sym}: no front contract (GAPPED)", flush=True)
            continue
        n_sym = 0
        for (y, m, end, dur) in month_windows(FUTURES_1MIN_MONTHS):
            key = f'futures/1min/{sym}/{y}-{m:02d}'
            if is_done(state, key):
                continue
            try:
                df = load_bars_df(ib, con, dur, '1 min', end=end, use_rth=True)
                if df.empty:
                    mark_done(state, key, 0, gapped=True)
                    continue
                out = min_out(df, y, m)
                if out.empty:
                    mark_done(state, key, 0, gapped=True)
                    continue
                if not dry_run:
                    put_parquet(f'ibkr/{key}.parquet', out)
                ok += 1
                n_sym += len(out)
                mark_done(state, key, len(out))
            except Exception as e:
                failed += 1
                print(f"    {sym} {y}-{m:02d}: FAILED {e!r}", flush=True)
            time.sleep(PACING_S)
        print(f"  [{i + 1}/{len(syms)}] {sym}: {n_sym} 1-min bars total", flush=True)
        save_state(state)
    save_state(state)
    print(f"[futures/1min] ok={ok} failed={failed}", flush=True)
    return ok, failed


# ================= CRYPTO (micros) =================
def collect_crypto_daily(ib, dry_run=False, state=None):
    print(f"\n=== CRYPTO MICROS DAILY ({CRYPTO_SYMBOLS}) ===", flush=True)
    ok = empty = failed = 0
    gaps = []
    for sym in CRYPTO_SYMBOLS:
        key = f'crypto/daily/{sym}'
        if is_done(state, key):
            continue
        try:
            cd = ib.reqContractDetails(Future(sym, exchange='CME'))
            if not cd:
                empty += 1
                gaps.append(sym)
                mark_done(state, key, 0, gapped=True)
                print(f"  {sym}: no contract (GAPPED)", flush=True)
                continue
            con = cd[0].contract
            df = load_bars_df(ib, con, CRYPTO_DAILY_DUR, '1 day', timeout=DAILY_TIMEOUT)
            if df.empty:
                empty += 1
                gaps.append(sym)
                mark_done(state, key, 0, gapped=True)
                continue
            out = daily_out(df)
            if not dry_run:
                put_parquet(f'ibkr/{key}.parquet', out)
            ok += 1
            mark_done(state, key, len(out), out['date'].iloc[0], out['date'].iloc[-1])
            print(f"  {sym}: {len(out)} bars {out['date'].iloc[0]}..{out['date'].iloc[-1]}", flush=True)
        except Exception as e:
            failed += 1
            print(f"  {sym}: FAILED {e!r}", flush=True)
        time.sleep(PACING_S)
    save_state(state)
    print(f"[crypto/daily] ok={ok} empty={empty} failed={failed}", flush=True)
    return ok, empty, failed, gaps


def collect_crypto_1min(ib, dry_run=False, state=None):
    print(f"\n=== CRYPTO MICROS 1-MIN ({CRYPTO_SYMBOLS}, {CRYPTO_1MIN_MONTHS} months) ===", flush=True)
    ok = failed = 0
    for sym in CRYPTO_SYMBOLS:
        try:
            cd = ib.reqContractDetails(Future(sym, exchange='CME'))
            con = cd[0].contract if cd else None
        except Exception:
            con = None
        if con is None:
            print(f"  {sym}: no contract (GAPPED)", flush=True)
            continue
        n_sym = 0
        for (y, m, end, dur) in month_windows(CRYPTO_1MIN_MONTHS):
            key = f'crypto/1min/{sym}/{y}-{m:02d}'
            if is_done(state, key):
                continue
            try:
                df = load_bars_df(ib, con, dur, '1 min', end=end, use_rth=True)
                if df.empty:
                    mark_done(state, key, 0, gapped=True)
                    continue
                out = min_out(df, y, m)
                if out.empty:
                    mark_done(state, key, 0, gapped=True)
                    continue
                if not dry_run:
                    put_parquet(f'ibkr/{key}.parquet', out)
                ok += 1
                n_sym += len(out)
                mark_done(state, key, len(out))
            except Exception as e:
                failed += 1
                print(f"    {sym} {y}-{m:02d}: FAILED {e!r}", flush=True)
            time.sleep(PACING_S)
        print(f"  {sym}: {n_sym} 1-min bars total", flush=True)
        save_state(state)
    save_state(state)
    print(f"[crypto/1min] ok={ok} failed={failed}", flush=True)
    return ok, failed


# ================= OPTIONS =================
def collect_options(ib, dry_run=False, state=None):
    """Options: chain metadata already in options_chains.py. Historical option
    BARS are a separate paid subscription (NOT entitled on paper) — log the gap."""
    print("\n=== OPTIONS ===", flush=True)
    print("  Chains metadata: already collected (options_chains.py -> options/<sym>/chains.json).", flush=True)
    print("  Historical option BARS: NOT entitled on paper DUR193467 (separate paid", flush=True)
    print("  subscription). Tagged 'shallow by design'. Skipping reqHistoricalData on options.", flush=True)
    return 0, 0


# ================= verify / gaps =================
def verify():
    print("=== IBKR ARCHIVE VERIFY (counts per prefix) ===", flush=True)
    prefixes = ['ibkr/equities/daily/', 'ibkr/equities/1min/',
                'ibkr/futures/daily/', 'ibkr/futures/1min/',
                'ibkr/crypto/daily/', 'ibkr/crypto/1min/']
    pag = s3().get_paginator('list_objects_v2')
    for pfx in prefixes:
        n = 0
        sample = []
        for pg in pag.paginate(Bucket=S3_BUCKET, Prefix=pfx, PaginationConfig={'PageSize': 1000}):
            for o in pg.get('Contents', []):
                n += 1
                if len(sample) < 3:
                    sample.append(o['Key'])
        print(f"  {pfx}: {n} objects  (e.g. {sample})", flush=True)


def gaps_report():
    print("=== GAPPED SYMBOLS (0 bars) from checkpoint ===", flush=True)
    state = load_state()
    gaps = {k: v for k, v in state['jobs'].items() if v.get('gapped')}
    if not gaps:
        print("  none recorded", flush=True)
    for k in sorted(gaps):
        print(f"  {k}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['equities', 'futures', 'crypto', 'options'], default=None)
    ap.add_argument('--kind', choices=['daily', '1min'], default=None)
    ap.add_argument('--symbols', default='', help='comma subset (equities)')
    ap.add_argument('--limit', type=int, default=0, help='max symbols this run')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--gaps', action='store_true')
    args = ap.parse_args()

    if args.verify:
        verify()
        return
    if args.gaps:
        gaps_report()
        return

    if not args.mode:
        ap.error('--mode is required (or use --verify / --gaps)')

    state = load_state()
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=15, readonly=True)
        print(f"connected clientId={CLIENT_ID} accounts={ib.managedAccounts()} "
              f"(READ-ONLY; dry_run={args.dry_run}, pacing={PACING_S}s)", flush=True)
        ib.sleep(2)

        if args.mode == 'equities':
            liquid = (args.kind == '1min')
            syms = equity_symbols(liquid=liquid)
            if args.symbols:
                want = {s.strip().upper() for s in args.symbols.split(',') if s.strip()}
                syms = [s for s in syms if s in want]
            if args.limit:
                syms = syms[:args.limit]
            if args.kind == 'daily':
                collect_equity_daily(ib, syms, args.dry_run, state)
            else:
                collect_equity_1min(ib, syms, args.dry_run, state)
        elif args.mode == 'futures':
            if args.kind == 'daily':
                collect_futures_daily(ib, args.dry_run, state)
            else:
                collect_futures_1min(ib, args.dry_run, state)
        elif args.mode == 'crypto':
            if args.kind == 'daily':
                collect_crypto_daily(ib, args.dry_run, state)
            else:
                collect_crypto_1min(ib, args.dry_run, state)
        elif args.mode == 'options':
            collect_options(ib, args.dry_run, state)
    except GatewayDown as e:
        save_state(state)
        print(f"\nGATEWAY DOWN: {e} — exiting non-zero (systemd will relaunch; "
              f"checkpoint resumes).", flush=True)
        sys.exit(1)
    finally:
        ib.disconnect()

    print("\nDONE. Trading side untouched: no orders, no DynamoDB, no RUN#/SIGNAL/POSITION.", flush=True)


if __name__ == '__main__':
    main()
