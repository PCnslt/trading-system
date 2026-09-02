"""Core cross-sectional ML experiment (Phase 2-5).

Builds a causal feature matrix across all symbols, then tests whether LightGBM
predicts next-30m cross-sectional ranking better than momentum/reversal
baselines, with strict chronological train/test split.
"""
import boto3, io, pandas as pd, numpy as np
import lightgbm as lgb
from scipy.stats import spearmanr

s3 = boto3.client('s3', region_name='us-east-1'); B = 'trading-datalake-920641308584'
P5 = 'ibkr/equities/5min/'
def discover():
    r = s3.list_objects_v2(Bucket=B, Prefix=P5)
    return sorted(o['Key'].split('/')[-1].replace('.parquet','') for o in r.get('Contents',[]))
SYMS = discover()

def load5(sym):
    d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=B, Key=f'{P5}{sym}.parquet')['Body'].read()))
    d['date'] = pd.to_datetime(d['date']); d = d.set_index('date').sort_index()
    d.index = d.index.tz_localize(None); return d

# ---- build per-symbol feature frames ----
FEATS = {}
for s in SYMS:
    d = load5(s)
    c, v = d['close'], d['volume']
    f = pd.DataFrame(index=d.index)
    f['r5'] = c.pct_change()
    f['r15'] = c.pct_change(3)
    f['r30'] = c.pct_change(6)
    f['r60'] = c.pct_change(12)
    delta = c.diff(); up = delta.clip(lower=0); dn = -delta.clip(upper=0)
    f['rsi'] = 100 - 100/(1 + up.rolling(14).mean()/dn.rolling(14).mean())
    ema12 = c.ewm(span=12).mean(); ema26 = c.ewm(span=26).mean()
    f['macd'] = (ema12-ema26)/c
    vwap = (c*v).rolling(30).sum()/v.rolling(30).sum()
    f['vwap_dist'] = (c-vwap)/vwap
    f['vr'] = v/v.rolling(30).median()
    f['rv'] = f['r5'].rolling(20).std()
    f['atr'] = (d['high']-d['low']).rolling(14).mean()/c
    f['hour'] = d.index.hour + d.index.minute/60
    f['target'] = c.shift(-6)/c - 1  # next ~30m return
    FEATS[s] = f

# ---- assemble long table ----
L = []
for s, f in FEATS.items():
    g = f.copy(); g['sym'] = s; L.append(g)
df = pd.concat(L)
# cross-sectional ranks (per timestamp)
df['cs_rank_r30'] = df.groupby(df.index)['r30'].rank(pct=True)
df['cs_rank_vr'] = df.groupby(df.index)['vr'].rank(pct=True)
df = df.dropna(subset=['target'])
FEAT_COLS = ['r5','r15','r30','r60','rsi','macd','vwap_dist','vr','rv','atr','hour','cs_rank_r30','cs_rank_vr']

# ---- chronological split (walk-forward, one fold for first pass) ----
dates = sorted(df.index.unique())
cut = dates[int(len(dates)*0.7)]
tr = df[df.index < cut]; te = df[df.index >= cut]
print(f"train rows {len(tr)} ({tr.index.min().date()}..{tr.index.max().date()}), test rows {len(te)} ({te.index.min().date()}..{te.index.max().date()})")

def rank_ic(pred, y):
    return spearmanr(pred, y).statistic

def top_decile_ret(pred, y):
    q = pd.Series(pred).rank(pct=True)
    return y[q >= 0.9].mean() - y.mean()  # top decile minus cross-sectional mean

# baselines on TEST
for name, sig in [('momentum (r30)', te['r30']), ('reversal (-r30)', -te['r30']),
                  ('r60', te['r60']), ('cs_rank_r30', te['cs_rank_r30'])]:
    print(f"baseline {name:20s}: rank_IC={rank_ic(sig.values, te['target'].values):+.4f}, top-decile excess={top_decile_ret(sig.values, te['target'].values)*1e4:+.2f}bp")

# LightGBM
Xtr, ytr = tr[FEAT_COLS].values, tr['target'].values
Xte, yte = te[FEAT_COLS].values, te['target'].values
model = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=31,
                          subsample=0.8, colsample_bytree=0.8, n_jobs=2, verbose=-1,
                          random_state=0)
model.fit(Xtr, ytr)
pred = model.predict(Xte)
ic = rank_ic(pred, yte); tdr = top_decile_ret(pred, yte)
hi = yte[pred >= np.quantile(pred, 0.8)].mean()
print(f"\nLightGBM: rank_IC={ic:+.4f}, top-decile excess={tdr*1e4:+.2f}bp, high-conf mean ret={hi*1e4:+.2f}bp")
imp = pd.Series(model.feature_importances_, index=FEAT_COLS).sort_values(ascending=False)
print("feature importance:", dict(imp.round(2).head(8)))
