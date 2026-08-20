"""Trading view — the 'day trading' cockpit: price charts (with the indicators
the bots actually run) + live bot logs + current signal state.

Read-only. No broker writes, no CONTROL mutation.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Key

from dashboard import charts, logs

NY = ZoneInfo('America/New_York')
_dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
_table = _dynamodb.Table('trading-data')


@st.cache_data(ttl=15, show_spinner=False)
def _latest_signal(tag):
    """Latest SIGNAL#<tag> item (newest sk) -> dict or None."""
    try:
        r = _table.query(KeyConditionExpression=Key('pk').eq(f'SIGNAL#{tag}'),
                         ScanIndexForward=False, Limit=1)
        items = r.get('Items', [])
        return items[0] if items else None
    except Exception:
        return None


@st.cache_data(ttl=15, show_spinner=False)
def _reconcile():
    r = _table.get_item(Key={'pk': 'RECONCILE', 'sk': 'system'})
    return r.get('Item') or {}


@st.cache_data(ttl=15, show_spinner=False)
def _control():
    r = _table.get_item(Key={'pk': 'CONTROL', 'sk': 'system'})
    return r.get('Item') or {}


def _signal_line(tag, default='—'):
    s = _latest_signal(tag)
    if not s:
        return default
    sig = s.get('signal', '—')
    reason = str(s.get('reason', ''))[:110]
    return f"**{sig}** — {reason}"


def _status_strip():
    c = _control()
    r = _reconcile()
    state = c.get('state', 'UNKNOWN')
    rst = r.get('status', 'no-data')
    emoji = {'RUNNING': '✅', 'PAUSED': '⚠️', 'KILLED': '🛑'}.get(state, '❓')
    col1, col2, col3 = st.columns(3)
    col1.metric('Control', f'{emoji} {state}')
    col2.metric('Reconcile', rst)
    col3.metric('Flatten flag', str(c.get('flatten', '—')))


def render_trading():
    st.caption(f"Live day-trading view · charts + logs · "
               f"{dt.datetime.now(NY).strftime('%Y-%m-%d %H:%M:%S')} ET · read-only")
    _status_strip()
    st.divider()

    # ---- Intraday MES ----
    st.subheader('⚡ Intraday — MES  (live_intraday.py)')
    mode = st.radio('Strategy', ['DONCH15 (15m breakout)', 'FADESHORT (5m fade)'],
                    horizontal=True, label_visibility='collapsed', key='intra_mode')
    if mode.startswith('DONCH15'):
        df = charts.load_intraday('MES', '15min')
        chart = charts.intraday_chart(df, 'donch15')
        sig_tag = 'MES_DONCH15'
        legend = '🟦 20-bar Donchian channel (hi/lo) · 🟦 dashed = mid (exit) · orange = RSI(2)'
    else:
        df = charts.load_intraday('MES', '5min')
        chart = charts.intraday_chart(df, 'fadeshort')
        sig_tag = 'MES_FADESHORT'
        legend = '🟪 Bollinger(20, 2σ) band · 🟪 dashed = mid · entry = RSI(2)>90 & close>upper'
    st.markdown(f"Latest signal: {_signal_line(sig_tag)}")
    if chart is not None:
        st.altair_chart(chart, width='stretch')
        st.caption(legend)
    else:
        st.caption('No intraday bars archived yet — the bot writes them on its first RTH run.')

    st.divider()

    # ---- Daily index ----
    st.subheader('📅 Daily — index  (live.py: Donchian + RSI2)')
    sym = st.radio('Symbol', ['MES', 'MNQ', 'MYM'], horizontal=True, key='daily_sym')
    df = charts.load_daily(sym)
    d_chart = charts.daily_chart(df)
    d_tag = f'{sym}_DONCHIAN'
    r_tag = f'{sym}_RSI2'
    st.markdown(f"**Donchian** latest: {_signal_line(d_tag)}")
    st.markdown(f"**RSI2** latest: {_signal_line(r_tag)}")
    if d_chart is not None:
        st.altair_chart(d_chart, width='stretch')
        st.caption('🟦 20-day Donchian channel · 🟡 dashed = 200-day SMA (RSI2 trend gate) '
                   '· orange = RSI(2)')
    else:
        st.caption('No daily bars available.')

    st.divider()

    # ---- Gold ----
    st.subheader('🥇 Gold — GC  (live_gc.py: Donchian L/S)')
    gdf = charts.load_gc_daily()
    g_chart = charts.gc_chart(gdf)
    st.markdown(f"Latest signal: {_signal_line('GC_DONCHIAN')}")
    if g_chart is not None:
        st.altair_chart(g_chart, width='stretch')
        st.caption('🟦 20-day Donchian channel · 🟥/🟩 dashed = 3·ATR chandelier stop reference')
    else:
        st.caption('GC daily unavailable (yfinance GC=F source) — gold L1 is delayed on paper.')

    st.divider()

    # ---- Live bot logs ----
    st.subheader('📜 Live bot logs')
    st.caption('Tails the latest cron run of each trading bot (auto-refreshes every 30s).')
    for b in logs.all_bots():
        run = b['run_ts'] or 'never'
        with st.expander(f"{b['label']} — {b['blurb']} · last run `{run}`"):
            if b['tail']:
                st.code(b['tail'], language='text')
            else:
                st.caption('No log output yet.')
