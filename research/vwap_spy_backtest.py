#!/usr/bin/env python3
"""VWAP 2-sigma reversion — SPY/QQQ fractional (Robinhood) backtest.

Tests whether the VALIDATED intraday VWAP 2σ edge (OOS PF 1.11-1.38 @1t on
ES/NQ/MES/MNQ futures) transfers to SPY/QQQ, which is what $700 fractional
shares can actually trade (whole-share can't touch a $776 SPY).

Data: real SPY/QQQ 5-min RTH bars pulled from IBKR (~1y). Signal = the exact
lane10_vwap_sweep logic (session VWAP, z = (close-vwap)/σ, long z<-K, short
z>+K, high-volume entry filter, exit on reversion, 2xATR stop, EOD flatten).

Cost model (fractional Robinhood): $0 commission, tick = $0.01 (1-cent spread).
Tested at 0/1/2 ticks of adverse-selection slip per side. Walk-forward 60/40.
"""
import os, sys, time, argparse
import numpy as np
import pandas as pd
from ib_insync import IB, Stock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import intraday_validate as IV
import lane10_vwap_sweep as LW

# SPY/QQQ fractional specs: mult=$1/share, tick=$0.01, comm=$0 (RH commission-free)
for _s in ['SPY', 'QQQ']:
    IV.SPECS[_s] = dict(mult=1.0, tick=0.01, comm=0.0)

SYMS = ['SPY', 'QQQ']
VWAP_K_SWEEP = [1.5, 2.0, 2.5]
HV_MULT_SWEEP = [0.0, 1.0, 1.5, 2.0]
SLIP = [0, 1, 2]


def pull_ibkr(sym, duration='1 Y', barsize='5 mins'):
    ib = IB()
    ib.connect('127.0.0.1', 4002, clientId=94, readonly=True, timeout=15)
    ib.RequestTimeout = 300  # deep 5-min history exceeds the 60s default
    c = Stock(sym, 'SMART', 'USD')
    ib.qualifyContracts(c)
    bars = ib.reqHistoricalData(c, '', duration, barsize, 'TRADES',
                                useRTH=True, formatDate=2)
    ib.disconnect()
    rows = [{'ts': b.date, 'open': b.open, 'high': b.high, 'low': b.low,
             'close': b.close, 'volume': b.volume} for b in bars]
    return rows


def to_df(rows):
    df = pd.DataFrame(rows)
    df['ts'] = pd.to_datetime(df['ts'], utc=True).dt.tz_convert('America/New_York')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    df = df.sort_values('ts').drop_duplicates('ts').set_index('ts')
    df['day'] = df.index.date
    return df[['open', 'high', 'low', 'close', 'volume', 'day']]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--duration', default='1 Y')
    ap.add_argument('--cache', action='store_true', help='reuse /tmp cache if present')
    args = ap.parse_args()

    for sym in SYMS:
        cache = f'/tmp/vwap_{sym}_5min.pkl'
        if args.cache and os.path.exists(cache):
            df = pd.read_pickle(cache)
        else:
            rows = pull_ibkr(sym, args.duration)
            df = to_df(rows)
            df.to_pickle(cache)
        print(f'=== {sym}: {len(df)} bars, {df["day"].nunique()} sessions, '
              f'{df["volume"].notna().mean()*100:.0f}% volume populated, '
              f'close range {df["close"].min():.1f}-{df["close"].max():.1f}', flush=True)

        best = None
        for k in VWAP_K_SWEEP:
            for hv in HV_MULT_SWEEP:
                trades = LW.make_vwap_sweep(df, k, hv)
                if not trades:
                    print(f'  K{k} HV{hv}: 0 trades'); continue
                spec = IV.SPECS[sym]
                train, oos = IV.walk_forward_split(trades)
                row = {}
                for slip in SLIP:
                    nt = IV.apply_cost(trades, spec, slip, True)
                    oo = IV.apply_cost(oos, spec, slip, True)
                    s = IV.summarize(nt, IV.daily_buckets(nt, trades))
                    so = IV.summarize(oo, IV.daily_buckets(oo, oos))
                    row[slip] = (s, so)
                s1, so1 = row[1]
                n_day = len(trades) / max(df['day'].nunique(), 1)
                print(f'  K{k} HV{hv}: n={s1["n"]:4d} ({n_day:.1f}/day) '
                      f'win={s1["win"]:3.1f}% PF={s1["pf"]:.2f} '
                      f'OOS_PF@1t={so1["pf"]:.2f} (n={so1["n"]}) maxDD={s1["maxdd"]:.1f}t', flush=True)
                if best is None or (so1['pf'] > best[0] and so1['n'] >= 30):
                    best = (so1['pf'], k, hv, so1['n'])
        if best:
            print(f'  >>> {sym} best OOS_PF@1t = {best[0]:.2f} (K{best[1]}, HV{best[2]}, n={best[3]})')
        print()


if __name__ == '__main__':
    main()
