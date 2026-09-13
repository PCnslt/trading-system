#!/usr/bin/env python3
"""Session-level spread estimators + evening-fill timing from RH 24_7 5-min bars.

Improvements over overnight_cost_analyze.py:

1. Corwin-Schultz applied the way the paper intends — to consecutive *sessions*
   (session high/low per day, paired day-over-day within the same session type),
   not to 5-min bars. CS on 5-min bars in a thin session collapses toward 0
   because most thin bars have high==low, which biases the estimate DOWN; that
   artifact is why the naive run showed post-session spreads < RTH spreads.

2. Roll (1984) serial-covariance effective-spread estimator on 5-min traded-bar
   returns within each session:  S = 2*sqrt(-cov(dp_t, dp_t-1)), undefined when
   the autocovariance is positive (trending), which is reported honestly.

3. Evening-fill timing: place a notional BUY limit at the 16:00 regular close and
   measure the FIRST post-session 5-min bar whose low <= limit (time-to-touch),
   plus fill rate within 30/60 min and by 20:00, and the concession needed when
   no touch happens.

Writes research/overnight_session_estimators.json
"""
from __future__ import annotations
import json, math, os, statistics as st, datetime as dt
from zoneinfo import ZoneInfo
from collections import defaultdict

_ROOT = '/home/ubuntu/trading-system'
BARS = os.path.join(_ROOT, 'research', 'rh_247_bars')
NY = ZoneInfo('America/New_York')
K = 3 - 2 * math.sqrt(2)


def bucket(t):
    m = t.hour * 60 + t.minute
    if 4 * 60 <= m < 9 * 60 + 30:
        return 'pre'
    if 9 * 60 + 30 <= m < 16 * 60:
        return 'reg'
    if 16 * 60 <= m < 20 * 60:
        return 'post'
    return 'overnight'


def load(sym):
    d = json.load(open(os.path.join(BARS, f'{sym}.json')))
    out = []
    for b in d['bars']:
        t = dt.datetime.fromisoformat(b['begins_at'].replace('Z', '+00:00')).astimezone(NY)
        out.append({'t': t, 'h': float(b['high_price']), 'l': float(b['low_price']),
                    'c': float(b['close_price']), 'v': int(b.get('volume') or 0),
                    'interp': bool(b.get('interpolated')), 'bkt': bucket(t)})
    out.sort(key=lambda x: x['t'])
    return out


def cs_pair(h1, l1, h2, l2):
    if min(h1, l1, h2, l2) <= 0 or h1 < l1 or h2 < l2:
        return None
    b = math.log(h1 / l1) ** 2 + math.log(h2 / l2) ** 2
    g = math.log(max(h1, h2) / min(l1, l2)) ** 2
    if b <= 0:
        return None
    try:
        a = (math.sqrt(2 * b) - math.sqrt(b)) / K - math.sqrt(g / K)
    except ValueError:
        return None
    return 2 * (math.exp(a) - 1) / (1 + math.exp(a))


def roll_bp(closes):
    """Roll (1984) effective spread in bp from a return series; None if cov>=0."""
    if len(closes) < 30:
        return None, None
    dp = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
          if closes[i] > 0 and closes[i - 1] > 0]
    if len(dp) < 30:
        return None, None
    m = st.mean(dp)
    cov = sum((dp[i] - m) * (dp[i - 1] - m) for i in range(1, len(dp))) / (len(dp) - 1)
    if cov >= 0:
        return None, round(cov, 12)
    return round(2 * math.sqrt(-cov) * 1e4, 1), round(cov, 12)


