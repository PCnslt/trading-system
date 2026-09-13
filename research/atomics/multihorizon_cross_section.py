"""Multi-horizon cross-sectional return-predictability test.

Signals:
  - momentum r6   : 6-bar (30-min) past return, close.pct_change(6)
  - reversal -r6  : negative of that momentum
  - LightGBM      : gradient boosting on the 11 FLAT (per-symbol, causal) features
                    used in ml_cross_section.py -- r5,r15,r30,r60,rsi,macd,
                    vwap_dist,vr,rv,atr,hour.  No cross-sectional rank features,
                    so the model must learn cross-sectional ordering itself.

Horizons (forward return in bp): 5m / 15m / 30m / 60m / 120m / end-of-day.
  end-of-day = same-day close-to-close (return from bar t to that day's final bar).

Evaluation (cross-sectional, per timestamp):
  - rank IC = Spearman(signal, forward return) across the ~40 names at each
    timestamp, averaged over timestamps (mean + median + t-stat).
  - top-decile excess (bp) = mean return of the top-decile names minus the
    cross-sectional mean return, averaged over timestamps, x1e4.

Chronological 70/30 split by unique timestamp; LightGBM trains on train,
predicts on test; momentum/reversal are parameter-free and evaluated on the
same test period for a like-for-like comparison.  The final (partial) trading
day is dropped because intraday data ends mid-session.

Research-only.  No trading, no data purchase.
"""
from __future__ import annotations
import boto3, io, json, os, sys
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.stats import spearmanr
from datetime import datetime, timezone

BUCKET = "trading-datalake-920641308584"
PREFIX = "ibkr/equities/5min/"
REGION = "us-east-1"
OUT = "/home/ubuntu/trading-system/research/atomics/multihorizon_results.json"

# ---- 11 flat features (identical to ml_cross_section.py, minus cs ranks) ----
FEAT_COLS = ['r5', 'r15', 'r30', 'r60', 'rsi', 'macd', 'vwap_dist', 'vr', 'rv', 'atr', 'hour']

HORIZONS = [('5m', 1), ('15m', 3), ('30m', 6), ('60m', 12), ('120m', 24), ('eod', None)]


def discover(s3):
    r = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX, MaxKeys=300)
    return sorted(o['Key'].split('/')[-1].split('.parquet')[0]
                  for o in r.get('Contents', []) if o['Key'].endswith('.parquet'))


def load5(s3, sym):
    d = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=f'{PREFIX}{sym}.parquet')['Body'].read()))
    d['date'] = pd.to_datetime(d['date'])
    d = d.set_index('date').sort_index()
    d.index = d.index.tz_localize(None)
    return d


