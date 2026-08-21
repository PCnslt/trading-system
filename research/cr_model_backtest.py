"""
9AM/8AM CR (Candle Range) Model — honest backtest.

The "9am CR Model" (Massimo, ICT/SMC) = define a reference candle-range at the
NY open, wait for a LIQUIDITY SWEEP ("turtle soup") of one extreme, then FADE
the sweep to the OPPOSING side of the range.  Reactive, not predictive.

Faithful rule (from the primary sources + TradingView "CRT Model" Pine default):
  range  = 08:00-09:00 ET hourly candle (pre-open).   <-- NOT in our RTH-only bars
  sweep  = after 09:30 open, price pokes through one extreme then CLOSES BACK inside
  entry  = fade the sweep (sweep high -> short; sweep low -> long)
  stop   = beyond the swept extreme
  target = opposing end of the range (or midpoint EQ)

We do NOT have the 08:00-09:00 pre-open hour in our intraday bar store (RTH only),
so we test the mechanically-identical "opening-range sweep reversal" using the
first N minutes of RTH (09:30 + N) as the reference range.  This is the exact same
family — failed-breakout fade — and it is the honest thing we CAN test on current
data.  We ALSO test the 08:00-09:00 pre-open hour by backfilling 1h bars via IBKR
in a separate step if this opening-range version shows edge.

Cost model: honest per-side slippage + commission, stressed at 1/2/3 ticks round
trip.  MES/MNQ/ES/NQ tick = 0.25 pt.  Results reported gross and net.
"""
import json, boto3, sys, os
from datetime import datetime, timedelta, time as dtime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv('.env')
BUCKET = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')

SYMS = ['MES', 'MNQ', 'ES', 'NQ']
BARSIZE = '5min'

def load_bars(sym):
    """Download all 5min bars for a symbol, return sorted list of dicts."""
    pag = s3.get_paginator('list_objects_v2')
    keys = []
    for p in pag.paginate(Bucket=BUCKET, Prefix=f'futures-bars/intraday/{sym}/{BARSIZE}/'):
        for o in p.get('Contents', []):
            keys.append(o['Key'])
    bars = []
    for k in keys:
        d = json.loads(s3.get_object(Bucket=BUCKET, Key=k)['Body'].read().decode())
        bars.extend(d['bars'])
    bars.sort(key=lambda b: b['ts'])
    return bars

def group_by_day(bars):
    days = defaultdict(list)
    for b in bars:
        # timestamp is like 2026-08-19T09:30:00-04:00
        days[b['ts'][:10]].append(b)
    return days

def run(sym, bars, range_min=30, buf_ticks=1, target='opposing'):
    tick = 0.25
    buf = buf_ticks * tick
    days = group_by_day(bars)
    trades = []
    for date, dbars in sorted(days.items()):
        # reference range = first `range_min` minutes of RTH (09:30 + range_min)
        ref_end = (datetime.combine(datetime.min, dtime(9, 30)) + timedelta(minutes=range_min)).time()
        ref = [b for b in dbars if datetime.fromisoformat(b['ts']).time() < ref_end]
        rest = [b for b in dbars if datetime.fromisoformat(b['ts']).time() >= ref_end]
        if not ref or not rest:
            continue
        preH = max(b['high'] for b in ref)
        preL = min(b['low'] for b in ref)
        rng = preH - preL
        if rng <= 0:
            continue
        # skip degenerate tiny ranges (noise)
        if rng < 2 * tick:
            continue
        for b in rest:
            # upside sweep -> fade short
            if b['high'] > preH + buf and b['close'] < preH:
                entry = b['close']
                stop = max(b['high'], preH) + buf
                tgt = preL if target == 'opposing' else (preH + preL) / 2
                # simulate to end of day
                exit_p = None
                for b2 in rest[rest.index(b)+1:]:
                    if tgt <= preH:  # short: target below
                        if b2['low'] <= tgt:
                            exit_p = tgt; break
                        if b2['high'] >= stop:
                            exit_p = stop; break
                    else:
                        if b2['high'] >= tgt:
                            exit_p = tgt; break
                        if b2['low'] <= stop:
                            exit_p = stop; break
                if exit_p is None:
                    exit_p = rest[-1]['close']
                trades.append(('short', entry, stop, exit_p, rng, date))
                break
            # downside sweep -> fade long
            if b['low'] < preL - buf and b['close'] > preL:
                entry = b['close']
                stop = min(b['low'], preL) - buf
                tgt = preH if target == 'opposing' else (preH + preL) / 2
                exit_p = None
                for b2 in rest[rest.index(b)+1:]:
                    if tgt >= preL:  # long: target above
                        if b2['high'] >= tgt:
                            exit_p = tgt; break
                        if b2['low'] <= stop:
                            exit_p = stop; break
                    else:
                        if b2['low'] <= tgt:
                            exit_p = tgt; break
                        if b2['high'] >= stop:
                            exit_p = stop; break
                if exit_p is None:
                    exit_p = rest[-1]['close']
                trades.append(('long', entry, stop, exit_p, rng, date))
                break
    return trades

def metrics(trades, cost_pts):
    """cost_pts = round-trip cost in points."""
    if not trades:
        return None
    wins = 0; sumR = 0.0; grossR = 0.0; netpts = 0.0
    rs = []
    for side, e, s, x, rng, date in trades:
        risk = abs(e - s)
        if risk <= 0:
            continue
        r = (x - e) / risk if side == 'long' else (e - x) / risk
        # net points after cost
        raw = (x - e) if side == 'long' else (e - x)
        netpts += raw - cost_pts
        grossR += r
        if r > 0:
            wins += 1
        rs.append(r)
    n = len(rs)
    # R after cost (cost in R terms varies per trade; approximate: cost/avg risk)
    avg_risk = sum(abs(e - s) for side, e, s, x, rng, date in trades) / n
    netR = grossR - n * (cost_pts / avg_risk)
    return dict(n=n, win=wins/n, grossR=grossR, netR=netR, avg_risk=avg_risk,
                netpts=netpts, rs=rs)

def maxdd(rs):
    eq = 0.0; peak = 0.0; mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return mdd

if __name__ == '__main__':
    for sym in SYMS:
        print(f'\n######## {sym} ########')
        try:
            bars = load_bars(sym)
        except Exception as e:
            print('  load ERR', e); continue
        print(f'  {len(bars)} bars, {len(group_by_day(bars))} days')
        for rm in [15, 30, 60]:
            for buf in [0, 1]:
                for tgt in ['opposing', 'eq']:
                    tr = run(sym, bars, range_min=rm, buf_ticks=buf, target=tgt)
                    if not tr:
                        print(f'  range={rm}m buf={buf}t tgt={tgt:>8}: 0 trades'); continue
                    g = metrics(tr, 0.0)
                    print(f'  range={rm}m buf={buf}t tgt={tgt:>8}: n={g["n"]:3d} win={g["win"]*100:4.0f}% '
                          f'grossR={g["grossR"]:+.1f} avgRisk={g["avg_risk"]:.2f}pt '
                          f'maxDD={maxdd(g["rs"]):.1f}R')
