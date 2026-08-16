"""INTRADAY futures scan — preliminary scaffold.

Data source TODAY: yfinance 5m bars (last 60 days, the free limit at 5m).
Once CME real-time is subscribed on IBKR paper (DUR193467), switch the loader
to IBKR reqHistoricalData (5m/15m) — the `load_ibkr_bars` function is written
and only needs an `ib` client + qualified contract. See `load_*` below.

Strategies (all tested LONG + SHORT, flattened by EOD — no overnight risk):
  (a) ORB      — opening-range breakout: first 30-min RTH range; enter on
                 close break of that range, exit EOD.
  (b) MOM      — N-bar ROC momentum (N=10 five-min bars): |ROC| > threshold
                 -> enter in ROC direction, exit after MOM_HOLD bars or EOD.
  (c) VWAP     — intraday VWAP reversion: close z-score vs session VWAP;
                 fade > +k / < -k sigma, exit on VWAP touch or EOD.
  (d) DONCH15  — 15m Donchian(20)/ATR breakout (the validated DAILY edge at
                 15m scale): enter on close break of 20-bar channel, exit on
                 opposite channel mid, 2*ATR stop, or EOD.

COST: 1.3 bps round-trip of notional (repo convention — see futures_scan.py).
Execution model: enter at signal-bar CLOSE (matches the daily scan's
close-to-close convention), stop fills at the stop price, EOD exits at the
session close. Conservative-ish, but a preliminary scan only.

HONEST CAVEAT: 60 days of 5m data ≈ ~42-50 RTH sessions and ~30-80 trades per
strategy. That is NOT statistically meaningful for profit-factor or win-rate
claims — treat every number as a preliminary smoke result, not an edge. The
walk-forward split (60/40 chronological) is reported only when the OOS fold
has >= 10 trades; at this sample size it is directionally interesting at best.
"""
import os
import sys
import datetime as dt
import json

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# --- SSM-first secrets (infra/secrets.py): overlay /trading/* over .env fallback ---
import os as _so, sys as _ss
_ss.path.insert(0, _so.path.dirname(_so.path.dirname(_so.path.abspath(__file__))))
from infra.secrets import bootstrap as _sb
_sb()
from data.s3_archive import archive_scan_results

# ===== config =====
RTH_OPEN = dt.time(9, 30)
RTH_CLOSE = dt.time(16, 0)
TZ = 'America/New_York'
COST = 0.00013          # 1.3 bps round-trip of notional (repo convention)
SYMBOLS = ['ES=F', 'NQ=F']
WALK_FORWARD = True     # 60/40 chronological split, reported only if OOS >= 10 trades
MIN_DAY_BARS = 12       # skip truncated sessions

# strategy params (named, tunable)
ORB_MIN_BARS = 6        # 30 min of 5m bars = opening range
MOM_N = 10              # ROC lookback (5m bars)
MOM_HOLD = 6            # hold bars before exit
MOM_THRESH = 0.0015     # |ROC| entry threshold
VWAP_K = 2.0            # sigma multiple for the reversion band
VWAP_SD_N = 10          # rolling std window for the VWAP z-score
DC_N = 20               # Donchian lookback (15m bars)
DC_ATR_N = 14           # ATR lookback (15m bars)
DC_STOP_ATR = 2.0       # ATR multiple for the stop


# ===== data loaders (source-switchable) =====
def load_yfinance_5m(symbol, period='60d'):
    """5m bars from yfinance (free tier caps 5m at ~60 days)."""
    df = yf.download(symbol, period=period, interval='5m',
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def load_ibkr_bars(ib, contract, duration='60 D', bar_size='5 mins', rth=True):
    """IBKR historical 5m/15m bars — switch here once CME real-time is live.

    `ib` is a connected ib_insync.IB(); `contract` a qualified Future.
    bar_size '5 mins' or '15 mins'. Returns an RTH-filterable DataFrame
    indexed by tz-aware timestamps (America/New_York) with OHLCV columns.
    """
    from ib_insync import util
    bars = ib.reqHistoricalData(contract, endDateTime='', durationStr=duration,
                                barSizeSetting=bar_size, whatToShow='TRADES',
                                useRTH=rth, formatDate=2)
    if not bars:
        return pd.DataFrame()
    df = util.df(bars).rename(columns=str.title)
    df = df.set_index('Date')
    if getattr(df.index, 'tz', None) is None:
        df.index = pd.to_datetime(df.index, utc=True)
    df.index = df.index.tz_convert(TZ)
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]


