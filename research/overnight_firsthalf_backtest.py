#!/usr/bin/env python3
"""Overnight-return -> first-half-hour predictability on US index futures
(queue strat-20260911-2).

Iwanaga & Sakemoto 2026 (NAJEF, DOI 10.1016/j.najef.2026.102707): does the
overnight (close->open) return of a US index predict the FIRST half-hour
(09:30-10:00 ET) return — REVERSAL (fade the overnight move at the open) or
continuation? Corroborating mechanism: Berkman-Koch-Tuttle-Zhang 2012 JFQA
(attention-driven high opens reverse intraday).

This is index-FUTURES + overnight-conditioned + first-30-min only — distinct
from the retired first->LAST half-hour momentum (Gao/Baltussen) and from
single-stock gap-fade.

Data: IBKR RTH 5-min bars from S3 (futures-bars/intraday/{sym}/5min/),
ES/MES/NQ, ~1y (ES 181 / MES 185 / NQ 154 sessions, 2025-08..2026-09).

Honest fills: index-futures round trip = 2*slip_ticks*tick + 2*commission,
reported at 1-tick and 2-tick slip (ES/MES/NQ tick 0.25). IS/OOS = 60/40
chronological split by session date. n is small -> flagged honestly.

READ-ONLY: S3 get_object only.
"""
from __future__ import annotations

import os
import sys
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'research'))

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, '.env'))

import intraday_validate as IV

SPECS = {  # (mult $/point, tick, commission $/side)
    'ES':  (50.0,  0.25, 1.60),
    'MES': (5.0,   0.25, 0.62),
    'NQ':  (20.0,  0.25, 1.60),
}
SYMS = ['ES', 'MES', 'NQ']
TF = '5min'
N_BARS_HALFHR = 6            # 09:30..09:55 (close = 10:00) -> first half hour
OOS_FRAC = 0.60
SLIPS = [1, 2]               # ticks per side


def session_features(df):
    """Per full session: overnight (close->open) return + first-half-hour return.

    Only sessions whose first bar is 09:30, that have >= N_BARS_HALFHR bars, and
    whose previous session close exists are usable.
    """
    d = df.copy()
    d['day'] = pd.to_datetime(d['day']).astype(str)
    d['tm'] = d.index.strftime('%H:%M')
    days = sorted(d['day'].unique())
    day_open, day_close, day_first6close = {}, {}, {}
    for day in days:
        g = d[d['day'] == day]
        if len(g) < N_BARS_HALFHR or g['tm'].iloc[0] != '09:30':
            continue
        day_open[day] = float(g['open'].iloc[0])
        day_close[day] = float(g['close'].iloc[-1])
        day_first6close[day] = float(g['close'].iloc[N_BARS_HALFHR - 1])
    rows = []
    for i in range(1, len(days)):
        day = days[i]
        prev = days[i - 1]
        if day not in day_open or prev not in day_close:
            continue
        open_t = day_open[day]
        overnight = open_t / day_close[prev] - 1.0
        halfhr = day_first6close[day] / open_t - 1.0
        rows.append({'date': pd.Timestamp(day), 'open_t': open_t,
                     'overnight_bp': overnight * 1e4, 'halfhr_bp': halfhr * 1e4})
    return pd.DataFrame(rows).set_index('date')


def stats(rets_bp):
    r = np.asarray(rets_bp, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) == 0:
        return None
    w = r[r > 0].sum(); l = -r[r <= 0].sum()
    pf = w / l if l > 0 else float('inf')
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 and len(r) > 1 else 0.0
    return {'n': int(len(r)), 'pf': round(pf, 3), 'win': round(float((r > 0).mean()), 3),
            'avg_bp': round(float(r.mean()), 2), 't': round(float(t), 2)}


