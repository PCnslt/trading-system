#!/usr/bin/env python3
"""Effective cost for OUR order size from RH L2 books, per session snapshot.

For each snapshot label we walk the recorded L2 book to fill a target notional
(default $250 — the real per-position size on a ~$700 account) and report:
  quoted_spread_bp   (ask-bid)/mid
  eff_half_bp_buy    VWAP(ask side, $250) vs mid   <- what a market-taking buy pays
  eff_half_bp_sell   mid vs VWAP(bid side, $250)
  roundtrip_bp       eff_half_bp_buy + eff_half_bp_sell
  tick_floor_bp      1 cent / mid  (hard minimum spread on a penny grid)
  book_depth_usd     total $ resting on the 5 best levels each side

Usage: ./venv/bin/python research/rh_book_cost.py <label> [<label2> ...]
"""
import json, os, statistics as st, sys

_ROOT = '/home/ubuntu/trading-system'
SNAP = os.path.join(_ROOT, 'research', 'rh_quote_snaps')
TARGET_USD = float(os.getenv('TARGET_USD', '250'))


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def walk(levels, target_usd, side):
    """VWAP to fill target_usd walking best-first. Returns (vwap, filled_usd, levels_used)."""
    got_usd = 0.0
    got_sh = 0.0
    used = 0
    for lv in levels or []:
        p = _f(lv.get('price'))
        q = lv.get('quantity') or 0
        if not p or p <= 0 or q <= 0:
            continue
        used += 1
        need_sh = (target_usd - got_usd) / p
        take = min(q, need_sh)
        got_sh += take
        got_usd += take * p
        if got_usd >= target_usd - 1e-9:
            break
    if got_sh <= 0:
        return None, 0.0, 0
    return got_usd / got_sh, got_usd, used


def analyse(label):
    rows = [json.loads(l) for l in open(os.path.join(SNAP, f'{label}.jsonl'))]
    out = {}
    for r in rows:
        if not r.get('bids') or not r.get('asks'):
            continue
        b, a = _f(r.get('bid')), _f(r.get('ask'))
        if not b or not a or a < b or b <= 0:
            continue
        mid = (a + b) / 2
        vb, ub, nb = walk(r['asks'], TARGET_USD, 'buy')     # buying lifts asks
        vs, us, ns = walk(r['bids'], TARGET_USD, 'sell')    # selling hits bids
        bid_depth = sum((_f(x.get('price')) or 0) * (x.get('quantity') or 0) for x in r['bids'][:5])
        ask_depth = sum((_f(x.get('price')) or 0) * (x.get('quantity') or 0) for x in r['asks'][:5])
        d = {'symbol': r['symbol'], 'mid': round(mid, 4),
             'quoted_spread_bp': round((a - b) / mid * 1e4, 1),
             'tick_floor_bp': round(0.01 / mid * 1e4, 1),
             'eff_half_bp_buy': round((vb - mid) / mid * 1e4, 1) if vb else None,
             'eff_half_bp_sell': round((mid - vs) / mid * 1e4, 1) if vs else None,
             'filled_usd_buy': round(ub), 'filled_usd_sell': round(us),
             'levels_used_buy': nb, 'levels_used_sell': ns,
             'bid_depth_5lvl_usd': round(bid_depth), 'ask_depth_5lvl_usd': round(ask_depth),
             'target_usd': TARGET_USD}
        if d['eff_half_bp_buy'] is not None and d['eff_half_bp_sell'] is not None:
            d['roundtrip_bp'] = round(d['eff_half_bp_buy'] + d['eff_half_bp_sell'], 1)
        out[r['symbol']] = d          # first snapshot per symbol has the book
    return out


def main():
    labels = sys.argv[1:] or ['premarket_0917']
    allres = {}
    for lab in labels:
        res = analyse(lab)
        allres[lab] = res
        print(f'\n===== {lab}  (target ${TARGET_USD:.0f} per side) =====')
        print(f"{'sym':7}{'mid':>8}{'quoted':>9}{'tickflr':>9}{'effB':>8}{'effS':>8}{'RT_bp':>8}"
              f"{'fillB$':>8}{'fillS$':>8}{'dep_bid$':>10}{'dep_ask$':>10}")
        for s, d in sorted(res.items()):
            print(f"{s:7}{d['mid']:>8.2f}{d['quoted_spread_bp']:>9.1f}{d['tick_floor_bp']:>9.1f}"
                  f"{(d['eff_half_bp_buy'] if d['eff_half_bp_buy'] is not None else float('nan')):>8.1f}"
                  f"{(d['eff_half_bp_sell'] if d['eff_half_bp_sell'] is not None else float('nan')):>8.1f}"
                  f"{(d.get('roundtrip_bp') or float('nan')):>8.1f}"
                  f"{d['filled_usd_buy']:>8}{d['filled_usd_sell']:>8}"
                  f"{d['bid_depth_5lvl_usd']:>10}{d['ask_depth_5lvl_usd']:>10}")
        rt = [d['roundtrip_bp'] for d in res.values() if d.get('roundtrip_bp') is not None]
        qs = [d['quoted_spread_bp'] for d in res.values()]
        short = [s for s, d in res.items() if d['filled_usd_buy'] < TARGET_USD * 0.99
                 or d['filled_usd_sell'] < TARGET_USD * 0.99]
        print(f"  n={len(rt)}  quoted median={st.median(qs):.1f}bp  "
              f"roundtrip median={st.median(rt):.1f}bp mean={st.mean(rt):.1f}bp "
              f"p75={sorted(rt)[3*len(rt)//4]:.1f} max={max(rt):.1f}")
        if short:
            print(f"  book could not fill ${TARGET_USD:.0f} within recorded levels: {sorted(short)}")
    with open(os.path.join(_ROOT, 'research', 'rh_book_cost.json'), 'w') as f:
        json.dump(allres, f, indent=1)


if __name__ == '__main__':
    main()
