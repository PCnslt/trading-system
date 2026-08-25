#!/usr/bin/env python3
"""READ-ONLY Robinhood L1 quote snapshotter for session-spread measurement.

Polls get_equity_quotes (bid/ask/last) + get_equity_price_book (L2 levels) for
the sub-$50 sample and appends every snapshot as JSONL to
research/rh_quote_snaps/<label>.jsonl.

NO orders. Only read tools: get_equity_quotes, get_equity_price_book.

Usage: LABEL=premkt POLLS=4 SLEEP=45 ./venv/bin/python research/rh_spread_snap.py
"""
import os, sys, json, time, datetime as dt

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()
from hardening.rh_client import RHClient
from research.overnight_cost_fetch import SAMPLE

OUT = os.path.join(_ROOT, 'research', 'rh_quote_snaps')
os.makedirs(OUT, exist_ok=True)
LABEL = os.getenv('LABEL', 'snap')
POLLS = int(os.getenv('POLLS', '4'))
SLEEP = float(os.getenv('SLEEP', '45'))


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main():
    rh = RHClient()
    path = os.path.join(OUT, f'{LABEL}.jsonl')
    for p in range(POLLS):
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        rows = {}
        try:
            for r in rh.get_quotes(SAMPLE):
                q = r.get('quote') or {}
                sym = q.get('symbol')
                if not sym:
                    continue
                rows[sym] = {'ts': ts, 'label': LABEL, 'symbol': sym,
                             'bid': q.get('bid_price'), 'ask': q.get('ask_price'),
                             'last': q.get('last_trade_price'),
                             'last_non_reg': q.get('last_non_reg_trade_price'),
                             'venue_bid_time': q.get('venue_bid_time'),
                             'venue_last_trade_time': q.get('venue_last_trade_time'),
                             'venue_last_non_reg_trade_time': q.get('venue_last_non_reg_trade_time'),
                             'prev_close': q.get('previous_close'),
                             'state': q.get('state')}
        except Exception as e:
            rows['_quote_error'] = {'ts': ts, 'error': repr(e)}
        # L2 price book (sizes) — max 4 symbols per call; only on the first poll
        if p == 0:
            for ch in chunks(SAMPLE, 4):
                try:
                    raw = rh._tool('get_equity_price_book', symbols=ch)
                    for b in ((raw.get('data') or {}).get('books') or []):
                        sym = b.get('symbol')
                        if sym in rows:
                            rows[sym]['bids'] = b.get('bids')
                            rows[sym]['asks'] = b.get('asks')
                    for err in ((raw.get('data') or {}).get('errors') or []):
                        s = err.get('symbol') if isinstance(err, dict) else str(err)
                        if s in rows:
                            rows[s]['book_error'] = err
                except Exception as e:
                    for s in ch:
                        if s in rows:
                            rows[s]['book_error'] = repr(e)
        with open(path, 'a') as f:
            for v in rows.values():
                f.write(json.dumps(v) + '\n')
        got = sum(1 for v in rows.values() if isinstance(v, dict) and v.get('bid'))
        print(f'poll {p+1}/{POLLS} {ts} rows={len(rows)} with_bid={got}', flush=True)
        if p < POLLS - 1:
            time.sleep(SLEEP)
    print('DONE', path, flush=True)


if __name__ == '__main__':
    main()
