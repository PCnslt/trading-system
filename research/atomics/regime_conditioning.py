"""
Market-state conditioning test: does cross-sectional momentum (past 30m return)
predict next-30m return differently across market regimes?

Regimes (all computed at time t from lagged/causal data only):
  (a) market realized vol  : trailing 60-min realized vol of equal-weight index (median split)
  (b) market direction     : equal-weight mean past-30m return across symbols (terciles)
  (c) cross-sectional dispersion : std across symbols of past-30m return (median split)

Signal (t): past 30m return = close(t)/close(t-6) - 1, within-day only.
Forward (t): next 30m return = close(t+6)/close(t) - 1, within-day only.

Report mean next-30m return of top-minus-bottom momentum quintile within each regime.
Research-only. No trading, no data purchase.
"""
import io
import json
import numpy as np
import pandas as pd
import boto3
import pyarrow.parquet as pq
from scipy.stats import rankdata

BUCKET = "trading-datalake-920641308584"
PREFIX = "ibkr/equities/5min/"
SYMBOLS = [
    "AAPL","MSFT","NVDA","JNJ","KO","XOM","TSLA","META","AMZN","GOOGL",
    "AMD","PLTR","LLY","UNH","V","MA","JPM","WMT","PG","HD",
    "DIS","BA","GE","NFLX","COST","CRM","CSCO","INTC","MU","QCOM",
    "TMO","TXN","AVGO","ORCL","PEP","MCD","NKE","ACN","ABT","ADBE",
]
MIN_STOCKS = 25          # require >= this many valid signals to form cross-section
N_QUINTILES = 5
BAR_LOOKBACK = 6          # 30 min = 6 x 5min bars
VOL_WINDOW = 12           # trailing 60 min realized-vol window (12 x 5min bars)

s3 = boto3.client("s3")

# ---- load ---------------------------------------------------------------
dfs = []
for s in SYMBOLS:
    buf = io.BytesIO(s3.get_object(Bucket=BUCKET, Key=PREFIX + s + ".parquet")["Body"].read())
    d = pq.read_table(buf).to_pandas()
    d = d[["date", "close"]].rename(columns={"close": s})
    dfs.append(d.set_index("date"))

panel = pd.concat(dfs, axis=1).sort_index()
panel = panel[~panel.index.duplicated(keep="first")]
# keep only RTH 5-min timestamps (bars already RTH; drop any non-market rows defensively)
day = pd.Series(panel.index.normalize(), index=panel.index)

# ---- within-day 30m returns --------------------------------------------
def within_day_shift(df, k):
    """shift by k rows but NaN where the shift crosses a day boundary."""
    out = df.shift(k)
    same = day.shift(k) == day          # boolean Series, aligned by index
    return out.where(same, axis=0)

close_prev = within_day_shift(panel, BAR_LOOKBACK)
signal = panel / close_prev - 1.0          # past 30m return

close_next = within_day_shift(panel, -BAR_LOOKBACK)
forward = close_next / panel - 1.0         # next 30m return

# ---- market state (causal, time t) --------------------------------------
market_return = signal.mean(axis=1, skipna=True)            # equal-weight mean past-30m return
dispersion = signal.std(axis=1, skipna=True)                # cross-sectional std of past-30m return

# equal-weight index 1-bar (5-min) return -> realized vol
r_1bar = panel.pct_change()                                 # close(t)/close(t-1)-1
r_1bar = r_1bar.where(day.shift(1) == day, axis=0)          # within-day only
market_ret_1bar = r_1bar.mean(axis=1, skipna=True)
# realized vol reset per trading day (avoid smearing overnight gap into trailing window)
realized_vol = market_ret_1bar.groupby(day).transform(
    lambda x: x.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std()
)

# ---- per-timestamp momentum quintile spread ----------------------------
sig = signal.to_numpy(float)      # T x N
fwd = forward.to_numpy(float)

