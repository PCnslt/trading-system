"""Trading system dashboard — LIVE FACTS ONLY.

Reflects the running system straight from DynamoDB / S3 / systemd:
positions, P&L, signals, control/reconcile state, data-feed health,
price charts, and the architecture diagram. No roadmap, no checklist,
no prose — a dashboard, not a diary.
"""
import os
import sys
import datetime as dt
from zoneinfo import ZoneInfo

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Key, Attr
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.control import set_control as control_set_control
from dashboard.pulse import render_pulse, render_data_hot
from dashboard.trading_view import render_trading

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
NY = ZoneInfo("America/New_York")

ARCH_HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "assets", "architecture.html")


def _load_architecture_html():
    try:
        with open(ARCH_HTML_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMO_TABLE)

st.set_page_config(page_title="Trading System", page_icon="📈", layout="wide")


@st.cache_data(ttl=15)
def latest(pk, limit=1):
    r = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=limit)
    return r.get("Items", [])


@st.cache_data(ttl=15)
def get_control():
    r = table.get_item(Key={"pk": "CONTROL", "sk": "system"})
    return r.get("Item", {})


def set_control(**fields):
    control_set_control(table, **fields)
    st.cache_data.clear()


def _scan_all(filter_expr):
    """Paginated scan — one table.scan() returns ONE page (<=1MB); loop
    LastEvaluatedKey to avoid silently missing rows."""
    items, lek = [], None
    while True:
        kw = {'FilterExpression': filter_expr}
        if lek:
            kw['ExclusiveStartKey'] = lek
        r = table.scan(**kw)
        items.extend(r.get('Items', []))
        lek = r.get('LastEvaluatedKey')
        if not lek:
            break
    return items


@st.cache_data(ttl=15)
def scan_positions():
    """Currently-open positions (POSITION#* with pos>0)."""
    items = _scan_all(Attr('pk').begins_with('POSITION#') & Attr('sk').eq('current'))
    return [it for it in items if float(it.get('pos', 0) or 0) > 0]


@st.cache_data(ttl=15)
def scan_signals(limit=30):
    """Recent signals across all strategies (SIGNAL#*), newest first."""
    items = _scan_all(Attr('pk').begins_with('SIGNAL#'))
    items.sort(key=lambda x: x.get('ts', 0), reverse=True)
    return items[:limit]


@st.cache_data(ttl=15)
def realized_pnl_total():
    """Sum realized P&L across all lanes (RISK#<date>/<scope> ledger rows)."""
    items = _scan_all(Attr('pk').begins_with('RISK#'))
    tot = 0.0
    for it in items:
        try:
            tot += float(it.get('realized_pnl') or 0)
        except (TypeError, ValueError):
            pass
    return tot


def render_results():
    """Numbers strip: realized P&L · open positions · control · gate 5."""
    rp = realized_pnl_total()
    positions = scan_positions()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Realized P&L (all lanes)", f"${rp:,.2f}")
    c2.metric("Open positions", len(positions))
    c3.metric("Control", (get_control() or {}).get('state', '—'))
    c4.metric("Gate 5 sessions", "1 / 10")


def render_controls():
    """Safe control flags the bots read (no order entry)."""
    st.subheader("🕹️ Controls")
    st.caption("Flags the bots read each run — no order entry here.")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("⏸️ Pause bot", use_container_width=True):
            set_control(state="PAUSED")
            st.rerun()
    with c2:
        if st.button("🧹 Flatten positions", use_container_width=True):
            set_control(flatten="true")
            st.rerun()
    with c3:
        if st.button("🛑 KILL SWITCH", type="primary", use_container_width=True):
            set_control(state="KILLED")
            st.rerun()


st.title("📈 Trading System")

# --- control state banner ---
ctrl = get_control()
state = ctrl.get("state")
if state == "PAUSED":
    st.warning("⚠️ Bot is PAUSED")
elif state == "KILLED":
    st.error("🛑 Bot is KILLED — all trading halted")
elif state == "RUNNING":
    st.success("✅ Bot is RUNNING (paper mode)")
else:
    st.warning("⚠️ Control state UNKNOWN — bots are fail-closed (no trading until set)")

tab_live, tab_charts, tab_health, tab_arch = st.tabs(
    ["📊 Live", "📈 Charts", "🩺 Health", "🗺️ Architecture"])

# ============================ LIVE ============================
with tab_live:
    render_results()
    st.divider()
    render_pulse()
    st.divider()
    render_controls()

# ============================ CHARTS ============================
with tab_charts:
    render_trading()

# ============================ HEALTH ============================
with tab_health:
    render_data_hot()

# ============================ ARCHITECTURE ============================
with tab_arch:
    st.caption("The running system — strategy → risk → execution → broker → reconcile. "
               "Solid = trade path · dashed = broker-truth/state. Scroll the diagram.")
    _arch = _load_architecture_html()
    if _arch:
        st.components.v1.html(_arch, height=1000, scrolling=True)
    else:
        st.warning("assets/architecture.html not found.")