def prep_rth(df):
    """Normalize tz to America/New_York and keep regular-trading-hours bars."""
    df = df.copy()
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize(TZ)
    else:
        idx = idx.tz_convert(TZ)
    df.index = idx
    df = df[(df.index.time >= RTH_OPEN) & (df.index.time < RTH_CLOSE)]
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    df['date'] = df.index.date
    return df


# ===== shared trade engine =====
def _run_day(bars, sym, name, enter_fn, exit_fn, stop_fn=None):
    """Event loop over one RTH day. Enter at signal-bar close, exit on signal
    close / intra-bar stop / EOD close. One position at a time (first signal
    wins)."""
    trades = []
    pos = 0
    entry_px = entry_ts = stop_px = None
    entry_i = 0
    for i in range(len(bars)):
        row = bars.iloc[i]
        o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
        ts = bars.index[i]
        if pos == 0:
            side = enter_fn(bars, i)
            if side:
                pos = side
                entry_px = c
                entry_ts = ts
                entry_i = i
                stop_px = stop_fn(bars, i, c, side) if stop_fn else None
                continue
        else:
            exit_px = reason = None
            if stop_px is not None:
                if pos == 1 and l <= stop_px:
                    exit_px = stop_px
                    reason = 'stop'
                elif pos == -1 and h >= stop_px:
                    exit_px = stop_px
                    reason = 'stop'
            if exit_px is None and exit_fn(bars, i, pos, entry_px, entry_i, stop_px):
                exit_px = c
                reason = 'signal'
            if exit_px is None and i == len(bars) - 1:
                exit_px = c
                reason = 'EOD'
            if exit_px is not None:
                trades.append(dict(sym=sym, strat=name, side=pos,
                                   entry_ts=str(entry_ts), exit_ts=str(ts),
                                   entry_px=float(entry_px), exit_px=float(exit_px),
                                   ret=(exit_px / entry_px - 1) * pos - COST,
                                   reason=reason))
                pos = 0
                entry_px = entry_ts = stop_px = None
    return trades


# ===== strategies =====
def _orb(bars, sym):
    def enter_fn(b, i):
        if i < ORB_MIN_BARS:
            return 0
        rng = b.iloc[:ORB_MIN_BARS]
        hi, lo = rng['High'].max(), rng['Low'].min()
        c = b.iloc[i]['Close']
        if c > hi:
            return 1
        if c < lo:
            return -1
        return 0

    def exit_fn(b, i, pos, entry_px, entry_i, stop):
        return False  # EOD only

    return _run_day(bars, sym, 'ORB', enter_fn, exit_fn)


def _momentum(bars, sym):
    def enter_fn(b, i):
        if i < MOM_N:
            return 0
        roc = b.iloc[i]['Close'] / b.iloc[i - MOM_N]['Close'] - 1
        if roc > MOM_THRESH:
            return 1
        if roc < -MOM_THRESH:
            return -1
        return 0

    def exit_fn(b, i, pos, entry_px, entry_i, stop):
        return (i - entry_i) >= MOM_HOLD

    return _run_day(bars, sym, 'MOM', enter_fn, exit_fn)


def _vwap(bars, sym):
    tp = (bars['High'] + bars['Low'] + bars['Close']) / 3
    vol = bars['Volume'].clip(lower=0.0)
    vwap = (tp * vol).cumsum() / vol.cumsum()          # session-cumulative VWAP
    dev = bars['Close'] - vwap
    sd = dev.rolling(VWAP_SD_N).std()

    def enter_fn(b, i):
        s = sd.iloc[i]
        if pd.isna(s) or s == 0:
            return 0
        z = (b['Close'].iloc[i] - vwap.iloc[i]) / s
        if z < -VWAP_K:
            return 1
        if z > VWAP_K:
            return -1
        return 0

    def exit_fn(b, i, pos, entry_px, entry_i, stop):
        c = b['Close'].iloc[i]
        v = vwap.iloc[i]
        return (pos == 1 and c >= v) or (pos == -1 and c <= v)

    return _run_day(bars, sym, 'VWAP', enter_fn, exit_fn)


