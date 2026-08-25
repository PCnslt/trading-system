#!/usr/bin/env python3
"""Paired extended-vs-RTH execution-cost comparison + round-trip cost floor.

Pools ALL clean single-session snapshots (a snapshot file must contain rows from
exactly one ET session — mixed files are quarantined as .MIXED_DO_NOT_USE).
Both legs measured identically: RH L2 price book walked to fill $250/side,
effective half-spread vs the prevailing mid, summed to a round trip.
Adds the statutory sell-side fees an RH equity round trip actually pays.
"""
import json, os, statistics as st, sys
sys.path.insert(0, '/home/ubuntu/trading-system')
from research.rh_book_cost import analyse

_ROOT = '/home/ubuntu/trading-system'
EXT_LABELS = ['premarket_0917', 'premarket_0923', 'premarket_0925', 'premarket_0927']
RTH_LABELS = ['rth_0931', 'rth_0935', 'rth_0942']
SEC_FEE_RATE = 0.0000278          # SEC Section 31, sells only ($27.80 per $1M)
TAF_PER_SHARE = 0.000166          # FINRA TAF, sells only, cap $8.30
STALE_BP = 300                    # above this a quote is stale/crossed, not a spread


def pooled(labels):
    """Median round-trip per symbol across snapshots; also keeps mid + tick floor."""
    rt, meta = {}, {}
    for lab in labels:
        for s, d in analyse(lab).items():
            if d.get('roundtrip_bp') is not None:
                rt.setdefault(s, []).append(d['roundtrip_bp'])
                meta[s] = {'mid': d['mid'], 'tick_floor_bp': d['tick_floor_bp']}
    return {s: st.median(v) for s, v in rt.items()}, {s: len(v) for s, v in rt.items()}, meta


def main():
    ext, ext_n, meta = pooled(EXT_LABELS)
    rth, rth_n, _ = pooled(RTH_LABELS)
    syms = sorted(set(ext) & set(rth))
    print(f"PAIRED $250/side EFFECTIVE ROUND-TRIP COST — pooled clean snapshots")
    print(f"  extended ({len(EXT_LABELS)} snaps): {', '.join(EXT_LABELS)}")
    print(f"  regular  ({len(RTH_LABELS)} snaps): {', '.join(RTH_LABELS)}")
    print(f"\n{'sym':7}{'mid':>8}{'RTH_bp':>9}{'EXT_bp':>9}{'ratio':>8}{'tickflr':>9}{'snaps':>7}")
    rows = []
    for s in syms:
        a, b = rth[s], ext[s]
        if a <= 0:
            continue
        rows.append((s, meta[s]['mid'], a, b, b / a, meta[s]['tick_floor_bp'],
                     f'{rth_n[s]}/{ext_n[s]}'))
    for s, mid, a, b, rt, tf, n in rows:
        print(f"{s:7}{mid:>8.2f}{a:>9.1f}{b:>9.1f}{rt:>8.2f}{tf:>9.1f}{n:>7}")
    rv = [x[2] for x in rows]
    pv = [x[3] for x in rows]
    rat = [x[4] for x in rows]
    tf = [x[5] for x in rows]
    stale = [x[0] for x in rows if x[3] >= STALE_BP]
    trim = [x[3] for x in rows if x[3] < STALE_BP]
    print(f"\nn={len(rows)} names")
    print(f"  REGULAR  round-trip median={st.median(rv):6.1f}bp mean={st.mean(rv):6.1f} p75={sorted(rv)[3*len(rv)//4]:6.1f} max={max(rv):6.1f}")
    print(f"  EXTENDED round-trip median={st.median(pv):6.1f}bp mean={st.mean(pv):6.1f} p75={sorted(pv)[3*len(pv)//4]:6.1f} max={max(pv):6.1f}")
    print(f"    excl. stale >{STALE_BP}bp {stale}: median={st.median(trim):.1f}bp mean={st.mean(trim):.1f}")
    print(f"  paired EXT/RTH ratio median={st.median(rat):6.2f}x mean={st.mean(rat):6.2f}")
    print(f"  penny-tick floor    median={st.median(tf):6.1f}bp (1 cent / price = hard minimum HALF spread)")

    px = st.median([x[1] for x in rows])
    sh = 250 / px
    sec_bp = SEC_FEE_RATE * 1e4
    taf_bp = (TAF_PER_SHARE * sh) / 250 * 1e4
    fees = sec_bp + taf_bp
    print(f"\nSTATUTORY FEES on a $250 round trip (sell leg only, RH commission $0):")
    print(f"  SEC Section 31 {sec_bp:.2f}bp + FINRA TAF {taf_bp:.2f}bp = {fees:.2f}bp")
    ext_med = st.median(pv)
    print(f"\nMINIMUM ROUND-TRIP COST TO OVERCOME:")
    print(f"  EXTENDED session: {ext_med:.1f}bp spread + {fees:.2f}bp fees = {ext_med+fees:.1f}bp")
    print(f"  regular hours:    {st.median(rv):.1f}bp spread + {fees:.2f}bp fees = {st.median(rv)+fees:.1f}bp")
    out = {'extended_labels': EXT_LABELS, 'rth_labels': RTH_LABELS, 'n_names': len(rows),
           'method': 'RH get_equity_price_book L2 walked to $250/side; eff half-spread vs mid, both legs',
           'rth_roundtrip_bp_median': round(st.median(rv), 1),
           'extended_roundtrip_bp_median': round(ext_med, 1),
           'extended_roundtrip_bp_median_excl_stale': round(st.median(trim), 1),
           'extended_over_rth_ratio_median': round(st.median(rat), 2),
           'stale_excluded': stale, 'statutory_fees_bp': round(fees, 2),
           'min_roundtrip_bp_extended': round(ext_med + fees, 1),
           'min_roundtrip_bp_rth': round(st.median(rv) + fees, 1),
           'caveat': ('extended snapshots were taken 09:12-09:28 ET, the PEAK-liquidity '
                      'window of the extended session, so this is a LOWER BOUND for '
                      '16:05-20:00 and 20:00-04:00; the latter remains unmeasured'),
           'per_symbol': [{'symbol': s, 'mid': m, 'rth_bp': a, 'ext_bp': b,
                           'ratio': round(x, 2), 'tick_floor_bp': t, 'snaps_rth_ext': n}
                          for s, m, a, b, x, t, n in rows]}
    with open(os.path.join(_ROOT, 'research', 'overnight_cost_floor.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
