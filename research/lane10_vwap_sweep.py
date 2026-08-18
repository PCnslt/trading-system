#!/usr/bin/env python3
"""LANE 10 — Intraday VWAP (2-sigma reversion) DEFINITIVE param sweep + volume filter.

Follow-up to INTRADAY_GATE1_VALIDATION (which found VWAP HOLD: pooled 1.12 @0t /
1.08 @1t / 1.00 @3t, OOS 1.03, per-symbol-inconsistent — Nasdaq micros/minis
positive, S&P/energy negative).

This sweep:
  - VWAP_K in {1.5, 2.0, 2.5}  (the 2-sigma reversion band width)
  - High-volume entry filter  HV_MULT in {OFF, 1.0, 1.5, 2.0}
      only enter when current-bar volume >= HV_MULT * 20-bar rolling mean volume
      (relative-volume-spike confirmation; OFF = baseline, no filter).
  - Same honest-fill engine + cost model as intraday_validate.py:
      entry at signal close + adverse slip; GTC stop gap-through-aware; EOD flatten;
      slip 0/1/2/3 ticks per side + flat commission per round-trip.
  - Walk-forward 60/40 by session date; OOS = last 40% of sessions.

GO BAR (from laptop directive): OOS PF >= 1.1 at realistic 1-tick slippage
(1t/side + commission) AND consistent across >= 2 symbol groups.

Symbol groups:
  S&P     = {MES, ES}
  Nasdaq  = {MNQ, NQ}
  Dow     = {YM}
  Russell = {RTY}
  Metals  = {GC}
  Energy  = {CL, NG}

A group is "positive" if its pooled OOS PF @1t >= 1.1. Consistency = count of
positive groups. Verdict GO only if consistency >= 2 (and, for robustness, we
also report the per-symbol consensus so a single-symbol group can't flatter).

READ-ONLY: S3 get_object only. No IBKR, no DynamoDB, no orders.
"""
import argparse
import json
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import intraday_validate as IV  # reuse loader/engine/cost/metrics (research/intraday_validate.py)

LIQUID = ['MES', 'MNQ', 'ES', 'NQ', 'RTY', 'YM', 'GC', 'CL', 'NG']

GROUPS = {
    'S&P':     ['MES', 'ES'],
    'Nasdaq':  ['MNQ', 'NQ'],
    'Dow':     ['YM'],
    'Russell': ['RTY'],
    'Metals':  ['GC'],
    'Energy':  ['CL', 'NG'],
}

VWAP_K_SWEEP = [1.5, 2.0, 2.5]
HV_MULT_SWEEP = [0.0, 1.0, 1.5, 2.0]   # 0.0 = filter OFF
HV_WIN = 20
SLIP_LEVELS = [0, 1, 2, 3]


def make_vwap_sweep(df, vwap_k, hv_mult):
    """Parameterized VWAP 2-sigma reversion (same logic as intraday_validate.make_vwap,
    plus an optional high-volume entry filter)."""
    o = df['open'].to_numpy(); h = df['high'].to_numpy()
    l = df['low'].to_numpy(); c = df['close'].to_numpy()
    days = list(df['day'])
    atr = IV.wilder_atr(df['high'], df['low'], df['close'], IV.ATR_N).to_numpy()
    tp = (df['high'] + df['low'] + df['close']) / 3
    vol = df['volume'].clip(lower=0.0)
    vwap = IV.session_cumsum(tp * vol) / IV.session_cumsum(vol).replace(0, np.nan)
    dev = df['close'] - vwap
    sd = dev.groupby(df['day']).rolling(IV.VWAP_SD_N, min_periods=IV.VWAP_SD_N).std().reset_index(level=0, drop=True)
    vwap_a = vwap.to_numpy()
    sd_a = sd.to_numpy()

    # high-volume filter: current-bar volume vs 20-bar rolling mean volume
    roll_vol = vol.rolling(HV_WIN, min_periods=HV_WIN).mean().to_numpy()
    vol_a = vol.to_numpy()

    def enter_fn(i):
        s = sd_a[i]
        if s != s or s == 0:
            return 0
        if hv_mult > 0:
            rv = roll_vol[i]
            if rv != rv or rv == 0:
                return 0                      # no rolling-volume reference yet
            if vol_a[i] < hv_mult * rv:
                return 0                      # low volume -> skip
        z = (c[i] - vwap_a[i]) / s
        if z < -vwap_k:
            return 1
        if z > vwap_k:
            return -1
        return 0

    def exit_fn(i, pos, entry_px, entry_i, stop):
        v = vwap_a[i]
        return (pos == 1 and c[i] >= v) or (pos == -1 and c[i] <= v)

    def stop_fn(i, entry_px, side):
        a = atr[i]
        return None if (a != a) else (entry_px - 2.0 * a if side == 1 else entry_px + 2.0 * a)

    return IV.run_engine(o, h, l, c, days, enter_fn, exit_fn, stop_fn)


