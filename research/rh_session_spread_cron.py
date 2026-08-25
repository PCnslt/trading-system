#!/usr/bin/env python3
"""CONTINUOUS session-labelled RH quote + L2 book sampler over the FULL sub-$50 universe.

WHY THIS EXISTS
Neither historical source carries the overnight session:
  - IBKR reqHistoricalData: 04:00-20:00 ET only; BID_ASK/MIDPOINT -> Error 162.
  - RH get_equity_historicals bounds=24_7: pads 20:00-04:00 bars but reports ZERO
    volume/prints even for TSLA/NVDA/SPY -> an API reporting gap, not an absence
    of trading.
So real 24-hour execution cost can only be measured by sampling the LIVE quote
surface inside every session, continuously. This runs on cron 24/5.

WHAT IT WRITES  (append-only, one row per symbol per sweep)
  research/rh_quote_snaps/session_<YYYY-MM-DD>.jsonl
    session: overnight|pre|reg|auction|post   (ET wall clock)
    bid/ask/last/last_non_reg + venue timestamps  (L1, every symbol every sweep)
    bids[]/asks[] L2 levels                       (rotating slice, full universe
                                                   covered every ROTATION sweeps)

READ-ONLY: get_equity_quotes + get_equity_price_book. Never places an order.
"""
import os, sys, json, datetime as dt
from zoneinfo import ZoneInfo

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()
from hardening.rh_client import RHClient

NY = ZoneInfo('America/New_York')
OUT = os.path.join(_ROOT, 'research', 'rh_quote_snaps')
STATE = os.path.join(OUT, '_rotation_state.json')
os.makedirs(OUT, exist_ok=True)

QUOTE_CHUNK = int(os.getenv('QUOTE_CHUNK', '40'))
BOOK_SLICE = int(os.getenv('BOOK_SLICE', '60'))   # L2 names per sweep (4/call)


def universe():
    p = os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')
    syms = list(dict.fromkeys(json.load(open(p))['symbols']))
    return syms


def session_of(t):
    m = t.hour * 60 + t.minute
    if 240 <= m < 570:
        return 'pre'
    if 570 <= m < 960:
        return 'reg'
    if 960 <= m < 965:
        return 'auction'
    if 965 <= m < 1200:
        return 'post'
    return 'overnight'


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main():
    now = dt.datetime.now(NY)
    sess = session_of(now)
    # RH 24-Hour Market runs Sun 20:00 -> Fri 20:00 ET. Skip the true weekend gap.
    wd = now.weekday()          # Mon=0 .. Sun=6
    if (wd == 5) or (wd == 4 and sess == 'overnight' and now.hour >= 20) \
            or (wd == 6 and not (sess == 'overnight' and now.hour >= 20)):
        print(f'{now.isoformat()} sess={sess} weekday={wd} — market closed, skip')
        return

    syms = universe()
    rh = RHClient()
    rows = {}
    nq = 0
    for ch in chunks(syms, QUOTE_CHUNK):
        try:
            for r in rh.get_quotes(list(ch)):
                q = r.get('quote') or {}
                sym = q.get('symbol')
                if not sym:
                    continue
                nq += 1
                rows[sym] = {
                    'ts': now.astimezone(dt.timezone.utc).isoformat(), 'et': now.isoformat(),
                    'session': sess, 'symbol': sym,
                    'bid': q.get('bid_price'), 'ask': q.get('ask_price'),
                    'last': q.get('last_trade_price'),
                    'last_non_reg': q.get('last_non_reg_trade_price'),
                    'venue_bid_time': q.get('venue_bid_time'),
                    'venue_ask_time': q.get('venue_ask_time'),
                    'venue_last_trade_time': q.get('venue_last_trade_time'),
                    'venue_last_non_reg_trade_time': q.get('venue_last_non_reg_trade_time'),
                    'prev_close': q.get('previous_close'), 'state': q.get('state')}
        except Exception as e:
            print(f'  quote chunk {ch[:3]}... ERR {e!r}')

    # rotating L2 slice so the whole universe gets depth coverage over time
    try:
        off = json.load(open(STATE)).get('offset', 0)
    except Exception:
        off = 0
    sl = [syms[(off + i) % len(syms)] for i in range(min(BOOK_SLICE, len(syms)))]
    nb = 0
    for ch in chunks(sl, 4):
        try:
            raw = rh._tool('get_equity_price_book', symbols=list(ch))
            for b in ((raw.get('data') or {}).get('books') or []):
                if b.get('symbol') in rows:
                    rows[b['symbol']]['bids'] = b.get('bids')
                    rows[b['symbol']]['asks'] = b.get('asks')
                    nb += 1
        except Exception as e:
            for s in ch:
                if s in rows:
                    rows[s]['book_error'] = repr(e)
    with open(STATE, 'w') as f:
        json.dump({'offset': (off + BOOK_SLICE) % len(syms)}, f)

    path = os.path.join(OUT, f'session_{now.date()}.jsonl')
    with open(path, 'a') as f:
        for v in rows.values():
            f.write(json.dumps(v) + '\n')

    def _pos(x):
        try:
            return float(x) > 0
        except (TypeError, ValueError):
            return False
    live = sum(1 for v in rows.values() if _pos(v.get('bid')) and _pos(v.get('ask')))
    print(f'{now.isoformat()} sess={sess} universe={len(syms)} quoted={nq} '
          f'two_sided={live} books={nb} -> {path}')


if __name__ == '__main__':
    main()
