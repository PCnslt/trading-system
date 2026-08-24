"""VIX term-structure slope backtest — Fassas & Hourvouliades (2019) replication.

Signal: VIX futures curve slope. 2-point proxy = VIX(30d) / VXV(3m) ratio:
  ratio < 1  => contango (normal, VIX < VXV)
  ratio > 1  => backwardation (panic, VIX > VXV)  — Fassas: predicts HIGHER fwd returns.

Data: FRED VIXCLS + VXVCLS (free fredgraph.csv, no key) + SPY (S3 yf/etfs/SPY.json).

VERDICT (2026-08-24): does NOT replicate on 2007-2026. Backwardation predicts
flat-to-negative fwd returns (extreme ratio>1.2 => 5d -1.24% / 10d -2.57% =
crisis momentum, not bounce). The robust signal is the spot-VIX LEVEL
(Simon-Wiggins 2001), not the slope. Lane 44.
"""
import json
import requests
import boto3
import pandas as pd

S3 = boto3.client('s3', region_name='us-east-1')
B = 'trading-datalake-920641308584'


def fred(sid):
    r = requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv',
                     params={'id': sid}, timeout=60)
    rows = []
    for ln in r.text.strip().splitlines()[1:]:
        p = ln.split(',')
        if len(p) >= 2 and p[1] not in ('', '.'):
            try:
                rows.append((pd.to_datetime(p[0]), float(p[1])))
            except (ValueError, TypeError):
                pass
    return pd.DataFrame(rows, columns=['date', sid]).set_index('date')


def main():
    vix = fred('VIXCLS').rename(columns={'VIXCLS': 'vix'})
    vxv = fred('VXVCLS').rename(columns={'VXVCLS': 'vxv'})
    spy = pd.DataFrame(json.loads(
        S3.get_object(Bucket=B, Key='yf/etfs/SPY.json')['Body'].read().decode())['daily'])
    spy['date'] = pd.to_datetime(spy['ts']).dt.tz_localize(None)
    spy = spy.set_index('date')['close'].rename('close')

    df = vix.join(vxv).join(spy).dropna().sort_index()
    df['ratio'] = df['vix'] / df['vxv']  # <1 contango, >1 backwardation
    for H in (1, 3, 5, 10, 20):
        df[f'fwd{H}'] = df['close'].shift(-H) / df['close'] - 1

    print(f'=== VIX term-structure (VIX/VXV) -> SPY, {df.index[0].date()}..{df.index[-1].date()} (n={len(df)}) ===')
    print('baseline:', ' '.join(f'{h}d {df[f"fwd{h}"].mean()*100:+.3f}%' for h in (1, 3, 5, 10, 20)))
    for lbl, cond in [('backwardation ratio<1.0', df['ratio'] < 1.0),
                      ('strong backwardation <0.90', df['ratio'] < 0.90),
                      ('contango ratio>1.05', df['ratio'] > 1.05),
                      ('deep contango ratio>1.20', df['ratio'] > 1.20)]:
        s = df[cond]
        print(f'  {lbl} (n={len(s)}):', ' '.join(f'{h}d {s[f"fwd{h}"].mean()*100:+.3f}%' for h in (1, 3, 5, 10, 20)))


if __name__ == '__main__':
    main()
