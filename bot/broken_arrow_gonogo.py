#!/usr/bin/env python3
"""Broken Arrow Go/No-Go monitor — forward fill analysis + hard-halt boundaries.

Reads the BATRADE journal (paginated), computes the empirical forward sample against
the OOS baseline (+34bp, t=3.96) and enforces the three halt conditions:
  1. COST DEGRADATION:  mean net return < 6bp friction floor
  2. VARIANCE SPIKE:    win rate materially below baseline OR 3 consecutive losses
  3. MODEL DRIFT:       95% CI of mean net spans zero (edge indistinguishable from noise)

Outputs the execution log (CSV) with: ticker, entry/exit ts, ideal vs realized price,
slippage (bp), rolling net return. Read-only. Places NO orders.
"""
import argparse, csv, io, os, sys
import datetime as dt
import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))
from infra.ssm_secrets import bootstrap as _sb
_sb()
import boto3
from boto3.dynamodb.conditions import Key

REGION = os.getenv('AWS_REGION', 'us-east-1')
TABLE = os.getenv('DYNAMODB_TABLE', 'trading-data')

BASELINE_BP = 34.0       # OOS mean net (backtest)
FLOOR_BP = 6.0           # friction floor: edge must stay above this
CONF = 1.96              # 95% CI z
MIN_N = 10               # need at least this many trades before a Go is even considered

table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE)


def load_trades():
    """Paginated scan of the BATRADE journal."""
    trades = []
    lek = None
    while True:
        kw = dict(FilterExpression='begins_with(pk, :p)',
                  ExpressionAttributeValues={':p': 'BATRADE#'})
        if lek:
            kw['ExclusiveStartKey'] = lek
        r = table.scan(**kw)
        for it in r.get('Items', []):
            try:
                trades.append({
                    'sym': it['pk'].split('#', 1)[1],
                    'entry_date': it.get('entry_date', ''),
                    'exit_date': it.get('exit_date', ''),
                    'entry_price': float(it.get('entry_price') or 0),
                    'exit_price': float(it.get('exit_price') or 0),
                    'gross_bp': float(it.get('gross_bp') or 0),
                    'net_bp': float(it.get('net_bp') or 0),
                    'buy_half_bp': float(it.get('buy_half_bp') or 0) if it.get('buy_half_bp') not in ('', None, 'None') else np.nan,
                    'pnl_usd': float(it.get('pnl_usd') or 0),
                })
            except Exception:
                pass
        lek = r.get('LastEvaluatedKey')
        if not lek:
            break
    trades.sort(key=lambda x: (x['exit_date'], x['sym']))
    return trades


def stats(trades):
    net = np.array([t['net_bp'] for t in trades])
    n = len(net)
    mean = net.mean()
    std = net.std(ddof=1) if n > 1 else np.nan
    med = np.median(net)
    winrate = (net > 0).mean()
    t_vs_zero = mean / (std / np.sqrt(n)) if n > 1 and std > 0 else np.nan
    t_vs_base = (mean - BASELINE_BP) / (std / np.sqrt(n)) if n > 1 and std > 0 else np.nan
    ci_lo = mean - CONF * std / np.sqrt(n) if n > 1 else np.nan
    ci_hi = mean + CONF * std / np.sqrt(n) if n > 1 else np.nan
    # consecutive losses
    streak = max_streak = 0
    for t in trades:
        streak = streak + 1 if t['net_bp'] < 0 else 0
        max_streak = max(max_streak, streak)
    return dict(n=n, mean=mean, std=std, med=med, winrate=winrate,
                t0=t_vs_zero, tb=t_vs_base, ci_lo=ci_lo, ci_hi=ci_hi,
                max_loss_streak=max_streak)


def halt_verdict(s):
    flags = []
    if s['n'] < MIN_N:
        flags.append(f"INSUFFICIENT SAMPLE ({s['n']} < {MIN_N} trades) — cannot Go yet")
    else:
        # 1. cost degradation
        if s['mean'] < FLOOR_BP:
            flags.append(f"COST DEGRADATION: mean net {s['mean']:+.1f}bp < {FLOOR_BP}bp floor")
        # 2. variance spike
        if s['winrate'] < 0.45:
            flags.append(f"VARIANCE SPIKE: win rate {s['winrate']*100:.0f}% materially below ~52% baseline")
        if s['max_loss_streak'] >= 3:
            flags.append(f"VARIANCE SPIKE: {s['max_loss_streak']} consecutive stop-outs")
        # 3. model drift (CI spans zero)
        if not np.isnan(s['ci_lo']) and s['ci_lo'] <= 0 <= s['ci_hi']:
            flags.append(f"MODEL DRIFT: 95% CI [{s['ci_lo']:+.1f}, {s['ci_hi']:+.1f}]bp spans zero")
    if not flags and s['n'] >= MIN_N:
        return 'GO', 'all boundaries clear'
    return 'NO-GO' if s['n'] >= MIN_N else 'HOLD', '; '.join(flags) or 'pending'


def main():
    trades = load_trades()
    s = stats(trades)
    verdict, why = halt_verdict(s)

    print(f"Broken Arrow forward fill analysis — {dt.date.today()}")
    print(f"trades={s['n']}  mean_net={s['mean']:+.1f}bp  median={s['med']:+.1f}bp  "
          f"std={s['std']:.0f}bp  win={s['winrate']*100:.0f}%")
    print(f"t vs 0 = {s['t0']:+.2f}   t vs +34bp baseline = {s['tb']:+.2f}")
    print(f"95% CI = [{s['ci_lo']:+.1f}, {s['ci_hi']:+.1f}]bp   max loss streak = {s['max_loss_streak']}")
    print(f"\n>>> VERDICT: {verdict}  ({why})")

    # execution log CSV
    path = os.path.join(_ROOT, 'research', 'broken_arrow_execution_log.csv')
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ticker', 'entry_date', 'exit_date', 'ideal_entry', 'ideal_exit',
                    'slippage_buy_bp', 'slippage_sell_bp', 'gross_bp', 'net_bp',
                    'rolling_net_bp'])
        roll = []
        for t in trades:
            roll.append(t['net_bp'])
            w.writerow([t['sym'], t['entry_date'], t['exit_date'],
                        f"{t['entry_price']:.4f}", f"{t['exit_price']:.4f}",
                        f"{t['buy_half_bp']:.1f}" if not np.isnan(t['buy_half_bp']) else '',
                        '3.0',  # assumed sell half-spread (to be replaced by live bid)
                        f"{t['gross_bp']:.1f}", f"{t['net_bp']:.1f}",
                        f"{np.mean(roll):+.1f}"])
    print(f"execution log -> {path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
