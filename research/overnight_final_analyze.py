#!/usr/bin/env python3
"""FINAL clean session-cost analysis (auction prints excluded).

Corrects the two artifacts found in the naive pass:
  * the 16:00-16:05 bar is the CLOSING AUCTION cross, not post-session trading
    (median 7.9% of a name's daily volume, up to 29.6%) -> excluded from 'post'
  * the 09:25-09:30 bar carries opening-auction imbalance -> excluded from 'pre'

Windows used:  pre 04:00-09:25 | reg 09:30-16:00 | post 16:05-20:00 | overnight 20:00-04:00

Evening fill test: BUY limit resting at the 16:00 CLOSING PRICE, evaluated over
the clean post window 16:05-20:00 only.

Writes research/overnight_final_results.json
"""
from __future__ import annotations
import json, os, statistics as st, datetime as dt
from zoneinfo import ZoneInfo
from collections import defaultdict

_ROOT = '/home/ubuntu/trading-system'
RH = os.path.join(_ROOT, 'research', 'rh_247_bars')
NY = ZoneInfo('America/New_York')


def bkt(t):
    m = t.hour * 60 + t.minute
    if 4 * 60 <= m < 9 * 60 + 25:
        return 'pre'
    if m in (9 * 60 + 25,):
        return 'open_auction_window'
    if 9 * 60 + 30 <= m < 16 * 60:
        return 'reg'
    if m == 16 * 60:
        return 'close_auction'
    if 16 * 60 < m < 20 * 60:
        return 'post'
    return 'overnight'


def load(sym):
    d = json.load(open(os.path.join(RH, f'{sym}.json')))
    out = []
    for b in d['bars']:
        t = dt.datetime.fromisoformat(b['begins_at'].replace('Z', '+00:00')).astimezone(NY)
        out.append({'t': t, 'h': float(b['high_price']), 'l': float(b['low_price']),
                    'o': float(b['open_price']), 'c': float(b['close_price']),
                    'v': int(b.get('volume') or 0),
                    'interp': bool(b.get('interpolated')), 'bkt': bkt(t)})
    out.sort(key=lambda x: x['t'])
    return out