def analyse(sym):
    bars = load(sym)
    byday = defaultdict(lambda: defaultdict(list))
    for b in bars:
        byday[b['t'].date()][b['bkt']].append(b)
    res = {'symbol': sym, 'sessions': {}}
    for s in ['pre', 'reg', 'post', 'overnight']:
        # per-day session high/low from REAL bars only
        sess = []
        for d in sorted(byday):
            rb = [b for b in byday[d][s] if not b['interp'] and b['v'] > 0]
            if len(rb) < 2:
                continue
            sess.append({'date': d, 'h': max(b['h'] for b in rb), 'l': min(b['l'] for b in rb),
                         'c': rb[-1]['c'], 'v': sum(b['v'] for b in rb), 'n': len(rb)})
        ests, neg = [], 0
        for i in range(1, len(sess)):
            e = cs_pair(sess[i - 1]['h'], sess[i - 1]['l'], sess[i]['h'], sess[i]['l'])
            if e is None:
                continue
            if e < 0:
                neg += 1
            ests.append(max(0.0, e))
        closes = [b['c'] for b in bars if b['bkt'] == s and not b['interp'] and b['v'] > 0]
        r_bp, cov = roll_bp(closes)
        px = st.median([x['c'] for x in sess]) if sess else None
        res['sessions'][s] = {
            'n_days': len(sess),
            'cs_session_bp': round(st.mean(ests) * 1e4, 1) if ests else None,
            'cs_n_pairs': len(ests), 'cs_pct_negative_raw': round(100 * neg / len(ests), 0) if ests else None,
            'roll_bp': r_bp, 'roll_autocov': cov,
            'tick_floor_bp': round(0.01 / px * 1e4, 1) if px else None,
            'median_session_price': round(px, 2) if px else None,
        }
    # ---- evening fill timing ----
    trials = []
    for d in sorted(byday):
        reg = [b for b in byday[d]['reg'] if not b['interp'] and b['v'] > 0]
        post = [b for b in byday[d]['post'] if not b['interp'] and b['v'] > 0]
        if not reg or not post:
            continue
        limit = reg[-1]['c']            # BUY limit AT the regular-session close
        t0 = dt.datetime.combine(d, dt.time(16, 0), tzinfo=NY)
        touch_min = None
        for b in post:
            if b['l'] <= limit:
                touch_min = int((b['t'] - t0).total_seconds() // 60)
                break
        lo = min(b['l'] for b in post)
        trials.append({'date': str(d), 'limit': limit, 'touch_min': touch_min,
                       'post_low': lo, 'post_high': max(b['h'] for b in post),
                       'post_vol': sum(b['v'] for b in post), 'post_bars': len(post),
                       'concession_bp': None if touch_min is not None
                       else round((lo - limit) / limit * 1e4, 1)})
    res['evening_trials'] = trials
    if trials:
        tt = [t['touch_min'] for t in trials if t['touch_min'] is not None]
        conc = [t['concession_bp'] for t in trials if t['touch_min'] is None]
        res['evening_summary'] = {
            'n_sessions': len(trials),
            'touch_pct_any': round(100 * len(tt) / len(trials), 1),
            'touch_pct_30min': round(100 * sum(1 for x in tt if x <= 30) / len(trials), 1),
            'touch_pct_60min': round(100 * sum(1 for x in tt if x <= 60) / len(trials), 1),
            'touch_min_median': st.median(tt) if tt else None,
            'no_touch_concession_bp_median': round(st.median(conc), 1) if conc else None,
            'post_vol_median': int(st.median([t['post_vol'] for t in trials])),
            'post_traded_bars_median': int(st.median([t['post_bars'] for t in trials])),
        }
    return res


def main():
    syms = sorted(f[:-5] for f in os.listdir(BARS) if f.endswith('.json'))
    out = [analyse(s) for s in syms]
    with open(os.path.join(_ROOT, 'research', 'overnight_session_estimators.json'), 'w') as f:
        json.dump(out, f, indent=1)
    print(f"{'sym':7}{'px':>7} | {'CS reg':>7}{'CS pre':>7}{'CS post':>8} | "
          f"{'Roll reg':>9}{'Roll pre':>9}{'Roll post':>10} | {'tickflr':>8} | "
          f"{'touch%':>7}{'t30%':>6}{'tmed':>6}")
    for r in out:
        s = r['sessions']
        n = lambda k, f: s[k][f] if s[k].get(f) is not None else float('nan')
        e = r.get('evening_summary') or {}
        print(f"{r['symbol']:7}{n('reg','median_session_price'):>7.2f} | "
              f"{n('reg','cs_session_bp'):>7.0f}{n('pre','cs_session_bp'):>7.0f}{n('post','cs_session_bp'):>8.0f} | "
              f"{n('reg','roll_bp'):>9.0f}{n('pre','roll_bp'):>9.0f}{n('post','roll_bp'):>10.0f} | "
              f"{n('reg','tick_floor_bp'):>8.1f} | "
              f"{e.get('touch_pct_any', float('nan')):>7.1f}{e.get('touch_pct_30min', float('nan')):>6.1f}"
              f"{(e.get('touch_min_median') if e.get('touch_min_median') is not None else float('nan')):>6.0f}")
    print()
    for s in ['pre', 'reg', 'post', 'overnight']:
        cs = [r['sessions'][s]['cs_session_bp'] for r in out if r['sessions'][s]['cs_session_bp'] is not None]
        rl = [r['sessions'][s]['roll_bp'] for r in out if r['sessions'][s]['roll_bp'] is not None]
        tf = [r['sessions'][s]['tick_floor_bp'] for r in out if r['sessions'][s]['tick_floor_bp'] is not None]
        print(f'{s:10} CS median={st.median(cs) if cs else float("nan"):7.1f}bp (n={len(cs):2d})  '
              f'Roll median={st.median(rl) if rl else float("nan"):7.1f}bp (n={len(rl):2d})  '
              f'tick floor median={st.median(tf) if tf else float("nan"):5.1f}bp')
    ev = [r['evening_summary'] for r in out if r.get('evening_summary')]
    if ev:
        print(f'\nevening BUY-limit-at-close, {len(ev)} symbols x ~10 sessions:')
        for k in ['touch_pct_any', 'touch_pct_30min', 'touch_pct_60min', 'touch_min_median',
                  'no_touch_concession_bp_median', 'post_vol_median', 'post_traded_bars_median']:
            v = [e[k] for e in ev if e.get(k) is not None]
            print(f'  {k:32} median across symbols = {st.median(v):.1f}  (n={len(v)})')


if __name__ == '__main__':
    main()
