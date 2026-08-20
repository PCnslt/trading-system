#!/usr/bin/env python3
"""Validate the score-based Creamer auction setups across all archived MNQ sessions.

For each session: run generate_setups (score >= 0.60 threshold), then simulate the
outcome on the remaining 5-min bars of the SAME session (target = POC, stop = setup
stop; short wins if low <= target first, long if high >= target). Reports win rate,
avg R, and expectancy — the honest "does the score predict" check.

Signal-only, exec=NONE. Sample is small (only ~10 sessions archived); read the
numbers as a first indication, not statistical significance.
"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from bot.microstructure_engine import (_load_bars, _load_ticks, _list_prefix,
                                       compute_session_features)
from bot.auction_signals import generate_setups, _load_bars_multi

S3 = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
SYM = 'MNQ'


def simulate(bars, s):
    """Return ('WIN'|'LOSS'|'TIME', R_multiple) for a setup on the same-session bars."""
    entry, stop, t1, side = s['entry'], s['stop'], s['target_poc'], s['side']
    for j, b in enumerate(bars):
        if b.get('ts') != s['bar_ts']:
            continue
        for k in range(j + 1, len(bars)):
            bh, bl = bars[k].get('high'), bars[k].get('low')
            if side == 'short':
                if bl is not None and t1 is not None and bl <= t1:
                    return 'WIN', (entry - t1) / (stop - entry)
                if bh is not None and stop is not None and bh >= stop:
                    return 'LOSS', -1.0
            else:
                if bh is not None and t1 is not None and bh >= t1:
                    return 'WIN', (t1 - entry) / (entry - stop)
                if bl is not None and stop is not None and bl <= stop:
                    return 'LOSS', -1.0
        last = bars[-1].get('close')
        r = (entry - last) / (stop - entry) if (side == 'short' and stop > entry) else 0.0
        return 'TIME', r
    return 'TIME', 0.0


def main():
    dates = sorted({k.split('/')[4].replace('.json', '')
                    for k in _list_prefix(S3, f'futures-bars/intraday/{SYM}/5min/')})
    print(f'sessions: {len(dates)} -> {dates[0]} .. {dates[-1]}')

    all_setups, outcomes = [], []
    for di, date in enumerate(dates):
        bars = _load_bars(S3, SYM, date)
        if len(bars) < 20:
            continue
        ticks = _load_ticks(S3, SYM, date)
        per_bar, profile, imbalance = compute_session_features(SYM, bars, ticks, None)
        window = dates[max(0, di - 9):di + 1]
        sb = _load_bars_multi(S3, SYM, window)
        setups, _ = generate_setups(SYM, sb, bars, per_bar, profile, imbalance)
        for s in setups:
            all_setups.append((date, s))
            res, r = simulate(bars, s)
            outcomes.append((res, r))
        print(f'  {date}: {len(setups)} setups  (cumulative {len(all_setups)})', flush=True)

    print(f'\ntotal setups: {len(all_setups)}')
    if not all_setups:
        return
    wins = sum(1 for o in outcomes if o[0] == 'WIN')
    losses = sum(1 for o in outcomes if o[0] == 'LOSS')
    times = sum(1 for o in outcomes if o[0] == 'TIME')
    print(f'WIN {wins} | LOSS {losses} | TIME {times}')
    decided = wins + losses
    if decided:
        wr = wins / decided
        avgR = sum(o[1] for o in outcomes if o[0] in ('WIN', 'LOSS')) / decided
        exp = wr * avgR - (1 - wr)
        print(f'win rate (decided): {wr:.0%} | avg R: {avgR:+.2f} | expectancy: {exp:+.2f}R')
    for (d, s), (res, r) in zip(all_setups, outcomes):
        print(f'  {d} {s["side"]:5s} score={s["score"]:.3f} R={r:+.2f} -> {res}')


if __name__ == '__main__':
    main()
