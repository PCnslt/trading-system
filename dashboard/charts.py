"""Trading charts — live price action + the exact indicators the bots compute.

Renders candlestick charts with the strategy overlays the bots actually use:
  - Intraday MES 15m  → DONCH15: 20-bar Donchian channel (hi/lo/mid)
  - Intraday MES 5m   → FADESHORT: Bollinger(20,2) + RSI(2) > 90 threshold
  - Daily MES/MNQ     → Donchian 20-day channel + 200-day SMA + RSI(2)
  - Daily GC (gold)   → Donchian 20-day channel + 3·ATR chandelier reference

Data sources: S3 `futures-bars/intraday/<sym>/<barsize>/<date>.json` (full window),
S3 `futures-bars/daily/<sym>/<date>.json` (one bar per file), yfinance `GC=F`.
Indicators are byte-for-byte the same math as bot/live.py + bot/live_intraday.py.
"""
import os
import json
from concurrent.futures import ThreadPoolExecutor

import boto3
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st
from dotenv import load_dotenv

load_dotenv('/home/ubuntu/trading-system/.env')   # explicit path (skill pitfall)

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET = os.getenv('S3_BUCKET', 'trading-datalake-920641308584')

_s3 = boto3.client('s3', region_name=AWS_REGION)

# ============================ indicators (match bots exactly) ============================
def wilder_atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=2):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def bollinger(close, n, k):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid, mid + k * sd, mid - k * sd


def donchian(df, n):
    """Prior n-bar high/low (shift(1)) — matches live.py / live_intraday.py."""
    hi = df['high'].rolling(n).max().shift(1)
    lo = df['low'].rolling(n).min().shift(1)
    return hi, lo


