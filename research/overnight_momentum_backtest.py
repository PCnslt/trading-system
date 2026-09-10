#!/usr/bin/env python3
"""Cross-sectional OVERNIGHT-return momentum ('Night Trading' OBG) — queue strat-20260909-1.

Lachance (2023, Review of Financial Economics) 'Night Trading: Lower Risk but Higher
Returns?': an overnight-bias (OBG) portfolio earns +15.7-21.2%/yr NET 1995-2014.
Lou-Polk-Skouras (2019, JFE) 'The Market Risk Premium for Unsecured Consumer Credit
Risk'... no — 'A Tug of War: Overnight versus Intraday Expected Returns': overnight
momentum WML +3.47%/mo (t=16.83). Aboody et al (2018, JFQA): weekly overnight
persistence. Salotra et al (2026, Risks): sector-ETF overnight momentum.

Claim under test: the OVERNIGHT (close->open) return is PERSISTENT cross-sectionally —
names that earned high overnight returns over the trailing window keep earning them.
Lachance's OBG = slope of each stock's overnight return on its TOTAL return over the
prior year (a 'night-share' beta).

Tradeable lane (LONG-only, both legs RTH):
  signal computed at close_t, ENTER at close_t, EXIT at open_{t+1} (overnight-only hold).
  Rank the sub-$50 universe each rebalance date; LONG the top decile / top quintile.
  Rebalance weekly (5d) and monthly (21d).

Signals:
  on5  = sum of overnight returns, trailing 5d   (weekly overnight persistence)
  on21 = sum of overnight returns, trailing 21d  (monthly overnight momentum)
  obg  = rolling 252d beta of on_ret on ret1     (Lachance overnight-bias)

Honest fills: multiplicative 5 bps/side primary, 10 bps/side 2x stress.
net = (1+r)*(1-bps)/(1+bps) - 1.  IS/OOS split at 2022-01-01.
Per-trade t AND day-clustered t (cross-sectional ranks repeat on the same market day).
"""
from __future__ import annotations

import io, os, sys, json
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'research'))

import numpy as np
import pandas as pd
import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, '.env'))

BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')
PRICE_LO, PRICE_HI = 2.0, 50.0
DOLLAR_VOL_MIN = 5e6
OOS_FROM = '2022-01-01'
REBAL = {'weekly': 5, 'monthly': 21}
SIGNALS = {'on5': '5d overnight sum', 'on21': '21d overnight sum', 'obg': '252d OBG beta'}
COSTS = (0.0005, 0.0010)


def load(sym, s3):
    try:
        o = s3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{sym}.parquet')
        df = pd.read_parquet(io.BytesIO(o['Body'].read()))
        if len(df) < 300:
            return None
        df.index = pd.to_datetime(df['date'].astype(str))
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()
        df = df[df['close'] > 0]
        pc = df['close'].shift(1)
        df['on_ret'] = df['open'] / pc - 1.0                  # overnight close->open @t
        df['ret1'] = df['close'] / pc - 1.0                   # close-to-close
        df['next_on_ret'] = df['open'].shift(-1) / df['close'] - 1.0  # close_t -> open_{t+1}
        df['dollar_vol'] = (df['close'] * df['volume']).rolling(20).mean()
        df['on5'] = df['on_ret'].rolling(5).sum()
        df['on21'] = df['on_ret'].rolling(21).sum()
        rc = df['on_ret'].rolling(252).cov(df['ret1'])
        rv = df['ret1'].rolling(252).var()
        df['obg'] = rc / rv
        return df
    except Exception:
        return None


def stats(rets):
    r = np.asarray([x for x in rets if x == x and np.isfinite(x)], dtype=float)
    if len(r) == 0:
        return None
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    pf = w / l if l > 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 and len(r) > 1 else 0.0
    return {'n': int(len(r)), 'pf': round(pf, 3), 'win': round(float((r > 0).mean()), 3),
            'avg_bp': round(float(r.mean() * 1e4), 1), 't': round(float(t), 2)}


def day_t(rets, dates):
    s = pd.Series(rets, index=pd.to_datetime(dates))
    g = s.groupby(s.index).mean()
    g = g[g.notna()]
    if len(g) < 5 or g.std(ddof=1) == 0:
        return 0.0
    return round(float(g.mean() / (g.std(ddof=1) / np.sqrt(len(g)))), 2)


def cell(rets, dates):
    if not rets:
        return None
    isr = [r for r, d in zip(rets, dates) if pd.Timestamp(d) < pd.Timestamp(OOS_FROM)]
    oor = [r for r, d in zip(rets, dates) if pd.Timestamp(d) >= pd.Timestamp(OOS_FROM)]
    isd = [d for d in dates if pd.Timestamp(d) < pd.Timestamp(OOS_FROM)]
    ood = [d for d in dates if pd.Timestamp(d) >= pd.Timestamp(OOS_FROM)]
    out = {'all': stats(rets), 'is': stats(isr), 'oos': stats(oor)}
    if out['all']:
        out['all']['t_day'] = day_t(rets, dates)
    if out['is']:
        out['is']['t_day'] = day_t(isr, isd)
    if out['oos']:
        out['oos']['t_day'] = day_t(oor, ood)
    return out


def fmt(s):
    if not s or s['n'] == 0:
        return '        n/a'
    return (f"n={s['n']:>6} PF={s['pf']:>6.3f} win={s['win']*100:>5.1f}% "
            f"avg={s['avg_bp']:>7.1f}bp t={s['t']:>5.2f} tday={s.get('t_day', 0):>5.2f}")


