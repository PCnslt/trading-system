#!/usr/bin/env python3
"""Paired extended-vs-RTH execution-cost comparison + round-trip cost floor.

Both legs measured identically: RH L2 price book walked to fill $250/side,
effective half-spread vs the prevailing mid, summed to a round trip.
Adds the statutory sell-side fees an RH equity round trip actually pays.
"""
import json, os, statistics as st, sys
sys.path.insert(0, '/home/ubuntu/trading-system')
from research.rh_book_cost import analyse

_ROOT = '/home/ubuntu/trading-system'
EXT, RTH = 'premarket_0917', 'rth_0935'
SEC_FEE_RATE = 0.0000278          # SEC Section 31, sells only ($27.80 per $1M)
TAF_PER_SHARE = 0.000166          # FINRA TAF, sells only, cap $8.30


def main():
    e, r = analyse(EXT), analyse(RTH)
    syms = sorted(set(e) & set(r))
    print(f"PAIRED $250/side EFFECTIVE ROUND-TRIP COST, same names, same method")
    print(f"  extended = {EXT} (04:00-09:30 pre session)   regular = {RTH} (09:30-16:00)")
    print(f"\n{'sym':7}{'mid':>8}{'RTH_bp':>9}{'EXT_bp':>9}{'ratio':>8}{'tickflr':>9}")
    rows = []
    for s in syms:
        a, b = r[s].get('roundtrip_bp'), e[s].get('roundtrip_bp')
        if a is None or b is None or a <= 0:
            continue
        rows.append((s, r[s]['mid'], a, b, b / a, r[s]['tick_floor_bp']))
    for s, mid, a, b, rt, tf in rows:
        print(f"{s:7}{mid:>8.2f}{a:>9.1f}{b:>9.1f}{rt:>8.2f}{tf:>9.1f}")
    rth = [x[2] for x in rows]
    ext = [x[3] for x in rows]
    rat = [x[4] for x in rows]
    tf = [x[5] for x in rows]
    # robust: drop the single worst extended outlier (stale/crossed quote)
    worst = max(rows, key=lambda x: x[3])
    trim = [x for x in rows if x[0] != worst[0]]
    print(f"\nn={len(rows)}")
    print(f"  RTH round-trip      median={st.median(rth):6.1f}bp  mean={st.mean(rth):6.1f}  p75={sorted(rth)[3*len(rth)//4]:6.1f}  max={max(rth):6.1f}")
    print(f"  EXTENDED round-trip median={st.median(ext):6.1f}bp  mean={st.mean(ext):6.1f}  p75={sorted(ext)[3*len(ext)//4]:6.1f}  max={max(ext):6.1f}")
    print(f"    (excl. worst outlier {worst[0]} @ {worst[3]:.0f}bp: median={st.median([x[3] for x in trim]):.1f} mean={st.mean([x[3] for x in trim]):.1f})")
    print(f"  EXT/RTH ratio       median={st.median(rat):6.2f}x  mean={st.mean(rat):6.2f}")
    print(f"  penny-tick floor    median={st.median(tf):6.1f}bp  (1 cent / price — hard minimum HALF spread)")

    # statutory fees on a $250 round trip
    px = st.median([x[1] for x in rows])
    sh = 250 / px
    sec_bp = SEC_FEE_RATE * 1e4
    taf_bp = (TAF_PER_SHARE * sh) / 250 * 1e4
    print(f"\nSTATUTORY FEES on a $250 round trip (sell leg only, RH commission $0):")
    print(f"  SEC Section 31   {sec_bp:.2f}bp   FINRA TAF {taf_bp:.2f}bp   total {sec_bp+taf_bp:.2f}bp")

    ext_med = st.median(ext)
    floor = ext_med + sec_bp + taf_bp
    print(f"\nMINIMUM ROUND-TRIP COST TO OVERCOME (extended session, measured):")
    print(f"  effective spread {ext_med:.1f}bp + fees {sec_bp+taf_bp:.2f}bp = {floor:.1f}bp")
    print(f"  RTH equivalent:  {st.median(rth):.1f}bp + {sec_bp+taf_bp:.2f}bp = {st.median(rth)+sec_bp+taf_bp:.1f}bp")
    out = {'extended_label': EXT, 'rth_label': RTH, 'n': len(rows),
           'rth_roundtrip_bp_median': round(st.median(rth), 1),
           'extended_roundtrip_bp_median': round(ext_med, 1),
           'extended_over_rth_ratio_median': round(st.median(rat), 2),
           'statutory_fees_bp': round(sec_bp + taf_bp, 2),
           'min_roundtrip_bp_extended': round(floor, 1),
           'min_roundtrip_bp_rth': round(st.median(rth) + sec_bp + taf_bp, 1),
           'per_symbol': [{'symbol': s, 'mid': m, 'rth_bp': a, 'ext_bp': b,
                           'ratio': round(x, 2), 'tick_floor_bp': t}
                          for s, m, a, b, x, t in rows]}
    with open(os.path.join(_ROOT, 'research', 'overnight_cost_floor.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