def analyse(sym):
    bars = load(sym)
    real = [b for b in bars if not b['interp'] and b['v'] > 0]
    tot = sum(b['v'] for b in real)
    r = {'symbol': sym, 'sessions': {}}
    for s in ['overnight', 'pre', 'reg', 'post', 'close_auction']:
        allb = [b for b in bars if b['bkt'] == s]
        rb = [b for b in allb if not b['interp'] and b['v'] > 0]
        v = sum(b['v'] for b in rb)
        r['sessions'][s] = {
            'vol_share_pct': round(100 * v / tot, 3) if tot else None,
            'bars_total': len(allb), 'bars_traded': len(rb),
            'trade_bar_pct': round(100 * len(rb) / len(allb), 1) if allb else None,
            'total_volume': v,
            'med_bar_vol': int(st.median([b['v'] for b in rb])) if rb else 0,
        }
    # per-session-day volume in shares & dollars
    byday = defaultdict(lambda: defaultdict(list))
    for b in bars:
        byday[b['t'].date()][b['bkt']].append(b)
    px = st.median([b['c'] for b in real]) if real else None
    r['median_price'] = round(px, 2) if px else None
    r['tick_floor_bp'] = round(0.01 / px * 1e4, 1) if px else None
    for s in ['pre', 'post', 'reg']:
        dv = []
        for d in sorted(byday):
            rb = [b for b in byday[d][s] if not b['interp'] and b['v'] > 0]
            if rb:
                dv.append(sum(b['v'] for b in rb))
        r['sessions'][s]['median_daily_shares'] = int(st.median(dv)) if dv else 0
        r['sessions'][s]['median_daily_usd'] = int(st.median(dv) * px) if dv and px else 0
    # ---- evening fill test: BUY limit at the 16:00 closing price ----
    trials = []
    for d in sorted(byday):
        ca = [b for b in byday[d]['close_auction'] if not b['interp'] and b['v'] > 0]
        reg = [b for b in byday[d]['reg'] if not b['interp'] and b['v'] > 0]
        post = [b for b in byday[d]['post'] if not b['interp'] and b['v'] > 0]
        if not post or not (ca or reg):
            continue
        close = ca[-1]['c'] if ca else reg[-1]['c']
        t0 = dt.datetime.combine(d, dt.time(16, 5), tzinfo=NY)
        touch = next((int((b['t'] - t0).total_seconds() // 60) for b in post if b['l'] <= close), None)
        strict = next((int((b['t'] - t0).total_seconds() // 60) for b in post if b['l'] < close), None)
        lo = min(b['l'] for b in post)
        trials.append({'date': str(d), 'close': close, 'touch_min': touch,
                       'strict_through_min': strict, 'post_low': lo,
                       'post_high': max(b['h'] for b in post),
                       'post_vol': sum(b['v'] for b in post), 'post_bars': len(post),
                       'concession_bp': None if touch is not None else round((lo - close) / close * 1e4, 1),
                       'post_move_bp': round((post[-1]['c'] - close) / close * 1e4, 1)})
    r['evening_trials'] = trials
    if trials:
        tt = [t['touch_min'] for t in trials if t['touch_min'] is not None]
        sr = [t['strict_through_min'] for t in trials if t['strict_through_min'] is not None]
        conc = [t['concession_bp'] for t in trials if t['touch_min'] is None]
        mv = [abs(t['post_move_bp']) for t in trials]
        r['evening_summary'] = {
            'n_sessions': len(trials),
            'touch_pct': round(100 * len(tt) / len(trials), 1),
            'strict_through_pct': round(100 * len(sr) / len(trials), 1),
            'touch_pct_within_60min': round(100 * sum(1 for x in tt if x <= 60) / len(trials), 1),
            'touch_min_median': st.median(tt) if tt else None,
            'no_touch_concession_bp_median': round(st.median(conc), 1) if conc else None,
            'post_vol_median_shares': int(st.median([t['post_vol'] for t in trials])),
            'post_traded_bars_median': int(st.median([t['post_bars'] for t in trials])),
            'abs_evening_drift_bp_median': round(st.median(mv), 1),
        }
    return r


def main():
    syms = sorted(f[:-5] for f in os.listdir(RH) if f.endswith('.json'))
    out = [analyse(s) for s in syms]
    with open(os.path.join(_ROOT, 'research', 'overnight_final_results.json'), 'w') as f:
        json.dump(out, f, indent=1)
    print(f"{'sym':7}{'px':>7}{'tick':>6} | {'vol% pre':>9}{'vol% reg':>9}{'vol% post':>10}"
          f"{'vol% auct':>10}{'vol% ON':>8} | {'post$/day':>11}{'post bars%':>11} | "
          f"{'touch%':>7}{'thru%':>7}{'drift':>7}")
    for r in out:
        s = r['sessions']
        e = r.get('evening_summary') or {}
        g = lambda k, f: s[k][f] if s[k].get(f) is not None else float('nan')
        print(f"{r['symbol']:7}{(r['median_price'] or 0):>7.2f}{(r['tick_floor_bp'] or 0):>6.1f} | "
              f"{g('pre','vol_share_pct'):>9.2f}{g('reg','vol_share_pct'):>9.2f}"
              f"{g('post','vol_share_pct'):>10.2f}{g('close_auction','vol_share_pct'):>10.2f}"
              f"{g('overnight','vol_share_pct'):>8.2f} | "
              f"{g('post','median_daily_usd'):>11,.0f}{g('post','trade_bar_pct'):>11.1f} | "
              f"{e.get('touch_pct', float('nan')):>7.1f}{e.get('strict_through_pct', float('nan')):>7.1f}"
              f"{e.get('abs_evening_drift_bp_median', float('nan')):>7.0f}")
    print()
    for k in ['overnight', 'pre', 'reg', 'post', 'close_auction']:
        v = [r['sessions'][k]['vol_share_pct'] for r in out if r['sessions'][k]['vol_share_pct'] is not None]
        t = [r['sessions'][k]['trade_bar_pct'] for r in out if r['sessions'][k]['trade_bar_pct'] is not None]
        print(f'{k:14} vol share median={st.median(v):6.2f}% mean={st.mean(v):6.2f}%   '
              f'traded-bar median={st.median(t):5.1f}%')
    ext = [(r['sessions']['pre']['vol_share_pct'] or 0) + (r['sessions']['post']['vol_share_pct'] or 0) for r in out]
    print(f'\nTRADEABLE extended share (pre+post, auctions excluded): median={st.median(ext):.2f}% '
          f'mean={st.mean(ext):.2f}% max={max(ext):.2f}%')
    pu = [r['sessions']['post']['median_daily_usd'] for r in out]
    print(f'post-session (16:05-20:00) $ traded per day: median=${st.median(pu):,.0f} min=${min(pu):,.0f} max=${max(pu):,.0f}')
    ev = [r['evening_summary'] for r in out if r.get('evening_summary')]
    print(f'\nevening BUY limit AT the 16:00 close, {len(ev)} symbols:')
    for k in ['touch_pct', 'strict_through_pct', 'touch_pct_within_60min', 'touch_min_median',
              'abs_evening_drift_bp_median', 'post_traded_bars_median']:
        v = [e[k] for e in ev if e.get(k) is not None]
        print(f'  {k:32} median across symbols={st.median(v):8.1f}  (n={len(v)})')


if __name__ == '__main__':
    main()