def split_stat(rets_bp, dates):
    """stats + 60/40 chronological IS/OOS by session date."""
    r = pd.Series(np.asarray(rets_bp, dtype=float), index=pd.to_datetime(dates))
    r = r.dropna()
    if len(r) == 0:
        return None
    all_s = stats(r.values)
    idx = sorted(r.index)
    cut = idx[int(len(idx) * OOS_FRAC) - 1] if len(idx) > 2 else None
    if cut is not None:
        all_s['is'] = stats(r[r.index <= cut].values)
        all_s['oos'] = stats(r[r.index > cut].values)
    else:
        all_s['is'] = None
        all_s['oos'] = None
    return all_s


def main():
    out = {}
    print('=' * 96)
    print('OVERNIGHT -> FIRST-HALF-HOUR PREDICTABILITY (ES/MES/NQ, 5-min RTH, ~1y)')
    print('=' * 96)
    for sym in SYMS:
        df = IV.load_intraday(sym, TF)
        if df is None or len(df) == 0:
            print(f'\n{sym}: no data')
            continue
        feats = session_features(df)
        if len(feats) < 30:
            print(f'\n{sym}: only {len(feats)} usable sessions (insufficient)')
            continue
        mult, tick, comm = SPECS[sym]
        print(f'\n### {sym}: {len(feats)} usable sessions '
              f'({feats.index[0].date()} .. {feats.index[-1].date()})')

        # 1) correlation + conditional means
        corr = feats['halfhr_bp'].corr(feats['overnight_bp'])
        print(f'  corr(first-half-hour, overnight) = {corr:+.3f}  '
              f'[negative => reversal, positive => continuation]')
        out[f'{sym}_corr'] = round(float(corr), 3)
        for lbl, mask in [('overnight>0', feats['overnight_bp'] > 0),
                          ('overnight<0', feats['overnight_bp'] < 0),
                          ('all', pd.Series(True, index=feats.index))]:
            sub = feats.loc[mask, 'halfhr_bp']
            t = (sub.mean() / (sub.std() / np.sqrt(len(sub)))) if len(sub) > 1 and sub.std() > 0 else 0.0
            print(f'    {lbl:>12}: n={len(sub):>4} halfhr avg={sub.mean():>+7.2f}bp '
                  f'median={sub.median():>+7.2f}bp win={(sub > 0).mean() * 100:>5.1f}% t={t:+.2f}')
            out[f'{sym}_cond_{lbl.replace(">", "gt").replace("<", "lt")}'] = {
                'n': int(len(sub)), 'avg_bp': round(float(sub.mean()), 2),
                'median_bp': round(float(sub.median()), 2),
                'win': round(float((sub > 0).mean()), 3)}

        # 2) tradeable: fade vs continuation, 1t/2t slip + comm
        for direction in ['fade', 'continuation']:
            for slip in SLIPS:
                nets, dates = [], []
                for d, row in feats.iterrows():
                    if direction == 'fade':
                        side = -1.0 if row['overnight_bp'] > 0 else 1.0
                    else:
                        side = 1.0 if row['overnight_bp'] > 0 else -1.0
                    gross_bp = side * row['halfhr_bp']
                    slip_bp = 2 * slip * tick / row['open_t'] * 1e4
                    comm_bp = 2 * comm / (mult * row['open_t']) * 1e4
                    nets.append(gross_bp - slip_bp - comm_bp)
                    dates.append(d)
                s = split_stat(np.array(nets), dates)
                out[f'{sym}_{direction}_slip{slip}'] = s
                if s and s['n'] >= 3:
                    print(f'  {direction:>12} @{slip}t: ALL n={s["n"]:>4} PF={s["pf"]:>6.3f} '
                          f'win={s["win"] * 100:>5.1f}% avg={s["avg_bp"]:>+7.2f}bp t={s["t"]:>+5.2f} '
                          f'| IS {s["is"]["pf"] if s["is"] else "n/a"} / '
                          f'OOS {s["oos"]["pf"] if s["oos"] else "n/a"}')
                else:
                    print(f'  {direction:>12} @{slip}t: n<3')

    json.dump(out, open(os.path.join(_ROOT, 'research',
              'overnight_firsthalf_results.json'), 'w'), indent=1, default=str)
    print('\nwrote research/overnight_firsthalf_results.json')


if __name__ == '__main__':
    main()