# ============================ data loaders ============================
@st.cache_data(ttl=300, show_spinner=False)
def load_intraday(sym='MES', barsize='15min'):
    """Latest intraday window from S3 (one object/day, full window inside)."""
    try:
        r = _s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=f'futures-bars/intraday/{sym}/{barsize}/')
        keys = sorted([o['Key'] for o in r.get('Contents', [])])
        if not keys:
            return None
        o = _s3.get_object(Bucket=S3_BUCKET, Key=keys[-1])
        d = json.loads(o['Body'].read())
        df = pd.DataFrame(d['bars'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_daily(sym='MES', n=300):
    """Stitch the last n daily bar JSONs (one per file) into a DataFrame."""
    try:
        r = _s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=f'futures-bars/daily/{sym}/')
        keys = sorted([o['Key'] for o in r.get('Contents', [])])[-n:]

        def _get(k):
            try:
                o = _s3.get_object(Bucket=S3_BUCKET, Key=k)
                d = json.loads(o['Body'].read())
                return {'date': d['date'], 'open': float(d['open']), 'high': float(d['high']),
                        'low': float(d['low']), 'close': float(d['close']), 'volume': float(d['volume'])}
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=16) as ex:
            rows = list(ex.map(_get, keys))
        df = pd.DataFrame([r_ for r_ in rows if r_])
        if df.empty:
            return None
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_gc_daily(period='3y'):
    """Gold daily from yfinance GC=F (same source as bot/live_gc.py)."""
    try:
        import yfinance as yf
        df = yf.download('GC=F', period=period, interval='1d', progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df = df.reset_index()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        rename = {}
        for c in df.columns:
            cl = str(c).lower()
            if cl in ('date', 'datetime', 'index'):
                rename[c] = 'date'
            elif cl == 'open':
                rename[c] = 'open'
            elif cl == 'high':
                rename[c] = 'high'
            elif cl == 'low':
                rename[c] = 'low'
            elif cl == 'close':
                rename[c] = 'close'
            elif cl == 'volume':
                rename[c] = 'volume'
        df = df.rename(columns=rename)
        keep = [c for c in ('date', 'open', 'high', 'low', 'close', 'volume') if c in df.columns]
        df = df[keep]
        df['date'] = pd.to_datetime(df['date'])
        df = df.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
        return df if not df.empty else None
    except Exception:
        return None


# ============================ chart builders ============================
def _candle(df, date_col='date'):
    """OHLC candlesticks (green up / red down)."""
    color = alt.condition('datum.close >= datum.open',
                          alt.value('#26a69a'), alt.value('#ef5350'))
    wicks = alt.Chart(df).mark_rule(size=1, color='#6b7280').encode(
        x=alt.X(f'{date_col}:T', title=None),
        y=alt.Y('low:Q', scale=alt.Scale(zero=False), title='price'),
        y2=alt.Y2('high:Q'),
    )
    bodies = alt.Chart(df).mark_bar(size=7).encode(
        x=alt.X(f'{date_col}:T'),
        y=alt.Y('open:Q', scale=alt.Scale(zero=False)),
        y2=alt.Y2('close:Q'),
        color=color,
    )
    return wicks + bodies


def _band(df, hi_col, lo_col, color):
    return alt.Chart(df).mark_area(opacity=0.13, color=color).encode(
        x=alt.X('date:T', title=None),
        y=alt.Y(f'{hi_col}:Q', scale=alt.Scale(zero=False)),
        y2=alt.Y2(f'{lo_col}:Q'),
    )


def _line(df, col, color, dash=None):
    return alt.Chart(df).mark_line(color=color, strokeWidth=1.2,
                                   strokeDash=dash or []).encode(
        x=alt.X('date:T'), y=alt.Y(f'{col}:Q'))


def _rsi_panel(df, col='rsi2', over=90.0, under=10.0):
    line = alt.Chart(df).mark_line(color='#f59e0b', strokeWidth=1.2).encode(
        x=alt.X('date:T', title=None), y=alt.Y(f'{col}:Q', title='RSI(2)', scale=alt.Scale(domain=[0, 100]))
    )
    over_line = alt.Chart(pd.DataFrame({'y': [over]})).mark_rule(
        color='#ef5350', strokeDash=[4, 4]).encode(y='y:Q')
    under_line = alt.Chart(pd.DataFrame({'y': [under]})).mark_rule(
        color='#26a69a', strokeDash=[4, 4]).encode(y='y:Q')
    return (line + over_line + under_line).properties(height=90, width='container')


def _latest_session(df):
    """Slice to the most recent trading session (clean 'today' view)."""
    if df is None or df.empty:
        return df
    last = df['date'].dt.date.iloc[-1]
    return df[df['date'].dt.date == last].reset_index(drop=True)


def intraday_chart(df, mode):
    """mode: 'donch15' (15m) | 'fadeshort' (5m). Returns a vconcat altair spec."""
    if df is None or df.empty:
        return None
    df = df.copy()
    # indicators on the FULL window (continuous channel warmup), then slice latest session
    if mode == 'donch15':
        hi, lo = donchian(df, 20)
        df['don_hi'] = hi
        df['don_lo'] = lo
        df['mid'] = (hi + lo) / 2
        df['rsi2'] = rsi(df['close'], 2)
        view = _latest_session(df)
        main = alt.layer(_band(view, 'don_hi', 'don_lo', '#5c6bc0'),
                         _candle(view), _line(view, 'mid', '#5c6bc0', [4, 4])).resolve_scale(y='shared')
        panel = _rsi_panel(view)
    else:  # fadeshort
        mid, upper, lower = bollinger(df['close'], 20, 2.0)
        df['boll_mid'] = mid
        df['boll_up'] = upper
        df['boll_lo'] = lower
        df['rsi2'] = rsi(df['close'], 2)
        view = _latest_session(df)
        main = alt.layer(_band(view, 'boll_up', 'boll_lo', '#ab47bc'),
                         _candle(view), _line(view, 'boll_mid', '#ab47bc', [4, 4])).resolve_scale(y='shared')
        panel = _rsi_panel(view, over=90.0, under=50.0)
    main = main.properties(width='container')
    chart = (main & panel).resolve_scale(x='shared').interactive()
    return chart


def daily_chart(df, show_sma200=True):
    """Daily candlestick + Donchian 20-day channel + (optional) 200d SMA + RSI(2)."""
    if df is None or df.empty:
        return None
    df = df.copy()
    hi, lo = donchian(df, 20)
    df['don_hi'] = hi
    df['don_lo'] = lo
    df['sma200'] = df['close'].rolling(200).mean()
    df['rsi2'] = rsi(df['close'], 2)
    layers = [_band(df, 'don_hi', 'don_lo', '#5c6bc0'), _candle(df)]
    if show_sma200:
        layers.append(_line(df, 'sma200', '#eab308', [2, 2]))
    main = alt.layer(*layers).resolve_scale(y='shared').properties(width='container')
    panel = _rsi_panel(df, over=70.0, under=10.0)
    chart = (main & panel).resolve_scale(x='shared').interactive()
    return chart


def gc_chart(df):
    """Gold daily: Donchian channel + 3·ATR chandelier reference (L/S)."""
    if df is None or df.empty:
        return None
    df = df.copy()
    hi, lo = donchian(df, 20)
    df['don_hi'] = hi
    df['don_lo'] = lo
    atr = wilder_atr(df['high'], df['low'], df['close'], 14)
    df['atr'] = atr
    # 3·ATR around the prior close = the chandelier reference band (L/S symmetric)
    df['stop_long'] = df['close'] - 3 * atr
    df['stop_short'] = df['close'] + 3 * atr
    layers = [_band(df, 'don_hi', 'don_lo', '#5c6bc0'), _candle(df),
              _line(df, 'stop_long', '#ef5350', [4, 4]),
              _line(df, 'stop_short', '#26a69a', [4, 4])]
    main = alt.layer(*layers).resolve_scale(y='shared')
    return main.properties(width='container').interactive()
