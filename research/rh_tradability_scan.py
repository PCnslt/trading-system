#!/usr/bin/env python3
"""READ-ONLY: 24-Hour-Market eligibility scan over the FULL sub-$50 universe.

Uses the Robinhood MCP read tool `get_equity_tradability`, whose
`all_day_tradability` field gates the 24 Hour Market / overnight session
(`market_hours='all_day_hours'`). NO orders.

Writes research/rh_tradability_full.json
"""
import os, sys, json, time, collections

_ROOT = '/home/ubuntu/trading-system'
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap
bootstrap()
from hardening.rh_client import RHClient

OUT = os.path.join(_ROOT, 'research', 'rh_tradability_full.json')
BATCH = int(os.getenv('BATCH', '8'))


def main():
    syms = json.load(open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']
    syms = list(dict.fromkeys(syms))
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    rh = RHClient()
    acct = rh._resolve_account()
    todo = [s for s in syms if s not in res]
    print(f'universe={len(syms)} cached={len(res)} todo={len(todo)}', flush=True)
    for i in range(0, len(todo), BATCH):
        ch = todo[i:i + BATCH]
        try:
            raw = rh._tool('get_equity_tradability', account_number=acct, symbols=ch)
            got = ((raw.get('data') or {}).get('results') or [])
            for r in got:
                res[r['symbol']] = {'tradeable': r.get('tradeable'), 'state': r.get('state'),
                                    'all_day': r.get('all_day_tradability'),
                                    'frac': r.get('fractional_tradability'),
                                    'short': r.get('short_selling_tradability')}
            for s in ch:
                res.setdefault(s, {'error': 'not_returned'})
        except Exception as e:
            for s in ch:
                res.setdefault(s, {'error': repr(e)[:120]})
            print(f'  {ch} ERR {e!r}', flush=True)
        if i % 80 == 0:
            json.dump(res, open(OUT, 'w'), indent=1)
            print(f'  {i+len(ch)}/{len(todo)}', flush=True)
        time.sleep(0.8)
    json.dump(res, open(OUT, 'w'), indent=1)
    c = collections.Counter(d.get('all_day', d.get('error')) for d in res.values())
    print('\nall_day_tradability across the sub-$50 universe:', dict(c))
    n = sum(c.values())
    trad = c.get('tradable', 0)
    print(f'24-Hour-Market eligible: {trad}/{n} = {100*trad/n:.1f}%')
    unt = sorted(s for s, d in res.items() if d.get('all_day') == 'untradable')
    print(f'NOT eligible ({len(unt)}): {unt}')
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