def build_symbol_frame(d: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol flat feature frame + all forward targets. Strictly causal."""
    c, v = d['close'], d['volume']
    f = pd.DataFrame(index=d.index)
    f['r5'] = c.pct_change()
    f['r15'] = c.pct_change(3)
    f['r30'] = c.pct_change(6)          # <-- this IS "r6" momentum (6 bars)
    f['r60'] = c.pct_change(12)
    delta = c.diff(); up = delta.clip(lower=0); dn = -delta.clip(upper=0)
    f['rsi'] = 100 - 100 / (1 + up.rolling(14).mean() / dn.rolling(14).mean())
    ema12 = c.ewm(span=12).mean(); ema26 = c.ewm(span=26).mean()
    f['macd'] = (ema12 - ema26) / c
    vwap = (c * v).rolling(30).sum() / v.rolling(30).sum()
    f['vwap_dist'] = (c - vwap) / vwap
    f['vr'] = v / v.rolling(30).median()
    f['rv'] = f['r5'].rolling(20).std()
    f['atr'] = (d['high'] - d['low']).rolling(14).mean() / c
    f['hour'] = d.index.hour + d.index.minute / 60.0

    # fixed-bar forward targets
    f['t_5m'] = c.shift(-1) / c - 1.0
    f['t_15m'] = c.shift(-3) / c - 1.0
    f['t_30m'] = c.shift(-6) / c - 1.0
    f['t_60m'] = c.shift(-12) / c - 1.0
    f['t_120m'] = c.shift(-24) / c - 1.0

    # end-of-day: return from bar t to the FINAL bar of the same day
    day = pd.Series(d.index).dt.date.values
    f['_day'] = day
    last_close = c.groupby(day).transform('last')
    f['t_eod'] = last_close / c - 1.0
    # the last bar of each day has zero horizon -> exclude from eod target
    is_last = c.groupby(day).transform(lambda s: np.arange(len(s)) == len(s) - 1)
    f.loc[is_last.astype(bool), 't_eod'] = np.nan
    return f


def cross_sectional_ic(sig, y, ts):
    """Per-timestamp Spearman rank IC -> Series indexed by timestamp."""
    g = pd.DataFrame({'sig': sig, 'y': y, 't': ts}).dropna()
    def f(x):
        if len(x) < 10:
            return np.nan
        return spearmanr(x['sig'], x['y']).statistic
    return g.groupby('t').apply(f).dropna()


def cross_sectional_top_decile(sig, y, ts):
    """Per-timestamp top-decile mean minus cross-sectional mean (returns, not bp)."""
    g = pd.DataFrame({'sig': sig, 'y': y, 't': ts}).dropna()
    def f(x):
        if len(x) < 10:
            return np.nan
        th = x['sig'].quantile(0.9)
        return x.loc[x['sig'] >= th, 'y'].mean() - x['y'].mean()
    return g.groupby('t').apply(f).dropna()


def summarize(ic_series, tdr_series):
    ic = ic_series.values
    tdr = tdr_series.values
    n = len(ic)
    return {
        'rank_ic_mean': float(np.mean(ic)) if n else np.nan,
        'rank_ic_median': float(np.median(ic)) if n else np.nan,
        'rank_ic_tstat': float(np.mean(ic) / (np.std(ic) / np.sqrt(n))) if n > 1 else np.nan,
        'top_decile_excess_bp': float(np.mean(tdr) * 1e4) if len(tdr) else np.nan,
        'top_decile_excess_median_bp': float(np.median(tdr) * 1e4) if len(tdr) else np.nan,
        'n_timestamps': int(n),
    }


def pooled_ic(sig, y):
    m = ~(np.isnan(sig) | np.isnan(y))
    if m.sum() < 10:
        return np.nan
    return float(spearmanr(sig[m], y[m]).statistic)


def main():
    s3 = boto3.client('s3', region_name=REGION)
    syms = discover(s3)
    print(f"[multihorizon] {len(syms)} symbols discovered")

    frames = []
    for s in syms:
        d = load5(s3, s)
        f = build_symbol_frame(d)
        f['sym'] = s
        frames.append(f)
    df = pd.concat(frames).sort_index()
    df = df.replace([np.inf, -np.inf], np.nan)

    # drop final (partial) trading day -- intraday data ends mid-session
    days = sorted(pd.Series(df.index).dt.date.unique())
    last_day = days[-1]
    df = df[pd.Series(df.index).dt.date.values < last_day]
    print(f"[multihorizon] data range {df.index.min()} .. {df.index.max()} "
          f"(dropped partial final day {last_day})")
    print(f"[multihorizon] rows={len(df)} symbols={df['sym'].nunique()} days={len(days)-1}")

    # chronological 70/30 split by unique timestamp
    times = np.sort(df.index.unique())
    cut = times[int(len(times) * 0.7)]
    is_test = df.index >= cut
    print(f"[multihorizon] split at {cut}: train={int((~is_test).sum())} test={int(is_test.sum())} rows")

    results = []
    for hname, hbars in HORIZONS:
        tcol = f't_{hname}'
        y = df[tcol].to_numpy()
        # signals (momentum / reversal are parameter-free, causal)
        r6 = df['r30'].to_numpy()      # 6-bar momentum
        sig_mom = r6
        sig_rev = -r6

        # subset to rows where target + features + signal are all valid
        feat_ok = df[FEAT_COLS].notna().all(axis=1).to_numpy()
        valid = feat_ok & ~np.isnan(y) & ~np.isnan(r6)

        # LightGBM train/test
        Xtr = df.loc[valid & ~is_test, FEAT_COLS].to_numpy()
        ytr = y[valid & ~is_test]
        Xte = df.loc[valid & is_test, FEAT_COLS].to_numpy()
        yte = y[valid & is_test]
        model = lgb.LGBMRegressor(
            n_estimators=200, learning_rate=0.05, num_leaves=31,
            subsample=0.8, colsample_bytree=0.8, n_jobs=2, verbose=-1, random_state=0)
        model.fit(Xtr, ytr)
        pred = model.predict(Xte)
        pred_full = np.full(len(df), np.nan)
        pred_full[valid & is_test] = pred

        # evaluate on TEST period only (like-for-like across all 3 signals)
        ts = pd.Series(df.index).to_numpy()
        m = valid & is_test
        res = {
            'horizon': hname,
            'horizon_bars': hbars if hbars is not None else 'to_close',
            'n_test_rows': int(m.sum()),
            'momentum_r6': summarize(cross_sectional_ic(sig_mom[m], y[m], ts[m]),
                                     cross_sectional_top_decile(sig_mom[m], y[m], ts[m])),
            'reversal_r6': summarize(cross_sectional_ic(sig_rev[m], y[m], ts[m]),
                                     cross_sectional_top_decile(sig_rev[m], y[m], ts[m])),
            'lightgbm': summarize(cross_sectional_ic(pred_full[m], y[m], ts[m]),
                                  cross_sectional_top_decile(pred_full[m], y[m], ts[m])),
        }
        # pooled IC for comparability with ml_cross_section.py
        res['momentum_r6']['pooled_rank_ic'] = pooled_ic(sig_mom[m], y[m])
        res['reversal_r6']['pooled_rank_ic'] = pooled_ic(sig_rev[m], y[m])
        res['lightgbm']['pooled_rank_ic'] = pooled_ic(pred_full[m], y[m])

        # feature importance for the LGBM at this horizon
        imp = pd.Series(model.feature_importances_, index=FEAT_COLS).sort_values(ascending=False)
        res['lightgbm']['feature_importance_top5'] = {k: round(float(v), 3) for k, v in imp.head(5).items()}

        results.append(res)
        print(f"[{hname:>4}] mom IC={res['momentum_r6']['rank_ic_mean']:+.4f} "
              f"rev IC={res['reversal_r6']['rank_ic_mean']:+.4f} "
              f"lgbm IC={res['lightgbm']['rank_ic_mean']:+.4f} | "
              f"td excess(mom)={res['momentum_r6']['top_decile_excess_bp']:+.2f}bp "
              f"(rev)={res['reversal_r6']['top_decile_excess_bp']:+.2f}bp "
              f"(lgbm)={res['lightgbm']['top_decile_excess_bp']:+.2f}bp")

    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'methodology': {
            'feature_set': FEAT_COLS,
            'feature_set_note': '11 flat (per-symbol, causal) features from ml_cross_section.py; no cross-sectional rank features',
            'momentum_signal': 'r6 = close.pct_change(6) = 6-bar (30-min) past return',
            'reversal_signal': '-r6',
            'lightgbm': 'LGBMRegressor(200 trees, lr=0.05, leaves=31, subsample/colsample=0.8), trained per horizon on 70% train, scored on 30% test',
            'horizons': {'5m': 1, '15m': 3, '30m': 6, '60m': 12, '120m': 24, 'eod': 'return to same-day final bar'},
            'split': 'chronological 70/30 by unique timestamp',
            'evaluation': 'cross-sectional per timestamp; rank IC = Spearman across ~40 names per timestamp (mean/median/t-stat); top-decile excess = top-10% mean minus cross-sectional mean (bp)',
            'dropped': 'final partial trading day (data ends mid-session)',
        },
        'n_symbols': len(syms),
        'symbols': syms,
        'data_range': [str(df.index.min()), str(df.index.max())],
        'split_threshold': str(cut),
        'results': results,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as fh:
        json.dump(payload, fh, indent=2)
    print(f"\n[done] wrote {OUT}")


if __name__ == '__main__':
    main()
