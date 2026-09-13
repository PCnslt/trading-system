#!/usr/bin/env python3
"""Independent cross-check of session volume shares using IBKR 5-min TRADES bars.

IBKR useRTH=False gives real consolidated-tape bars 04:00-20:00 ET (NO 20:00-04:00
overnight bars exist on this account — verified). Comparing its pre/reg/post volume
split against Robinhood's 24_7 series validates (or contradicts) the RH numbers.

Writes research/ibkr_volume_crosscheck.json
"""
from __future__ import annotations
import json, os, statistics as st, datetime as dt
from collections import defaultdict

_ROOT = '/home/ubuntu/trading-system'
IB = os.path.join(_ROOT, 'research', 'overnight_bars')
RH = os.path.join(_ROOT, 'research', 'rh_247_bars')


def bucket_min(m):
    if 4 * 60 <= m < 9 * 60 + 30:
        return 'pre'
    if 9 * 60 + 30 <= m < 16 * 60:
        return 'reg'
    if 16 * 60 <= m < 20 * 60:
        return 'post'
    return 'overnight'


def ibkr_split(sym):
    d = json.load(open(os.path.join(IB, f'{sym}.json')))
    if d.get('error') or not d['bars']:
        return None
    v = defaultdict(float)
    hours = set()
    for b in d['bars']:
        t = dt.datetime.fromisoformat(b['t'])
        hours.add(t.hour)
        v[bucket_min(t.hour * 60 + t.minute)] += (b['v'] or 0)
    tot = sum(v.values())
    return {'total': tot, 'hours_present': sorted(hours), 'n_bars': len(d['bars']),
            'window': (d['bars'][0]['t'], d['bars'][-1]['t']),
            **{f'{k}_pct': round(100 * v[k] / tot, 2) if tot else None
               for k in ['pre', 'reg', 'post', 'overnight']}}


def rh_split(sym):
    from zoneinfo import ZoneInfo
    NY = ZoneInfo('America/New_York')
    d = json.load(open(os.path.join(RH, f'{sym}.json')))
    v = defaultdict(float)
    for b in d['bars']:
        if b.get('interpolated') or not (b.get('volume') or 0):
            continue
        t = dt.datetime.fromisoformat(b['begins_at'].replace('Z', '+00:00')).astimezone(NY)
        v[bucket_min(t.hour * 60 + t.minute)] += b['volume']
    tot = sum(v.values())
    return {'total': tot, **{f'{k}_pct': round(100 * v[k] / tot, 2) if tot else None
                             for k in ['pre', 'reg', 'post', 'overnight']}}


def main():
    syms = sorted(f[:-5] for f in os.listdir(IB) if f.endswith('.json'))
    out = []
    print(f"{'sym':7}| {'IBKR pre':>9}{'IBKR reg':>9}{'IBKR post':>10}{'IBKR ON':>9} | "
          f"{'RH pre':>8}{'RH reg':>8}{'RH post':>9}{'RH ON':>7} | {'ext tot IBKR':>13}")
    for s in syms:
        i = ibkr_split(s)
        r = rh_split(s)
        if not i:
            print(f'{s:7}| IBKR fetch failed')
            continue
        ext = (i['pre_pct'] or 0) + (i['post_pct'] or 0)
        out.append({'symbol': s, 'ibkr': i, 'rh': r, 'ibkr_extended_pct': round(ext, 2)})
        print(f"{s:7}| {i['pre_pct']:>9.2f}{i['reg_pct']:>9.2f}{i['post_pct']:>10.2f}{i['overnight_pct']:>9.2f} | "
              f"{r['pre_pct']:>8.2f}{r['reg_pct']:>8.2f}{r['post_pct']:>9.2f}{r['overnight_pct']:>7.2f} | {ext:>13.2f}")
    with open(os.path.join(_ROOT, 'research', 'ibkr_volume_crosscheck.json'), 'w') as f:
        json.dump(out, f, indent=1)
    for src in ['ibkr', 'rh']:
        for k in ['pre_pct', 'reg_pct', 'post_pct', 'overnight_pct']:
            v = [o[src][k] for o in out if o[src][k] is not None]
            print(f'{src:5} {k:16} median={st.median(v):6.2f}%  mean={st.mean(v):6.2f}%')
    ext = [o['ibkr_extended_pct'] for o in out]
    print(f'\nIBKR extended (pre+post) share of tape volume: median={st.median(ext):.2f}% '
          f'mean={st.mean(ext):.2f}% min={min(ext):.2f}% max={max(ext):.2f}%')
    print('IBKR hours present (union):', sorted(set(h for o in out for h in o['ibkr']['hours_present'])))


if __name__ == '__main__':
    main()