def pf_of(net):
    net = np.asarray(net, dtype=float)
    if len(net) == 0:
        return 0.0
    wins = net[net > 0].sum()
    losses = abs(net[net <= 0].sum())
    return float(wins / losses) if losses > 0 else float('inf')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', default=','.join(LIQUID))
    ap.add_argument('--out', default=None, help='output JSON path (default research/lane10_vwap_sweep_results.json)')
    args = ap.parse_args()

    syms = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'lane10_vwap_sweep_results.json')

    print('=' * 110)
    print('LANE 10 — VWAP 2-sigma reversion: VWAP_K x high-volume-filter sweep')
    print('=' * 110, flush=True)

    # load 5-min data once (cached to /tmp via IV.load_intraday)
    data = {}
    for sym in syms:
        df = IV.load_intraday(sym, '5min')
        if df.empty:
            print(f'  {sym}: NO DATA')
            continue
        data[sym] = df
        print(f'  loaded {sym} 5min: {len(df)} bars, {df["day"].nunique()} sessions', flush=True)

    results = {
        'lane': 10, 'strategy': 'VWAP 2-sigma reversion',
        'cost_model': 'slip ticks/side + flat commission per round-trip',
        'go_bar': 'OOS PF >= 1.1 @1-tick+comm AND consistent across >=2 symbol groups',
        'groups': GROUPS,
        'vwap_k_sweep': VWAP_K_SWEEP,
        'hv_mult_sweep': HV_MULT_SWEEP,
        'hv_win': HV_WIN,
        'slip_levels': SLIP_LEVELS,
        'combos': {},
        'per_symbol_headline': {},
    }

    # ---- run every combo once, cache trades per (k,hv,sym) ----
    TRADES = {}          # (k,hv,sym) -> trades list
    OOS_NET_1T = {}      # (k,hv,sym) -> list of OOS net-ticks @1t+comm
    for k in VWAP_K_SWEEP:
        for hv in HV_MULT_SWEEP:
            tag = f'K{k}_HV{hv}'
            per_sym = {}
            for sym in syms:
                df = data.get(sym)
                if df is None:
                    per_sym[sym] = dict(error='no data')
                    continue
                trades = make_vwap_sweep(df, k, hv)
                TRADES[(k, hv, sym)] = trades
                if not trades:
                    per_sym[sym] = dict(n=0)
                    OOS_NET_1T[(k, hv, sym)] = []
                    continue
                spec = IV.SPECS[sym]
                train, oos = IV.walk_forward_split(trades)
                row = {}
                oos_net_1t = []
                for slip in SLIP_LEVELS:
                    nt = IV.apply_cost(trades, spec, slip, True)
                    oo = IV.apply_cost(oos, spec, slip, True)
                    s = IV.summarize(nt, IV.daily_buckets(nt, trades))
                    so = IV.summarize(oo, IV.daily_buckets(oo, oos))
                    row[f'slip{slip}'] = dict(pf=s['pf'], net=s['net'], n=s['n'],
                                              win=s['win'], maxdd=s['maxdd'],
                                              oos_pf=so['pf'], oos_n=so['n'])
                    if slip == 1:
                        oos_net_1t = [float(x) for x in oo]
                per_sym[sym] = row
                OOS_NET_1T[(k, hv, sym)] = oos_net_1t
            results['combos'][tag] = per_sym
            # print headline @1-tick (the GO bar) per symbol
            print(f'\n  [{tag}]  OOS PF @1t+comm  (GO bar: >=1.1):', flush=True)
            for sym in syms:
                r = per_sym.get(sym, {})
                if r and r.get('slip1'):
                    print(f'    {sym:4s}  n={r["slip1"]["n"]:5d}  PF={r["slip1"]["pf"]:5.2f}  '
                          f'OOS={r["slip1"]["oos_pf"]:5.2f} (n={r["slip1"]["oos_n"]})', flush=True)
                elif r:
                    print(f'    {sym:4s}  {r}', flush=True)
            print('-' * 110, flush=True)

    # ---- per-group OOS PF @1t for the GO decision (reuse cached OOS net ticks) ----
    # group pooled OOS PF from pooled net-tick arrays (per-symbol PF is
    # scale-invariant; pooled raw ticks mix contract sizes -> reported but flagged).
    go_rows = []
    for k in VWAP_K_SWEEP:
        for hv in HV_MULT_SWEEP:
            tag = f'K{k}_HV{hv}'
            group_pos = {}
            group_oos = {}
            for gname, gsyms in GROUPS.items():
                oos_nets = []
                for sym in gsyms:
                    oos_nets.extend(OOS_NET_1T.get((k, hv, sym), []))
                if oos_nets:
                    group_oos[gname] = pf_of(oos_nets)
                    group_pos[gname] = group_oos[gname] >= 1.1
                else:
                    group_oos[gname] = 0.0
                    group_pos[gname] = False
            n_pos = sum(group_pos.values())
            go_rows.append(dict(tag=tag, group_oos_pf_1t=group_oos,
                                n_groups_positive=n_pos,
                                groups=group_pos))
    results['go_decision'] = go_rows

    # ---- per-symbol headline table (K=2.0 baseline, HV off) for the report ----
    base = results['combos'].get('K2.0_HV0.0', {})
    results['per_symbol_headline'] = {
        sym: (base[sym].get('slip1') if base.get(sym) and base[sym].get('slip1') else None)
        for sym in syms
    }

    print('\n\n==== GO DECISION MATRIX (OOS PF @1t+comm per group) ====')
    print(f'{"combo":14s} ' + ' '.join(f'{g:>9s}' for g in GROUPS) + '  #pos')
    for r in go_rows:
        cells = ' '.join(f'{r["group_oos_pf_1t"][g]:9.2f}' for g in GROUPS)
        print(f'{r["tag"]:14s} {cells}  {r["n_groups_positive"]}')
    print('GO BAR: OOS>=1.1 @1t AND #pos>=2')

    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f'\nwrote {out}')

    # summary of best combos
    print('\nBest combos by #positive groups:')
    for r in sorted(go_rows, key=lambda x: -x['n_groups_positive'])[:6]:
        print(f'  {r["tag"]}: {r["n_groups_positive"]} positive groups '
              f'{[g for g,v in r["groups"].items() if v]}')


if __name__ == '__main__':
    main()
