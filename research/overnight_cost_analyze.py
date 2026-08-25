#!/usr/bin/env python3
"""Session-cost analysis of Robinhood 24_7 5-min bars — CORRECTED buckets.

Buckets (ET wall clock):
  overnight  20:00-04:00   (RH 24_7 pads these bars but reports 0 volume -> see caveat)
  pre        04:00-09:30
  reg        09:30-16:00
  auction    16:00-16:05   <-- the closing cross prints here; 72-100% of naive
                               "post" volume. EXCLUDED from the extended session.
  post       16:05-20:00   <-- the real evening session
Measures per symbol/session from REAL bars only (interpolated=false & volume>0):
  vol_share_pct, trade_bar_pct, med_bar_vol, notional_usd
  cs_bp   Corwin-Schultz on consecutive SESSION high/low pairs (day t-1 vs day t)
  roll_bp Roll (1984) serial-covariance effective spread from 5-min returns
  hl_bp   mean per-bar high-low range (traded bars) — loose upper bound
Evening-fill test: limit at the 16:00 regular close, placed 16:05, in the
16:05-20:00 session — time to touch, fill rate, required concession, and the
adverse-selection drift after a fill.

Writes research/overnight_cost_results.json
"""
from __future__ import annotations
import json, math, os, statistics as st, datetime as dt
from zoneinfo import ZoneInfo
from collections import defaultdict

_ROOT = '/home/ubuntu/trading-system'
BARS = os.path.join(_ROOT, 'research', 'rh_247_bars')
NY = ZoneInfo('America/New_York')
SESSIONS = ['overnight', 'pre', 'reg', 'auction', 'post']
K = 3 - 2 * math.sqrt(2)


def bucket(t: dt.datetime) -> str:
    m = t.hour * 60 + t.minute
    if 240 <= m < 570:
        return 'pre'
    if 570 <= m < 960:
        return 'reg'
    if 960 <= m < 965:
        return 'auction'
    if 965 <= m < 1200:
        return 'post'
    return 'overnight'


def cs_pair(h1, l1, h2, l2):
    if min(h1, l1, h2, l2) <= 0:
        return None
    b = math.log(h1 / l1) ** 2 + math.log(h2 / l2) ** 2
    g = math.log(max(h1, h2) / min(l1, l2)) ** 2
    try:
        a = (math.sqrt(2 * b) - math.sqrt(b)) / K - math.sqrt(g / K)
    except ValueError:
        return None
    return max(0.0, 2 * (math.exp(a) - 1) / (1 + math.exp(a)))


def roll_bp(closes):
    """Roll (1984): S = 2*sqrt(-cov(dp_t, dp_t-1)); undefined when cov >= 0."""
    if len(closes) < 12:
        return None
    dp = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    if len(dp) < 10:
        return None
    x, y = dp[1:], dp[:-1]
    mx, my = st.mean(x), st.mean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)
    if cov >= 0:
        return None
    return 2 * math.sqrt(-cov) / st.mean(closes) * 1e4


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


def analyse(sym):
    bars = load(sym)
    real = [b for b in bars if not b['interp'] and b['v'] > 0]
    tot_v = sum(b['v'] for b in real)
    res = {'symbol': sym,
           'source': 'robinhood get_equity_historicals bounds=24_7 interval=5minute',
           'window_start': bars[0]['t'].isoformat(), 'window_end': bars[-1]['t'].isoformat(),
           'total_volume': tot_v, 'last_price': real[-1]['c'] if real else None,
           'sessions': {}}
    byday = defaultdict(lambda: defaultdict(list))
    for b in bars:
        byday[b['t'].date()][b['bkt']].append(b)
    for s in SESSIONS:
        allb = [b for b in bars if b['bkt'] == s]
        rb = [b for b in allb if not b['interp'] and b['v'] > 0]
        v = sum(b['v'] for b in rb)
        # session-level CS: consecutive DAYS' session high/low (the daily-analogue use)
        sess_hl = []
        for d in sorted(byday):
            r = [b for b in byday[d][s] if not b['interp'] and b['v'] > 0]
            if r:
                sess_hl.append((max(b['h'] for b in r), min(b['l'] for b in r)))
        cs = [x for x in (cs_pair(*sess_hl[i - 1], *sess_hl[i]) for i in range(1, len(sess_hl)))
              if x is not None]
        hl = [(b['h'] - b['l']) / ((b['h'] + b['l']) / 2) * 1e4 for b in rb if b['l'] > 0]
        res['sessions'][s] = {
            'bars_total': len(allb), 'bars_traded': len(rb),
            'trade_bar_pct': round(100 * len(rb) / len(allb), 1) if allb else None,
            'volume': v, 'vol_share_pct': round(100 * v / tot_v, 3) if tot_v else None,
            'notional_usd': round(sum(b['v'] * b['c'] for b in rb)),
            'med_bar_vol': int(st.median([b['v'] for b in rb])) if rb else 0,
            'cs_bp': round(st.mean(cs) * 1e4, 1) if cs else None, 'cs_n': len(cs),
            'roll_bp': (lambda x: round(x, 1) if x else None)(roll_bp([b['c'] for b in rb])),
            'hl_bp_mean': round(st.mean(hl), 1) if hl else None,
        }
    # ---------- evening fill test ----------
    fills = []
    for d in sorted(byday):
        reg = [b for b in byday[d]['reg'] if not b['interp'] and b['v'] > 0]
        post = [b for b in byday[d]['post'] if not b['interp'] and b['v'] > 0]
        if not reg:
            continue
        close = reg[-1]['c']
        pv = sum(b['v'] for b in post)
        row = {'date': str(d), 'close': close, 'post_traded_bars': len(post), 'post_vol': pv}
        if not post:
            row.update({'no_evening_trade': True, 'buy_filled': False, 'sell_filled': False})
            fills.append(row)
            continue
        lo, hi = min(b['l'] for b in post), max(b['h'] for b in post)
        bfill = next((b for b in post if b['l'] <= close), None)
        sfill = next((b for b in post if b['h'] >= close), None)
        row.update({
            'post_low': lo, 'post_high': hi, 'post_close': post[-1]['c'],
            'buy_filled': bfill is not None, 'sell_filled': sfill is not None,
            'buy_mins_to_fill': int((bfill['t'] - byday[d]['post'][0]['t']).total_seconds() / 60) if bfill else None,
            'sell_mins_to_fill': int((sfill['t'] - byday[d]['post'][0]['t']).total_seconds() / 60) if sfill else None,
            'buy_concession_bp': round(max(0.0, (lo - close) / close * 1e4), 1),
            'sell_concession_bp': round(max(0.0, (close - hi) / close * 1e4), 1),
            # adverse selection: where did the evening end vs my fill at `close`?
            'buy_adverse_bp': round((post[-1]['c'] - close) / close * 1e4, 1) if bfill else None,
            'sell_adverse_bp': round((close - post[-1]['c']) / close * 1e4, 1) if sfill else None,
        })
        fills.append(row)
    res['evening_fill'] = fills
    n = len(fills)
    if n:
        withtrade = [f for f in fills if not f.get('no_evening_trade')]
        bf = [f for f in fills if f['buy_filled']]
        res['evening_fill_summary'] = {
            'sessions': n, 'sessions_with_any_evening_trade': len(withtrade),
            'buy_fill_pct': round(100 * len(bf) / n, 1),
            'sell_fill_pct': round(100 * sum(f['sell_filled'] for f in fills) / n, 1),
            'buy_fill_within_30min_pct': round(100 * sum(
                1 for f in fills if f.get('buy_mins_to_fill') is not None
                and f['buy_mins_to_fill'] <= 30) / n, 1),
            'median_mins_to_buy_fill': (st.median([f['buy_mins_to_fill'] for f in bf])
                                        if bf else None),
            'buy_concession_bp_p80': (round(sorted(f['buy_concession_bp'] for f in withtrade)[
                int(0.8 * (len(withtrade) - 1))], 1) if withtrade else None),
            'median_buy_adverse_bp': (round(st.median([f['buy_adverse_bp'] for f in bf]), 1)
                                      if bf else None),
            'median_post_vol': int(st.median([f['post_vol'] for f in fills])),
            'median_post_traded_bars': int(st.median([f['post_traded_bars'] for f in fills])),
        }
    return res


