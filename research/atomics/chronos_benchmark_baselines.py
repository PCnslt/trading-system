#!/usr/bin/env python3
"""Baseline-only evaluation (Ridge/LightGBM/momentum/reversal) — same setup as
chronos_benchmark.py but without the Chronos zero-shot loop. Fast (no foundation
model). Used to deliver exact baseline rank IC / directional accuracy when the
Chronos sweep is not available.
"""
import io, json, time
import numpy as np
import pandas as pd
import boto3
import lightgbm as lgb
from sklearn.linear_model import Ridge
from scipy.stats import spearmanr

s3 = boto3.client('s3', region_name='us-east-1')
B = 'trading-datalake-920641308584'
P5 = 'ibkr/equities/5min/'

HORIZON = 6
SPLIT = 0.7
STEP = 6

t0 = time.time()
keys = [o['Key'] for o in s3.list_objects_v2(Bucket=B, Prefix=P5).get('Contents', [])
        if o['Key'].endswith('.parquet')]
syms = sorted(k.split('/')[-1][:-8] for k in keys)

frames = {}
for k in keys:
    s = k.split('/')[-1][:-8]
    d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=k)['Body'].read()))
    d['date'] = pd.to_datetime(d['date'])
    d = d.set_index('date').sort_index()
    d.index = d.index.tz_localize(None)
    frames[s] = d

close = pd.DataFrame({s: frames[s]['close'] for s in syms}).dropna()
volume = pd.DataFrame({s: frames[s]['volume'] for s in syms}).reindex(close.index)
high = pd.DataFrame({s: frames[s]['high'] for s in syms}).reindex(close.index)
low = pd.DataFrame({s: frames[s]['low'] for s in syms}).reindex(close.index)
n_t, n_s = close.shape

r5 = close.pct_change()
r15 = close.pct_change(3)
r30 = close.pct_change(6)
r60 = close.pct_change(12)
delta = close.diff()
up = delta.clip(lower=0)
dn = -delta.clip(upper=0)
rsi = 100 - 100 / (1 + up.rolling(14).mean() / dn.rolling(14).mean())
ema12 = close.ewm(span=12).mean()
ema26 = close.ewm(span=26).mean()
macd = (ema12 - ema26) / close
vwap = (close * volume).rolling(30).sum() / volume.rolling(30).sum()
vwap_dist = (close - vwap) / vwap
vr = volume / volume.rolling(30).median()
rv = r5.rolling(20).std()
atr = (high - low).rolling(14).mean() / close
hour = pd.DataFrame(np.tile(close.index.hour + close.index.minute / 60, (n_s, 1)).T,
                    index=close.index, columns=close.columns)
cs_rank_r30 = r30.rank(axis=1, pct=True)
cs_rank_vr = vr.rank(axis=1, pct=True)
target = close.shift(-HORIZON) / close - 1.0

FEAT_COLS = ['r5', 'r15', 'r30', 'r60', 'rsi', 'macd', 'vwap_dist', 'vr',
             'rv', 'atr', 'hour', 'cs_rank_r30', 'cs_rank_vr']
F = {n: eval(n) for n in FEAT_COLS}

long_parts = [F[n].stack().rename(n) for n in FEAT_COLS]
long_df = pd.concat(long_parts, axis=1)
long_df['target'] = target.stack()
long_df = long_df.dropna(subset=FEAT_COLS + ['target'])

all_dates = sorted(long_df.index.get_level_values(0).unique())
cut = all_dates[int(len(all_dates) * SPLIT)]
tr = long_df[long_df.index.get_level_values(0) < cut]
te = long_df[long_df.index.get_level_values(0) >= cut]

Xtr, ytr = tr[FEAT_COLS].values, tr['target'].values
Xte, yte = te[FEAT_COLS].values, te['target'].values

ridge = Ridge(alpha=1.0); ridge.fit(Xtr, ytr); ridge_pred = ridge.predict(Xte)
lgbm = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=31,
                         subsample=0.8, colsample_bytree=0.8, n_jobs=2,
                         verbose=-1, random_state=0)
lgbm.fit(Xtr, ytr); lgbm_pred = lgbm.predict(Xte)

te_idx = te.index
ridge_wide = pd.Series(ridge_pred, index=te_idx).unstack()
lgbm_wide = pd.Series(lgbm_pred, index=te_idx).unstack()

n_test_start = int(n_t * SPLIT)
positions = list(range(n_test_start, n_t - HORIZON, STEP))

def rank_ic_vec(pred, y):
    m = ~(np.isnan(pred) | np.isnan(y))
    if m.sum() < 10:
        return np.nan
    return spearmanr(pred[m], y[m]).statistic

def dir_acc_vec(pred, y):
    m = ~(np.isnan(pred) | np.isnan(y))
    return np.mean(np.sign(pred[m]) == np.sign(y[m]))

res = {k: {'rank_ic': [], 'dir_acc': []} for k in
       ['ridge', 'lightgbm', 'momentum_r30', 'reversal_r30']}
for p in positions:
    ts = close.index[p]
    actual = target.iloc[p, :].values
    rr = r30.iloc[p, :].values
    rv = -rr
    rg = ridge_wide.loc[ts].reindex(close.columns).values if ts in ridge_wide.index else np.full(n_s, np.nan)
    lg = lgbm_wide.loc[ts].reindex(close.columns).values if ts in lgbm_wide.index else np.full(n_s, np.nan)
    for name, pred in [('ridge', rg), ('lightgbm', lg), ('momentum_r30', rr), ('reversal_r30', rv)]:
        res[name]['rank_ic'].append(rank_ic_vec(pred, actual))
        res[name]['dir_acc'].append(dir_acc_vec(pred, actual))

def agg(v):
    v = np.array([x for x in v if not np.isnan(x)], dtype=float)
    return {'n': int(len(v)), 'mean': float(np.mean(v)) if len(v) else np.nan,
            'std': float(np.std(v)) if len(v) else np.nan,
            't_stat': float(np.mean(v) / (np.std(v) / np.sqrt(len(v)))) if len(v) > 1 else np.nan,
            'median': float(np.median(v)) if len(v) else np.nan}

summary = {k: {'rank_ic': agg(v['rank_ic']), 'dir_acc': agg(v['dir_acc'])} for k, v in res.items()}

out = {
    'experiment': 'chronos_benchmark_baselines_only',
    'config': {'universe': 'ibkr/equities/5min', 'n_symbols': n_s, 'n_train_rows': int(len(tr)),
               'n_test_rows': int(len(te)), 'n_eval_timestamps': len(positions),
               'horizon': '30m (6 bars)', 'split': SPLIT, 'eval_step_bars': STEP,
               'train_range': [str(all_dates[0]), str(cut)], 'test_range': [str(cut), str(all_dates[-1])]},
    'results': summary,
}
with open('research/atomics/chronos_benchmark_baselines.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)

print('=' * 74)
print('BASELINE RESULTS (30m forward return, 40-symbol cross-section)')
print('=' * 74)
print(f"{'model':16s} {'rank_IC':>9s} {'t-stat':>7s} {'dir_acc':>9s} {'n':>5s}")
for name in ['ridge', 'lightgbm', 'momentum_r30', 'reversal_r30']:
    r = summary[name]
    print(f"{name:16s} {r['rank_ic']['mean']:>+9.4f} {r['rank_ic']['t_stat']:>+7.2f} "
          f"{r['dir_acc']['mean']:>9.4f} {r['rank_ic']['n']:>5d}")
print('=' * 74)
print(f"done {time.time()-t0:.1f}s")
