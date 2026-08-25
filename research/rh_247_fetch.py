#!/usr/bin/env python3
"""READ-ONLY: fetch Robinhood 24_7 + regular 5-min bars for the sub-$50 sample.

Robinhood's own historical surface (`get_equity_historicals`) is the ONLY source
we have that covers the 24-Hour Market overnight session (20:00-04:00 ET) —
IBKR historical bars stop at 04:00/20:00 ET. Each bar carries:
  session:      'pre' | 'reg' | 'post'  (RH's own label)
  interpolated: true  -> NO trade occurred in that bar (price carried forward)
  volume:       shares traded in that bar

NO orders placed. Read tool only: get_equity_historicals.
Writes research/rh_247_bars/<SYM>.json
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

OUT = os.path.join(_ROOT, 'research', 'rh_247_bars')
os.makedirs(OUT, exist_ok=True)
DAYS = int(os.getenv('RH_DAYS', '15'))
INTERVAL = os.getenv('RH_INTERVAL', '5minute')


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main():
    rh = RHClient()
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=DAYS)).strftime('%Y-%m-%dT%H:%M:%SZ')
    todo = [s for s in SAMPLE if not os.path.exists(os.path.join(OUT, f'{s}.json'))]
    print(f'fetching {len(todo)}/{len(SAMPLE)} symbols, {DAYS}d {INTERVAL} bounds=24_7', flush=True)
    for ch in chunks(todo, 4):
        try:
            raw = rh.get_equity_historicals(list(ch), start_time=start,
                                            interval=INTERVAL, bounds='24_7')
            res = ((raw.get('data') or {}).get('results') or [])
        except Exception as e:
            print(f'  {ch} ERR {e!r}', flush=True)
            time.sleep(2)
            continue
        got = set()
        for r in res:
            sym = r.get('symbol')
            if not sym:
                continue
            got.add(sym)
            rec = {'symbol': sym, 'source': 'robinhood_get_equity_historicals',
                   'bounds': '24_7', 'interval': INTERVAL, 'start_time': start,
                   'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'bars': r.get('bars') or []}
            with open(os.path.join(OUT, f'{sym}.json'), 'w') as f:
                json.dump(rec, f)
        print(f'  {list(ch)} -> ' + ', '.join(f'{r.get("symbol")}:{len(r.get("bars") or [])}' for r in res)
              + (f'  MISSING={sorted(set(ch)-got)}' if set(ch) - got else ''), flush=True)
        time.sleep(1.5)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
