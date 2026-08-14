"""Trading system dashboard — read-only cockpit + safe controls + architecture/roadmap.

Reads live data from DynamoDB. Controls write flags to DynamoDB that the
bot reads. No arbitrary order entry here.
"""
import os
import sys
import datetime as dt

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Key, Attr
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.control import set_control as control_set_control

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMO_TABLE)

CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
EQUITIES = ["AAPL", "MSFT", "SPY", "MCD"]

st.set_page_config(page_title="Trading System", page_icon="📈", layout="wide")


@st.cache_data(ttl=15)
def latest(pk, limit=1):
    """Latest record for a partition key (sorted desc by sk)."""
    r = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=limit)
    return r.get("Items", [])


@st.cache_data(ttl=15)
def get_control():
    r = table.get_item(Key={"pk": "CONTROL", "sk": "system"})
    return r.get("Item", {})


def set_control(**fields):
    # Read-modify-write via the shared control module (preserves existing flags).
    control_set_control(table, **fields)
    st.cache_data.clear()


@st.cache_data(ttl=15)
def scan_positions():
    """All currently-open positions (POSITION#* items with pos>0)."""
    r = table.scan(FilterExpression=Attr('pk').begins_with('POSITION#') & Attr('sk').eq('current'))
    return [it for it in r.get('Items', []) if int(it.get('pos', 0)) > 0]


@st.cache_data(ttl=15)
def scan_signals(limit=30):
    """Recent signals across all strategies (SIGNAL#* items), newest first."""
    r = table.scan(FilterExpression=Attr('pk').begins_with('SIGNAL#'))
    items = r.get('Items', [])
    items.sort(key=lambda x: x.get('ts', 0), reverse=True)
    return items[:limit]


st.title("📈 Trading System")

# --- Control state banner ---
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

tab_live, tab_arch, tab_road = st.tabs(["📊 Live", "🗺️ Architecture", "📋 Roadmap"])

# ============================ LIVE TAB ============================
with tab_live:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Crypto prices")
        for sym in CRYPTO:
            rows = latest(f"QUOTE#{sym}", 1)
            if rows:
                st.metric(sym, f"${float(rows[0]['price']):,.2f}")
            else:
                st.metric(sym, "—")
    with col2:
        st.subheader("Equities — latest close")
        for sym in EQUITIES:
            rows = latest(f"OHLCV#{sym}", 1)
            if rows:
                st.metric(sym, f"${float(rows[0]['close']):,.2f}")
            else:
                st.metric(sym, "—")
    with col3:
        st.subheader("Open positions")
        positions = scan_positions()
        if positions:
            for p in positions:
                tag = p['pk'].split('#', 1)[-1]
                side = p.get('side', 'LONG')
                arrow = '▲' if side == 'LONG' else '▼'
                st.markdown(f"{arrow} **{tag}** — {p.get('pos','0')} {side.lower()}"
                            f" · entry {p.get('entry','—')} · stop {p.get('stop','—')}")
        else:
            st.caption("No open positions")

    st.divider()
    st.subheader("🔔 Recent signals (all strategies)")
    sigs = scan_signals(30)
    if sigs:
        for s in sigs:
            tag = s['pk'].split('#', 1)[-1]
            sig = s.get('signal', '—')
            emoji = {'LONG': '🟢', 'SHORT': '🔴', 'EXIT': '🔵',
                     'COVER': '🟣', 'BUY': '🟢', 'SELL': '🔴'}.get(sig, '⚪️')
            st.markdown(f"{emoji} `{tag}` → **{sig}** · close {s.get('close','—')}"
                        f" · pos {s.get('pos','—')} · {str(s.get('reason',''))[:90]}")
    else:
        st.caption("No signals yet — first bot run pending.")

    st.divider()
    st.subheader("📰 Market research — latest headlines")
    _day = dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')
    _news = latest(f'NEWS#{_day}', 8)
    if _news:
        for _n in _news:
            _lbl = _n.get('sentiment', 'neutral')
            _emoji = {'positive': '🟢', 'negative': '🔴', 'neutral': '⚪️'}.get(_lbl, '⚪️')
            _sc = _n.get('score', '0')
            st.markdown(f"{_emoji} **{_lbl}** ({_sc}) — {_n.get('title','')} · `{_n.get('source','')}`")
    else:
        st.caption("No headlines yet — first research run pending.")

    st.divider()
    st.subheader("🕹️ Controls")
    st.caption("Safe controls only — no order entry here. These set flags the bot reads.")
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
    st.caption("Flatten/kill flags are read by ALL bots (live.py / live_bondsfx.py / live_intraday.py) "
               "each run before any order. They persist in DynamoDB until cleared.")