def _donchian_15m(bars5, sym):
    b = bars5[['Open', 'High', 'Low', 'Close', 'Volume']].resample(
        '15min', label='right', closed='right').agg(
        {'Open': 'first', 'High': 'max', 'Low': 'min',
         'Close': 'last', 'Volume': 'sum'}).dropna()
    hi = b['High'].rolling(DC_N).max().shift(1)
    lo = b['Low'].rolling(DC_N).min().shift(1)
    tr = pd.concat([b['High'] - b['Low'],
                    (b['High'] - b['Close'].shift()).abs(),
                    (b['Low'] - b['Close'].shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / DC_ATR_N, adjust=False).mean()

    def enter_fn(bb, i):
        if i < DC_N or pd.isna(hi.iloc[i]):
            return 0
        c = bb['Close'].iloc[i]
        if c > hi.iloc[i]:
            return 1
        if c < lo.iloc[i]:
            return -1
        return 0

    def exit_fn(bb, i, pos, entry_px, entry_i, stop):
        if i < DC_N or pd.isna(hi.iloc[i]):
            return False
        mid = (hi.iloc[i] + lo.iloc[i]) / 2
        c = bb['Close'].iloc[i]
        return (pos == 1 and c < mid) or (pos == -1 and c > mid)

    def stop_fn(bb, i, entry_px, side):
        a = atr.iloc[i]
        if pd.isna(a):
            return None
        return entry_px - DC_STOP_ATR * a if side == 1 else entry_px + DC_STOP_ATR * a

    return _run_day(b, sym, 'DONCH15', enter_fn, exit_fn, stop_fn)


STRATEGIES = {'ORB': _orb, 'MOM': _momentum, 'VWAP': _vwap, 'DONCH15': _donchian_15m}


# ===== metrics =====
def _summarize(trades):
    if not trades:
        return dict(trades=0, win=0.0, pf=0.0, net=0.0)
    rets = np.array([t['ret'] for t in trades])
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    gw = wins.sum()
    gl = abs(losses.sum())
    return dict(trades=len(rets),
                win=100.0 * len(wins) / len(rets),
                pf=(gw / gl if gl > 0 else float('inf')),
                net=float(rets.sum()))


def _split_wf(trades):
    t = sorted(trades, key=lambda x: x['entry_ts'])
    cut = int(len(t) * 0.6)
    return t[:cut], t[cut:]


# ===== main =====
def main():
    payload = {'cost': COST, 'walk_forward': WALK_FORWARD, 'symbols': {},
               'note': '60d yfinance 5m — statistically weak, preliminary only'}
    print(f"INTRADAY scan  ES=F + NQ=F  5m RTH  (cost={COST:.5f} = 1.3 bps RT)")
    print(f"{'strategy':<9}{'side':<7}{'n':>5}{'win%':>8}{'PF':>8}  {'WF OOS n':>9}{'WF OOS PF':>10}")
    print('-' * 58)

    all_trades = {name: [] for name in STRATEGIES}
    for sym in SYMBOLS:
        df = load_yfinance_5m(sym)
        if df is None or df.empty:
            print(f'{sym}: no data')
            continue
        rth = prep_rth(df)
        days = sorted(rth['date'].unique())
        payload['symbols'][sym] = {'bars': int(len(rth)), 'days': int(len(days))}
        print(f'{sym}: {len(rth)} RTH 5m bars / {len(days)} sessions')
        for name, fn in STRATEGIES.items():
            for d, g in rth.groupby('date'):
                if len(g) < MIN_DAY_BARS:
                    continue
                all_trades[name].extend(fn(g, sym))

    rows = []
    for name in STRATEGIES:
        trades = all_trades[name]
        for side_label, sides in [('long', [1]), ('short', [-1]), ('both', [1, -1])]:
            sub = [t for t in trades if t['side'] in sides]
            s = _summarize(sub)
            oos = None
            if WALK_FORWARD and sub:
                _, oos_t = _split_wf(sub)
                if len(oos_t) >= 10:
                    oos = _summarize(oos_t)
            row = dict(strategy=name, side=side_label, n=s['trades'],
                       win=round(s['win'], 1), pf=round(s['pf'], 2) if np.isfinite(s['pf']) else None)
            if oos:
                row['oos_n'] = oos['trades']
                row['oos_pf'] = round(oos['pf'], 2) if np.isfinite(oos['pf']) else None
            rows.append(row)
            oos_str = f"{row.get('oos_n','')!s:>9}  {row.get('oos_pf','')!s:>10}"
            pf_str = f"{s['pf']:.2f}" if np.isfinite(s['pf']) else " inf"
            print(f"{name:<9}{side_label:<7}{s['trades']:>5}{s['win']:>7.1f}%{pf_str:>8}  {oos_str}")

    print('-' * 58)
    print('CAVEAT: 60 days of 5m bars = ~42-50 sessions, ~30-80 trades/strategy.')
    print('PF/win% are NOT statistically meaningful here. Walk-forward OOS only')
    print('shown when the 40% fold had >= 10 trades; treat as directional smoke.')

    payload['rows'] = rows
    out = 'intraday_scan_results.json'
    with open(out, 'w') as f:
        json.dump(payload, f, indent=2)
    print(f'wrote {out}')
    try:
        archive_scan_results('intraday', payload)
    except Exception as e:
        print(f'S3 archive failed: {e}')


if __name__ == '__main__':
    main()

