import os, io, json
import boto3, pandas as pd, numpy as np

S3 = boto3.client('s3', region_name='us-east-1')
BUCKET = 'trading-datalake-920641308584'

def load_closes(n=300):
    with open('/home/ubuntu/trading-system/research/universe_1500.json') as f:
        raw = json.load(f)
    syms = (raw.get('symbols') if isinstance(raw, dict) else raw)[:n]
    out = {}
    for s in syms:
        try:
            o = S3.get_object(Bucket=BUCKET, Key=f'ibkr/equities/daily/{s}.parquet')
            df = pd.read_parquet(io.BytesIO(o['Body'].read()))
            df['date'] = pd.to_datetime(df['date'])
            out[s] = df.set_index('date')['close'].sort_index()
        except Exception:
            pass
    return out

closes = load_closes(300)
print('symbols:', len(closes))

# build a date grid
all_dates = sorted(set().union(*[set(c.index) for c in closes.values()]))
print('date range:', all_dates[0].date(), '->', all_dates[-1].date())

# monthly signal: prior-month return (skip last 5 days), top-25, forward return at horizons
HORIZONS = [2, 3, 5, 10, 20]
rows = []
dates = all_dates[30:]  # need 25 days of history for the signal
prev_signal_date = None
basket = []
for d in dates:
    # rebalance at month boundary, and measure forward return ONLY here (non-overlapping)
    if prev_signal_date is None or d.month != prev_signal_date.month:
        sig = {}
        for s, c in closes.items():
            seg = c[c.index < d]
            if len(seg) < 26:
                continue
            ret = float(seg.iloc[-6]) / float(seg.iloc[-25]) - 1.0
            sig[s] = ret
        basket = sorted(sig, key=sig.get, reverse=True)[:25]
        prev_signal_date = d
        for h in HORIZONS:
            rets = []
            for s in basket:
                c = closes[s]
                if d in c.index:
                    j = c.index.get_loc(d)
                    if j + h < len(c):
                        rets.append(float(c.iloc[j + h]) / float(c.iloc[j]) - 1.0)
            if rets:
                rows.append({'date': d, 'horizon': h, 'avg': np.mean(rets) * 10000})

df = pd.DataFrame(rows)
print('\nSTMOM top-25 forward return (bp) by horizon:')
for h in HORIZONS:
    sub = df[df.horizon == h]
    oos = sub[sub.date >= '2022-08-30']
    is_ = sub[sub.date < '2022-08-30']
    def t_stat(x):
        if len(x) < 3: return float('nan')
        return float(np.mean(x) / (np.std(x, ddof=1) / np.sqrt(len(x))))
    print(f'  {h:>2}d: IS {np.mean(is_.avg):+7.1f}bp (t {t_stat(is_.avg):+.2f}) | OOS {np.mean(oos.avg):+7.1f}bp (t {t_stat(oos.avg):+.2f}, n={len(oos)})')
