#!/usr/bin/env python3
"""Chronos-tiny zero-shot foundation-model benchmark vs Ridge/LightGBM baseline.

Cross-sectional setup on 40 liquid equities, 5-min bars (S3 trading-datalake).
For each symbol, context = last 64 closes; forecast next 6 bars (30m).
Report per-timestamp rank IC (Spearman across the 40-symbol cross-section)
and directional accuracy (sign agreement), aggregated over the chronological
test period. Baselines (Ridge, LightGBM) trained on the first 70% of timestamps.

Research only — no orders.
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

CTX = 64            # context bars (5-min)
HORIZON = 6         # forecast horizon (30m)
NUM_SAMPLES = 20    # Chronos samples for median point forecast
SPLIT = 0.7         # chronological train/test split
STEP = 6            # evaluate every 6th bar (non-overlapping 30m targets)

# ---------------------------------------------------------------------------
# load + align
# ---------------------------------------------------------------------------
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
print(f"[load] {n_s} symbols x {n_t} aligned 5-min bars  ({time.time()-t0:.1f}s)", flush=True)

# ---------------------------------------------------------------------------
# wide features (PIT-safe: past bars only)
# ---------------------------------------------------------------------------
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

# flatten into long table (timestamp x symbol) for baseline training
long_parts = []
for n in FEAT_COLS:
    long_parts.append(F[n].stack().rename(n))
long_df = pd.concat(long_parts, axis=1)
long_df['target'] = target.stack()
long_df = long_df.dropna(subset=FEAT_COLS + ['target'])

# chronological split on timestamps
all_dates = sorted(long_df.index.get_level_values(0).unique())
cut = all_dates[int(len(all_dates) * SPLIT)]
tr = long_df[long_df.index.get_level_values(0) < cut]
te = long_df[long_df.index.get_level_values(0) >= cut]
print(f"[split] train {len(tr)} rows, test {len(te)} rows  ({time.time()-t0:.1f}s)", flush=True)

# ---------------------------------------------------------------------------
# baselines (Ridge + LightGBM), trained on train period only
# ---------------------------------------------------------------------------
Xtr, ytr = tr[FEAT_COLS].values, tr['target'].values
Xte, yte = te[FEAT_COLS].values, te['target'].values

ridge = Ridge(alpha=1.0)
ridge.fit(Xtr, ytr)
ridge_pred = ridge.predict(Xte)

lgbm = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=31,
                         subsample=0.8, colsample_bytree=0.8, n_jobs=2,
                         verbose=-1, random_state=0)
lgbm.fit(Xtr, ytr)
lgbm_pred = lgbm.predict(Xte)
print(f"[baselines] trained  ({time.time()-t0:.1f}s)", flush=True)

# map flattened test predictions back to (timestamp, symbol)
te_idx = te.index  # MultiIndex
ridge_wide = pd.Series(ridge_pred, index=te_idx).unstack()
lgbm_wide = pd.Series(lgbm_pred, index=te_idx).unstack()

# ---------------------------------------------------------------------------
# Chronos zero-shot
# ---------------------------------------------------------------------------
chronos_err = None
pipe = None
try:
    import torch
    from chronos import ChronosPipeline
    pipe = ChronosPipeline.from_pretrained('amazon/chronos-t5-tiny',
                                           device_map='cpu', torch_dtype=torch.float32)
    print(f"[chronos] pipeline loaded  ({time.time()-t0:.1f}s)", flush=True)
except Exception as e:
    chronos_err = f"{type(e).__name__}: {str(e)[:300]}"
    print(f"[chronos] LOAD FAILED: {chronos_err}", flush=True)


def chronos_pred_returns(pipe, ctx_df):
    """ctx_df: (n_ctx, n_sym) DataFrame of closes -> np array of predicted 30m returns."""
    n_ctx, n_s = ctx_df.shape
    last = ctx_df.iloc[-1, :].values.astype('float64')      # last close per symbol
    ctx_arrs = []
    scales = []
    for s in range(n_s):
        x = ctx_df.iloc[:, s].values.astype('float32')
        sc = float(np.mean(np.abs(x))) or 1.0
        ctx_arrs.append(x / sc)
        scales.append(sc)
    tensors = [torch.tensor(x, dtype=torch.float32) for x in ctx_arrs]
    with torch.no_grad():
        fc = pipe.predict(tensors, prediction_length=HORIZON, num_samples=NUM_SAMPLES)
    med = fc[:, :, HORIZON - 1].median(dim=1).values.numpy()   # (n_sym,) level at +6 bars
    levels = med * np.array(scales, dtype='float64')
    return (levels - last) / last


# ---- evaluation grid: sampled test timestamps (by position in aligned close) ----
n_test_start = int(n_t * SPLIT)
positions = list(range(n_test_start, n_t - HORIZON, STEP))
print(f"[eval] {len(positions)} sampled test timestamps  ({time.time()-t0:.1f}s)", flush=True)

# results accumulators
def rank_ic_vec(pred, y):
    m = ~(np.isnan(pred) | np.isnan(y))
    if m.sum() < 10:
        return np.nan
    return spearmanr(pred[m], y[m]).statistic


def dir_acc_vec(pred, y):
    m = ~(np.isnan(pred) | np.isnan(y))
    return np.mean(np.sign(pred[m]) == np.sign(y[m]))


models = {k: {'rank_ic': [], 'dir_acc': []} for k in
          ['chronos_tiny', 'ridge', 'lightgbm', 'momentum_r30', 'reversal_r30']}

chronos_skipped = 0
for p in positions:
    ts = close.index[p]
    # realized next-30m return across symbols
    actual = target.iloc[p, :].values  # (n_sym,)

    # baseline + reference predictions at timestamp ts
    rr = r30.iloc[p, :].values
    rv = -rr
    rg = ridge_wide.loc[ts].reindex(close.columns).values if ts in ridge_wide.index else np.full(n_s, np.nan)
    lg = lgbm_wide.loc[ts].reindex(close.columns).values if ts in lgbm_wide.index else np.full(n_s, np.nan)

    # chronos
    cp = np.full(n_s, np.nan)
    if pipe is not None:
        ctx_df = close.iloc[p - CTX:p, :]
        try:
            cp = chronos_pred_returns(pipe, ctx_df)
        except Exception as e:
            if chronos_skipped == 0:
                print(f"[chronos] predict failed at {ts}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            chronos_skipped += 1
            cp = np.full(n_s, np.nan)

    for name, pred in [('chronos_tiny', cp), ('ridge', rg), ('lightgbm', lg),
                       ('momentum_r30', rr), ('reversal_r30', rv)]:
        models[name]['rank_ic'].append(rank_ic_vec(pred, actual))
        models[name]['dir_acc'].append(dir_acc_vec(pred, actual))

# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------
def agg(v):
    v = np.array([x for x in v if not np.isnan(x)], dtype=float)
    return {
        'n': int(len(v)),
        'mean': float(np.mean(v)) if len(v) else np.nan,
        'std': float(np.std(v)) if len(v) else np.nan,
        't_stat': float(np.mean(v) / (np.std(v) / np.sqrt(len(v)))) if len(v) > 1 else np.nan,
        'median': float(np.median(v)) if len(v) else np.nan,
    }

summary = {}
for name in models:
    summary[name] = {
        'rank_ic': agg(models[name]['rank_ic']),
        'dir_acc': agg(models[name]['dir_acc']),
    }

result = {
    'experiment': 'chronos_tiny_zero_shot_vs_baseline',
    'config': {
        'universe': 'ibkr/equities/5min', 'n_symbols': n_s, 'symbols': syms,
        'context_bars': CTX, 'horizon_bars': HORIZON, 'horizon_label': '30m',
        'num_samples': NUM_SAMPLES, 'split': SPLIT, 'eval_step_bars': STEP,
        'chronos_model': 'amazon/chronos-t5-tiny',
        'n_train_rows': int(len(tr)), 'n_test_rows': int(len(te)),
        'n_eval_timestamps': len(positions),
        'train_range': [str(all_dates[0]), str(cut)],
        'test_range': [str(cut), str(all_dates[-1])],
    },
    'chronos_skipped_timestamps': chronos_skipped,
    'chronos_error': chronos_err,
    'results': summary,
}

out_path = 'research/atomics/chronos_benchmark.json'
with open(out_path, 'w') as f:
    json.dump(result, f, indent=2, default=str)

print('\n' + '=' * 78)
print('CHRONOS-TINY ZERO-SHOT vs BASELINE  (30m forward return, 40-symbol cross-section)')
print('=' * 78)
hdr = f"{'model':16s} {'rank_IC':>9s} {'t-stat':>7s} {'dir_acc':>9s} {'n':>5s}"
print(hdr)
for name in ['chronos_tiny', 'ridge', 'lightgbm', 'momentum_r30', 'reversal_r30']:
    r = summary[name]
    print(f"{name:16s} {r['rank_ic']['mean']:>+9.4f} {r['rank_ic']['t_stat']:>+7.2f} "
          f"{r['dir_acc']['mean']:>9.4f} {r['rank_ic']['n']:>5d}")
print('=' * 78)
print(f"wrote {out_path}  ({time.time()-t0:.1f}s total)", flush=True)