spreads = []      # per-t dict of spread + regime membership + quintile means
T = sig.shape[0]
for t in range(T):
    s = sig[t]
    f = fwd[t]
    valid = ~np.isnan(s) & ~np.isnan(f)
    n_valid = int(valid.sum())
    if n_valid < MIN_STOCKS:
        continue
    sv = s[valid]
    fv = f[valid]
    rk = rankdata(sv, method="average")
    q = np.floor((rk - 1.0) * N_QUINTILES / n_valid).astype(int) + 1  # 1..5
    q = np.clip(q, 1, N_QUINTILES)
    q1_mean = float(fv[q == 1].mean())
    q5_mean = float(fv[q == N_QUINTILES].mean())
    spreads.append({
        "t": t,
        "spread": q5_mean - q1_mean,
        "q1_mean": q1_mean,
        "q5_mean": q5_mean,
        "n_stocks": n_valid,
        "market_return": float(market_return.iloc[t]),
        "dispersion": float(dispersion.iloc[t]),
        "realized_vol": float(realized_vol.iloc[t]) if not np.isnan(realized_vol.iloc[t]) else None,
    })

S = pd.DataFrame(spreads)
S = S.dropna(subset=["realized_vol"])   # realized vol needs warm-up window
S = S.reset_index(drop=True)

# ---- regime splits ------------------------------------------------------
def summarize(sub):
    if len(sub) == 0:
        return {"mean_spread": None, "n": 0}
    m = float(sub["spread"].mean())
    sd = float(sub["spread"].std(ddof=1)) if len(sub) > 1 else float("nan")
    se = sd / np.sqrt(len(sub)) if len(sub) > 1 else float("nan")
    tstat = m / se if se and not np.isnan(se) else float("nan")
    return {
        "mean_spread": m,
        "n": int(len(sub)),
        "std_spread": sd,
        "t_stat": tstat,
        "q1_mean": float(sub["q1_mean"].mean()),
        "q5_mean": float(sub["q5_mean"].mean()),
    }

results = {"regimes": {}}

# (a) realized vol
vol_med = float(S["realized_vol"].median())
hi = S[S["realized_vol"] >= vol_med]
lo = S[S["realized_vol"] < vol_med]
results["regimes"]["market_realized_vol"] = {
    "definition": f"trailing {VOL_WINDOW*5}-min realized vol of equal-weight index (std of 5-min returns)",
    "median_threshold": vol_med,
    "high": summarize(hi),
    "low": summarize(lo),
}

# (b) direction terciles
mr = S["market_return"]
q_lo, q_hi = float(mr.quantile(1 / 3)), float(mr.quantile(2 / 3))
results["regimes"]["market_direction"] = {
    "definition": "equal-weight mean past-30m return across symbols; terciles",
    "thresholds": {"down_below": q_lo, "up_above": q_hi},
    "down": summarize(S[mr <= q_lo]),
    "flat": summarize(S[(mr > q_lo) & (mr <= q_hi)]),
    "up": summarize(S[mr > q_hi]),
}

# (c) dispersion
disp_med = float(S["dispersion"].median())
results["regimes"]["cross_sectional_dispersion"] = {
    "definition": "std across symbols of past-30m return (cross-sectional dispersion of momentum signal)",
    "median_threshold": disp_med,
    "high": summarize(S[S["dispersion"] >= disp_med]),
    "low": summarize(S[S["dispersion"] < disp_med]),
}

results["unconditional"] = summarize(S)
results["method"] = {
    "signal": "past 30m return = close(t)/close(t-6)-1, within-day",
    "forward": "next 30m return = close(t+6)/close(t)-1, within-day",
    "cross_sectional_momentum": "rank stocks by signal into 5 quintiles at t; spread = mean(next-30m of Q5) - mean(next-30m of Q1)",
    "regime_split": "computed on lagged (causal) market state at time t, before forward window",
    "min_stocks_per_cross_section": MIN_STOCKS,
    "n_quintiles": N_QUINTILES,
    "significance_note": "t_stat = mean/std_of_timepoint_spread (timepoints treated as iid; autocorrelation inflates |t|)",
}
results["data"] = {
    "bucket": BUCKET,
    "prefix": PREFIX,
    "n_symbols": len(SYMBOLS),
    "date_range": [str(panel.index.min()), str(panel.index.max())],
    "n_trading_days": int(day.nunique()),
    "n_timepoints_analyzed": int(len(S)),
    "n_total_5min_bars": int(len(panel)),
}

out = "/home/ubuntu/trading-system/research/atomics/regime_condition_results.json"
with open(out, "w") as fh:
    json.dump(results, fh, indent=2)

print(json.dumps(results, indent=2))
