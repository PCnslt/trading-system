"""RVOL (relative volume) backtest — Gervais-Kaniel-Mingelgrin 2001 "high-volume premium".

Two tests, honest fills:
  1. TIME-SERIES (SPY index, 33y): does a high-volume day (RVOL>=2) predict
     positive forward 1-5d returns vs a low-volume day?
  2. CROSS-SECTIONAL (190-name liquid universe, 20y): rank by RVOL daily,
     top-decile vs bottom-decile equal-weight forward 1-5d spread, net of cost.

No lookahead: signal at close(t) uses volume through t; forward return t->t+H.
"""
import io, json, sys, os
import boto3
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
B = 'trading-datalake-920641308584'
s3 = boto3.client('s3', region_name='us-east-1')

# ---- universe: the RSI2 liquidity universe from live_equities ----
from bot.live_equities import STOCKS, SMALL_CAP_STOCKS  # noqa
UNIVERSE = STOCKS  # 190 liquid names
print(f'universe: {len(UNIVERSE)} names')

# =====================================================================
# TEST 1 — time-series RVOL on SPY (33y)
# =====================================================================
def load_spy():
    d = json.loads(s3.get_object(Bucket=B, Key='yf/etfs/SPY.json')['Body'].read().decode())
    df = pd.DataFrame(d['daily'])
    df['date'] = pd.to_datetime(df['ts']).dt.tz_localize(None)
    return df[['date', 'open', 'close', 'volume']].sort_values('date').reset_index(drop=True)

spy = load_spy()
spy['rvol'] = spy['volume'] / spy['volume'].rolling(20).mean().shift(1)
spy['fwd'] = spy['close'].shift(-1) / spy['close'] - 1
spy['fwd3'] = spy['close'].shift(-3) / spy['close'] - 1
spy['fwd5'] = spy['close'].shift(-5) / spy['close'] - 1

hi = spy[spy['rvol'] >= 2.0]
lo = spy[spy['rvol'] <= 0.7]
print('\n=== TEST 1: SPY time-series RVOL (33y) ===')
print(f'high-vol days (rvol>=2): {len(hi)}   low-vol days (rvol<=0.7): {len(lo)}')
for lbl, sub in [('HIGH', hi), ('LOW', lo)]:
    print(f'  {lbl}: fwd1d {sub["fwd"].mean()*100:+.3f}%  fwd3d {sub["fwd3"].mean()*100:+.3f}%  fwd5d {sub["fwd5"].mean()*100:+.3f}%  (n={len(sub)})')
# baseline all days
print(f'  ALL : fwd1d {spy["fwd"].mean()*100:+.3f}%  fwd3d {spy["fwd3"].mean()*100:+.3f}%  fwd5d {spy["fwd5"].mean()*100:+.3f}%')

# =====================================================================
# TEST 2 — cross-sectional RVOL (190 names, 20y)
# =====================================================================
def load_sym(sym):
    key = f'ibkr/equities/daily/{sym}.parquet'
    try:
        buf = s3.get_object(Bucket=B, Key=key)['Body'].read()
        df = pd.read_parquet(io.BytesIO(buf))
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        df['sym'] = sym
        return df[['date', 'sym', 'close', 'volume']]
    except Exception as e:
        return None

frames = []
missing = 0
for sym in UNIVERSE:
    df = load_sym(sym)
    if df is None or len(df) < 500:
        missing += 1
        continue
    df['rvol'] = df['volume'] / df['volume'].rolling(20).mean().shift(1)
    frames.append(df)
print(f'\n=== TEST 2: cross-sectional RVOL — loaded {len(frames)} names ({missing} missing/short) ===')

allx = pd.concat(frames, ignore_index=True)
allx = allx.dropna(subset=['rvol'])
allx['rvol'] = allx['rvol'].clip(upper=50)  # cap insane rvol from zero-volume days

# daily cross-sectional decile assignment
allx = allx.sort_values('date')
allx['decile'] = allx.groupby('date')['rvol'].transform(
    lambda s: pd.qcut(s.rank(method='first'), 10, labels=False) if s.notna().sum() >= 30 else np.nan
)

# forward returns per name (t -> t+H) via groupby shift
allx = allx.sort_values(['sym', 'date'])
for H in (1, 3, 5):
    allx[f'fwd{H}'] = allx.groupby('sym')['close'].transform(lambda s: s.shift(-H) / s - 1)

COST_BPS = 5  # 5 bps round trip per side-of-book (conservative for liquid large caps)

for H in (1, 3, 5):
    top = allx[allx['decile'] == 9][f'fwd{H}']
    bot = allx[allx['decile'] == 0][f'fwd{H}']
    spread = top.mean() - bot.mean()
    # long top decile, short bottom decile: cost = 2 * round-trip per rebalance
    # (daily rebalance => ~H rebalances over H-day hold, but approximate single round trip)
    net = spread - 2 * COST_BPS / 10000 * (1 + (H > 1))  # approx: cost grows with rebalances
    hit = ((top > 0).mean() - (bot > 0).mean()) * 100
    print(f'  H={H}d: top-decile {top.mean()*100:+.3f}% vs bottom {bot.mean()*100:+.3f}% '
          f'=> spread {spread*100:+.3f}% (hit-diff {hit:+.1f}pp) | net@~{COST_BPS}bps ≈ {net*100:+.3f}%')