# ============================ ARCHITECTURE TAB ============================
with tab_arch:
    st.subheader("System architecture")
    st.code("""
                    ┌─────────────────────────────┐
                    │      RESEARCH / DATA        │
                    │  TradingView (charts/Pine)  │
                    │  yfinance ES=F · AlphaVantage│
                    │  Binance.US (crypto data)   │
                    └──────────────┬──────────────┘
                                   │ signals / data
                                   ▼
┌───────────────────────────────────────────────────────────────┐
│               AWS VPS (t3.small · us-east-1 · 24/7)           │
│                                                               │
│   IB Gateway + IBC (auto-login · auto-restart · API :4002)    │
│   Real-time CME/CBOT L1 → paper DUR193467 (marketDataType=1)  │
│                                                               │
│   ┌── bot/control.py (kill switch) ──────────────────────────┐│
│   │  RUNNING/PAUSED/KILLED · flatten — read by ALL 3 bots    ││
│   │  BEFORE any order (fail-closed if unreadable)            ││
│   └───────────────────────┬──────────────────────────────────┘│
│                           ▼                                    │
│   ┌── BOTS (Hermes cron) ──────────────┐   ┌───────────────┐  │
│   │ live.py · index MES/MNQ · 23:00    │   │  RISK ENGINE  │  │
│   │   Donchian trend + RSI2 dip        │──▶│ budget sleeve │  │
│   │ live_bondsfx.py · ZB/ZN · 23:05    │   │ loss halt     │  │
│   │   fade-short (RSI2 / Bollinger)    │──▶│ fail-closed   │  │
│   │ live_intraday.py · MES · */15 RTH  │   │               │  │
│   │   FADESHORT + DONCH15 · EOD flatten│──▶└───────┬───────┘  │
│   └────────────────────────────────────┘          ▼            │
│                                          ┌───────────────┐    │
│                                          │ IBKR execution│    │
│                                          │   (paper)     │    │
│                                          └───────────────┘    │
│   Guards: cross-bot stand-down (intraday defers if daily      │
│   bot holds MES) · same-day RUN# dedupe (Hermes cron only)    │
│                                                               │
│   Data lake: DynamoDB `trading-data` + S3 `trading-datalake`  │
│   Dashboard :8501 · Hermes ops agent (Telegram)               │
│   Secrets: .env + SSM (never in git)                          │
│   Brokers: IBKR=futures · Robinhood=options L2 ·              │
│            Binance.US=crypto data (tabled) · Schwab DROPPED   │
└───────────────────────────────────────────────────────────────┘
         ▲                         │ alerts / results
   control (webhook :8644)         ▼
  ┌────────────┐           ┌───────────────┐
  │  Laptop    │           │ Telegram bot  │
  │  (admin)   │           │ (observability)│
  └────────────┘           └───────────────┘
""", language="text")

# ============================ ROADMAP TAB ============================
with tab_road:
    st.subheader("Build roadmap & checklist")
    st.caption("Phase 1 = futures (paper). 100% paper until edges earn trust. Stocks/options/futures live next. Crypto tabled.")

    st.markdown("#### ✅ Done")
    st.markdown("""
| Area | Item |
|---|---|
| Infra | EC2 t3.small + 2GB swap + Elastic IP |
| Infra | CloudFormation IaC + SSM secrets |
| IBKR | **IBC automation** — auto-login, API :4002, daily auto-restart (no re-auth), weekly 2FA |
| IBKR | Execution validated — MES paper round-trip filled |
| IBKR | Real-time CME/CBOT L1 → paper DUR193467 (marketDataType=1) |
| Bot | `live.py` — index futures MES/MNQ (Donchian trend + RSI2 dip), 23:00 UTC |
| Bot | `live_bondsfx.py` — bonds ZB/ZN fade-short (RSI2 / Bollinger), 23:05 UTC |
| Bot | `live_intraday.py` — intraday MES (FADESHORT + DONCH15), */15 RTH |
| Bot | Kill switch (bot/control.py) + cross-bot guard + same-day RUN# dedupe |
| Bot | Risk engine — budget sleeve, loss halt, fail-closed |
| Strategy | Walk-forward/OOS — Donchian long OOS PF 2.08/2.16 (ES/NQ, n=59/53); ADX long 2.55/1.77 (n=10/11, thin) |
| Strategy | ES breakout backtest — PF 2.73, MaxDD -7.9% |
| Data | DynamoDB + S3 lake, crypto/equities ingest live |
| Ops | VPS Hermes synced + self-checking (Telegram operator) |
""")

    st.markdown("#### 🔄 In progress / next")
    st.markdown("""
| # | Item |
|---|---|
| 1 | Paper-trade the live loop — first signals: index 23:00 UTC + bonds 23:05 UTC tonight, intraday Mon 13:30 UTC |
| 2 | Risk-engine daily-loss auto-cap → wire record_fill/close accounting (follow-up, not blocking) |
""")
    st.caption("Known gap (honest): daily-loss auto-cap is stateless — record_fill/close "
               "accounting not wired yet, so the halt can't trigger until it is.")

    st.markdown("#### ❌ Tabled / blocked")
    st.markdown("""
| Item | Why |
|---|---|
| Crypto | User doesn't trust it — deferred (Binance.US = data only) |
| Live futures | Capital HOLD — 100% paper until edges earn trust (several clean paper signals first) |
| Discount-broker day-margin | High leverage (~195×) = account-wipeout risk — user rejected |
| Options module (Robinhood L2) | Deferred until futures paper edge trusted |
| Schwab API | Dropped (futures=IBKR, options=Robinhood L2) |
""")

st.caption(f"Updated {dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M')} UTC · Data: DynamoDB `trading-data` · S3 `trading-datalake-920641308584`")