def spread_t(top, bot, dates):
    """Day-clustered t of the cross-sectional top-minus-bottom overnight-return spread."""
    t = pd.Series(np.asarray(top) - np.asarray(bot), index=pd.to_datetime(dates))
    g = t.groupby(t.index).mean()
    g = g[g.notna()]
    if len(g) < 5 or g.std(ddof=1) == 0:
        return 0.0
    return round(float(g.mean() / (g.std(ddof=1) / np.sqrt(len(g)))), 2)


def main():
    syms = list(dict.fromkeys(json.load(
        open(os.path.join(_ROOT, 'research', 'smallcap_universe_full.json')))['symbols']))
    s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    print(f'loading {len(syms)} symbols from S3…', flush=True)
    with ThreadPoolExecutor(max_workers=24) as ex:
        data = {s: d for s, d in zip(syms, ex.map(lambda x: load(x, s3), syms)) if d is not None}
    print(f'  usable {len(data)}   '
          f'{min(d.index[0] for d in data.values()).date()} .. '
          f'{max(d.index[-1] for d in data.values()).date()}', flush=True)

    on5 = pd.DataFrame({s: d['on5'] for s, d in data.items()})
    on21 = pd.DataFrame({s: d['on21'] for s, d in data.items()})
    obg = pd.DataFrame({s: d['obg'] for s, d in data.items()})
    nxt = pd.DataFrame({s: d['next_on_ret'] for s, d in data.items()})
    cl = pd.DataFrame({s: d['close'] for s, d in data.items()})
    dv = pd.DataFrame({s: d['dollar_vol'] for s, d in data.items()})
    # union of all symbol dates == the common RTH trading calendar (ETFs not in this bucket)
    cal = on5.index

    sigs = {'on5': on5, 'on21': on21, 'obg': obg}

    out = {}

    # ---- 0) unconditional close->open baseline (Lane 49 cross-check) ----
    print('=' * 100)
    print('#0 unconditional close->open (all valid names) — Lane 49 cross-check')
    print('=' * 100)
    base_dates = cal[::REBAL['weekly']]
    for bps in COSTS:
        rets, dates = [], []
        for d in base_dates:
            nr = nxt.loc[d]
            cr = cl.loc[d]
            dr = dv.loc[d]
            v = nr.notna() & cr.between(PRICE_LO, PRICE_HI) & (dr > DOLLAR_VOL_MIN)
            r = nr[v]
            if len(r) == 0:
                continue
            net = (1 + r) * (1 - bps) / (1 + bps) - 1
            rets.extend(net.tolist())
            dates.extend([d] * len(r))
        c = cell(rets, dates)
        out[f'baseline_{bps}'] = c
        print(f'  @{bps*1e4:.0f}bp/side  ALL {fmt(c["all"]) if c else "n/a"}')
        print(f'                   IS  {fmt(c["is"]) if c else ""}   OOS {fmt(c["oos"]) if c else ""}')

    # ---- 1) signal x rebalance: long top decile / top quintile net, top-bot spread ----
    for rname, R in REBAL.items():
        dates = cal[::R]
        print('\n' + '=' * 100)
        print(f'#1 rebalance={rname} (every {R} trading days, {len(dates)} dates)')
        print('=' * 100)
        for sname, sig in sigs.items():
            for bps in COSTS:
                b = f'{bps*1e4:.0f}bp'
                top_d, top_q = [], []
                top_d_d, top_q_d = [], []
                spreads, spread_dates = [], []
                for d in dates:
                    sr = sig.loc[d]
                    nr = nxt.loc[d]
                    cr = cl.loc[d]
                    dr = dv.loc[d]
                    v = sr.notna() & nr.notna() & cr.between(PRICE_LO, PRICE_HI) & (dr > DOLLAR_VOL_MIN)
                    s = sr[v]; r = nr[v]
                    if len(s) < 20:
                        continue
                    pct = s.rank(pct=True)
                    td = pct >= 0.9
                    tq = pct >= 0.8
                    bd = pct <= 0.1
                    net = (1 + r) * (1 - bps) / (1 + bps) - 1
                    top_d.extend(net[td].tolist()); top_d_d.extend([d] * int(td.sum()))
                    top_q.extend(net[tq].tolist()); top_q_d.extend([d] * int(tq.sum()))
                    if td.any() and bd.any():
                        spreads.append(float(r[td].mean() - r[bd].mean()))  # gross per-date spread
                        spread_dates.append(d)
                ct = cell(top_d, top_d_d)
                cq = cell(top_q, top_q_d)
                # gross spread evidence (per-date top-decile minus bottom-decile)
                spread_avg = float(np.mean(spreads) * 1e4) if spreads else float('nan')
                st = day_t(spreads, spread_dates)
                print(f'\n  {sname} ({SIGNALS[sname]})  @{b}/side:')
                print(f'    LONG top-decile   ALL {fmt(ct["all"]) if ct else "n/a"}')
                print(f'                       IS  {fmt(ct["is"]) if ct else ""}   OOS {fmt(ct["oos"]) if ct else ""}')
                print(f'    LONG top-quintile ALL {fmt(cq["all"]) if cq else "n/a"}')
                print(f'                       IS  {fmt(cq["is"]) if cq else ""}   OOS {fmt(cq["oos"]) if cq else ""}')
                print(f'    gross spread top10-bot10  avg={spread_avg:+.1f}bp  t_day={st:+.2f}')
                out[f'{sname}_{rname}_topdec_{b}'] = ct
                out[f'{sname}_{rname}_topquin_{b}'] = cq
                out[f'{sname}_{rname}_spread_bp'] = round(float(spread_avg), 1)
                out[f'{sname}_{rname}_spread_t'] = st

    json.dump(out, open(os.path.join(_ROOT, 'research', 'overnight_momentum_results.json'), 'w'),
              indent=1, default=str)
    print('\nwrote research/overnight_momentum_results.json')


if __name__ == '__main__':
    main()
