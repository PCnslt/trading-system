#!/usr/bin/env python3
"""Reduced Chronos-tiny sweep + baselines on a common evaluation grid.

The full 649-timestamp sweep is too slow on CPU (~3s/40-symbol batch). This
salvages a REAL zero-shot Chronos number on a sparser grid (2-hour spacing,
~160 timestamps, num_samples=8), with Ridge/LightGBM/momentum/reversal evaluated
on the SAME grid for an apples-to-apples rank IC / directional-accuracy report.
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

CTX = 64
HORIZON = 6
NUM_SAMPLES = 8
SPLIT = 0.7
STEP = 24          # evaluate every 24 bars (2h) -> ~160 timestamps

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
ridge_wide = pd.Series(ridge_pred, index=te.index).unstack()
lgbm_wide = pd.Series(lgbm_pred, index=te.index).unstack()

# ---- Chronos ----
chronos_err = None
pipe = None
try:
    import torch
    from chronos import ChronosPipeline
    pipe = ChronosPipeline.from_pretrained('amazon/chronos-t5-tiny',
                                           device_map='cpu', torch_dtype=torch.float32)
    print(f"[chronos] loaded ({time.time()-t0:.1f}s)", flush=True)
except Exception as e:
    chronos_err = f"{type(e).__name__}: {str(e)[:300]}"
    print(f"[chronos] LOAD FAILED: {chronos_err}", flush=True)

close_np = close.to_numpy(dtype='float64')  # (n_t, n_s) for fast context slicing

def chronos_returns(pipe, ctx):
    """ctx: (CTX, n_s) float64 array -> (n_s,) predicted 30m returns."""
    last = ctx[-1, :]
    ctx_arrs = []
    scales = []
    for s in range(n_s):
        x = ctx[:, s].astype('float32')
        sc = float(np.mean(np.abs(x))) or 1.0
        ctx_arrs.append(x / sc)
        scales.append(sc)
    tensors = [torch.tensor(x, dtype=torch.float32) for x in ctx_arrs]
    with torch.no_grad():
        fc = pipe.predict(tensors, prediction_length=HORIZON, num_samples=NUM_SAMPLES)
    med = fc[:, :, HORIZON - 1].median(dim=1).values.numpy()
    levels = med * np.array(scales, dtype='float64')
    return (levels - last) / last

n_test_start = int(n_t * SPLIT)
positions = list(range(n_test_start, n_t - HORIZON, STEP))
print(f"[eval] {len(positions)} timestamps", flush=True)

def rank_ic_vec(pred, y):
    m = ~(np.isnan(pred) | np.isnan(y))
    if m.sum() < 10:
        return np.nan
    return spearmanr(pred[m], y[m]).statistic

def dir_acc_vec(pred, y):
    m = ~(np.isnan(pred) | np.isnan(y))
    return np.mean(np.sign(pred[m]) == np.sign(y[m]))

res = {k: {'rank_ic': [], 'dir_acc': []} for k in
       ['chronos_tiny', 'ridge', 'lightgbm', 'momentum_r30', 'reversal_r30']}
skipped = 0
for p in positions:
    ts = close.index[p]
    actual = target.iloc[p, :].values
    rr = r30.iloc[p, :].values
    rg = ridge_wide.loc[ts].reindex(close.columns).values if ts in ridge_wide.index else np.full(n_s, np.nan)
    lg = lgbm_wide.loc[ts].reindex(close.columns).values if ts in lgbm_wide.index else np.full(n_s, np.nan)
    cp = np.full(n_s, np.nan)
    if pipe is not None:
        ctx = close_np[p - CTX:p, :]
        try:
            cp = chronos_returns(pipe, ctx)
        except Exception as e:
            if skipped == 0:
                print(f"[chronos] fail at {ts}: {type(e).__name__}: {str(e)[:150]}", flush=True)
            skipped += 1
    for name, pred in [('chronos_tiny', cp), ('ridge', rg), ('lightgbm', lg),
                       ('momentum_r30', rr), ('reversal_r30', -rr)]:
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
    'experiment': 'chronos_tiny_zero_shot_vs_baseline_reduced',
    'note': 'reduced eval grid (2h spacing) after full sweep aborted on CPU time',
    'config': {
        'universe': 'ibkr/equities/5min', 'n_symbols': n_s, 'symbols': syms,
        'context_bars': CTX, 'horizon_bars': HORIZON, 'horizon_label': '30m',
        'num_samples': NUM_SAMPLES, 'split': SPLIT, 'eval_step_bars': STEP,
        'chronos_model': 'amazon/chronos-t5-tiny', 'device': 'cpu',
        'n_train_rows': int(len(tr)), 'n_test_rows': int(len(te)),
        'n_eval_timestamps': len(positions),
        'train_range': [str(all_dates[0]), str(cut)], 'test_range': [str(cut), str(all_dates[-1])],
    },
    'chronos_skipped_timestamps': skipped,
    'chronos_error': chronos_err,
    'results': summary,
}
with open('research/atomics/chronos_benchmark.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)

print('=' * 74)
print('CHRONOS-TINY (zero-shot) vs BASELINES  — 30m return, 40-symbol cross-section')
print(f'(reduced grid: {len(positions)} timestamps, num_samples={NUM_SAMPLES})')
print('=' * 74)
print(f"{'model':16s} {'rank_IC':>9s} {'t-stat':>7s} {'dir_acc':>9s} {'n':>5s}")
for name in ['chronos_tiny', 'ridge', 'lightgbm', 'momentum_r30', 'reversal_r30']:
    r = summary[name]
    print(f"{name:16s} {r['rank_ic']['mean']:>+9.4f} {r['rank_ic']['t_stat']:>+7.2f} "
          f"{r['dir_acc']['mean']:>9.4f} {r['rank_ic']['n']:>5d}")
print('=' * 74)
print(f"wrote research/atomics/chronos_benchmark.json  ({time.time()-t0:.1f}s)", flush=True)