def main():
    syms = sorted(f[:-5] for f in os.listdir(BARS) if f.endswith('.json'))
    out = [analyse(s) for s in syms]
    with open(os.path.join(_ROOT, 'research', 'overnight_cost_results.json'), 'w') as f:
        json.dump(out, f, indent=1)
    nan = float('nan')
    print("VOLUME SHARE (% of 15d total, closing auction split out) + EVENING ACTIVITY")
    print(f"{'sym':6}{'px':>7}{'ON%':>6}{'pre%':>7}{'reg%':>7}{'auct%':>7}{'post%':>7}"
          f"{'post$/day':>11}{'postbars':>9}{'CSreg':>7}{'CSpost':>7}{'CSpre':>7}")
    for r in out:
        s = r['sessions']
        g = lambda k, f: (s[k][f] if s[k].get(f) is not None else nan)
        days = 11  # ~11 trading sessions in the 15-calendar-day window
        print(f"{r['symbol']:6}{(r['last_price'] or 0):>7.2f}{g('overnight','vol_share_pct'):>6.1f}"
              f"{g('pre','vol_share_pct'):>7.2f}{g('reg','vol_share_pct'):>7.2f}"
              f"{g('auction','vol_share_pct'):>7.2f}{g('post','vol_share_pct'):>7.2f}"
              f"{s['post']['notional_usd']/days:>11,.0f}{g('post','bars_traded'):>9.0f}"
              f"{g('reg','cs_bp'):>7.0f}{g('post','cs_bp'):>7.0f}{g('pre','cs_bp'):>7.0f}")
    print()
    for s in SESSIONS:
        v = [r['sessions'][s]['vol_share_pct'] for r in out if r['sessions'][s]['vol_share_pct'] is not None]
        c = [r['sessions'][s]['cs_bp'] for r in out if r['sessions'][s]['cs_bp'] is not None]
        t = [r['sessions'][s]['trade_bar_pct'] for r in out if r['sessions'][s]['trade_bar_pct'] is not None]
        print(f'{s:10} vol_share median={st.median(v):6.2f}%  CS median='
              f'{(st.median(c) if c else nan):6.1f}bp (n={len(c)})  traded-bar median={st.median(t):5.1f}%')
    ef = [r['evening_fill_summary'] for r in out if r.get('evening_fill_summary')]
    print(f"\nEVENING (16:05-20:00) LIMIT-AT-CLOSE FILL TEST, n={len(ef)} symbols "
          f"x ~{ef[0]['sessions']} sessions:")
    for k in ['buy_fill_pct', 'buy_fill_within_30min_pct', 'median_mins_to_buy_fill',
              'buy_concession_bp_p80', 'median_buy_adverse_bp', 'median_post_vol',
              'median_post_traded_bars', 'sessions_with_any_evening_trade']:
        vals = [e[k] for e in ef if e.get(k) is not None]
        print(f'  {k:32} median across symbols = {st.median(vals):.1f}' if vals else f'  {k}: n/a')


if __name__ == '__main__':
    main()
