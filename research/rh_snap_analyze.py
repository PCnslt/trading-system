#!/usr/bin/env python3
"""Analyse RH L1/L2 quote snapshots: quoted spread bp + depth at top of book.

Usage: ./venv/bin/python research/rh_snap_analyze.py <label> [<label2> ...]
Prints a per-symbol table and writes research/rh_snap_summary_<label>.json
"""
import json, os, sys, statistics as st

_ROOT = '/home/ubuntu/trading-system'
SNAP = os.path.join(_ROOT, 'research', 'rh_quote_snaps')


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def analyse(label):
    path = os.path.join(SNAP, f'{label}.jsonl')
    rows = [json.loads(l) for l in open(path)]
    by = {}
    for r in rows:
        b, a = _f(r.get('bid')), _f(r.get('ask'))
        if not b or not a or a <= 0 or b <= 0 or a < b:
            continue
        mid = (a + b) / 2
        by.setdefault(r['symbol'], []).append({
            'spr_bp': (a - b) / mid * 1e4, 'mid': mid,
            'bids': r.get('bids'), 'asks': r.get('asks'),
            'last': _f(r.get('last')), 'last_non_reg': _f(r.get('last_non_reg')),
        })
    out = {}
    for s, v in by.items():
        mid = st.mean(x['mid'] for x in v)
        spr = [x['spr_bp'] for x in v]
        bk = next((x for x in v if x.get('bids')), None)
        top_bid_qty = top_ask_qty = None
        notional_5lvl_bid = None
        if bk:
            bids, asks = bk['bids'] or [], bk['asks'] or []
            if bids:
                top_bid_qty = bids[0].get('quantity')
                notional_5lvl_bid = sum(_f(x.get('price')) * (x.get('quantity') or 0)
                                        for x in bids[:5] if _f(x.get('price')))
            if asks:
                top_ask_qty = asks[0].get('quantity')
        out[s] = {'polls': len(v), 'mid': round(mid, 4),
                  'spread_bp_median': round(st.median(spr), 1),
                  'spread_bp_min': round(min(spr), 1), 'spread_bp_max': round(max(spr), 1),
                  'top_bid_qty': top_bid_qty, 'top_ask_qty': top_ask_qty,
                  'bid_notional_5lvl': round(notional_5lvl_bid) if notional_5lvl_bid else None}
    return out


def main():
    labels = sys.argv[1:] or ['premarket_0917']
    res = {lab: analyse(lab) for lab in labels}
    syms = sorted(set().union(*[set(v) for v in res.values()]))
    hdr = f"{'sym':7}{'mid':>8}" + ''.join(f'{lab[:12]:>14}' for lab in labels) + f"{'topbid':>8}{'topask':>8}"
    print(hdr)
    for s in syms:
        first = next((res[l][s] for l in labels if s in res[l]), {})
        line = f"{s:7}{first.get('mid', 0):>8.2f}"
        for lab in labels:
            d = res[lab].get(s)
            line += f"{(str(d['spread_bp_median']) + 'bp') if d else '-':>14}"
        line += f"{str(first.get('top_bid_qty')):>8}{str(first.get('top_ask_qty')):>8}"
        print(line)
    for lab in labels:
        vals = [d['spread_bp_median'] for d in res[lab].values()]
        print(f'{lab}: n={len(vals)} median={st.median(vals):.1f}bp mean={st.mean(vals):.1f}bp '
              f'p25={sorted(vals)[len(vals)//4]:.1f} p75={sorted(vals)[3*len(vals)//4]:.1f} max={max(vals):.1f}')
        with open(os.path.join(_ROOT, 'research', f'rh_snap_summary_{lab}.json'), 'w') as f:
            json.dump(res[lab], f, indent=1)


if __name__ == '__main__':
    main()
