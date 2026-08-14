"""Trading system dashboard — read-only cockpit + safe controls + architecture/roadmap.

Reads live data from DynamoDB. Controls write flags to DynamoDB that the
bot reads. No arbitrary order entry here.
"""
import os
import datetime as dt

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

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
    item = {"pk": "CONTROL", "sk": "system", "ts": int(dt.datetime.now(dt.UTC).timestamp())}
    item.update(fields)
    table.put_item(Item=item)
    st.cache_data.clear()


st.title("📈 Trading System")

# --- Control state banner ---
ctrl = get_control()
state = ctrl.get("state", "RUNNING")
if state == "PAUSED":
    st.warning("⚠️ Bot is PAUSED")
elif state == "KILLED":
    st.error("🛑 Bot is KILLED — all trading halted")
else:
    st.success("✅ Bot is RUNNING (paper mode)")

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
        st.subheader("Bot — ES trend breakout")
        sig = latest("SIGNAL#ES=F", 1)
        pos = table.get_item(Key={"pk": "POSITION#MES", "sk": "current"}).get("Item", {})
        if sig:
            s = sig[0]
            st.metric("Signal", s.get("signal", "—"))
            st.metric("ADX", s.get("adx", "—"))
            st.metric("Close", s.get("close", "—"))
            st.caption(f"last: {s.get('sk', '—')}")
        st.metric("Position (MES)", pos.get("pos", "0"))
        if pos.get("stop"):
            st.metric("Stop", pos.get("stop"))

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
    st.caption("Flatten/kill flags are read by the bot loop. They persist in DynamoDB until cleared.")

# ============================ ARCHITECTURE TAB ============================
with tab_arch:
    st.subheader("System architecture")
    st.code("""
                    ┌─────────────────────────────┐
                    │      RESEARCH / DATA        │
                    │  TradingView (charts/Pine)  │
                    │  yfinance ES=F · AlphaVantage│
                    │  Binance.US · Serper         │
                    └──────────────┬──────────────┘
                                   │ signals / data
                                   ▼
┌───────────────────────────────────────────────────────────┐
│               AWS VPS (t3.small, us-east-1, 24/7)         │
│                                                           │
│  IB Gateway + IBC  (auto-login · auto-restart · API :4002)│
│                                                           │
│  ┌──────────┐  ┌────────────┐  ┌───────────────┐         │
│  │ live.py  │→ │ RISK ENGINE│→ │ IBKR execution│         │
│  │ bot cron │  │ sizing·halt│  │  (paper MES)  │         │
│  │ 23:00 UTC│ └────────────┘  └───────────────┘         │
│  └──────────┘                                            │
│                                                           │
│  Data lake: DynamoDB `trading-data` + S3 `trading-datalake`│
│  Hermes ops agent (Telegram) · Dashboard :8501            │
│  Secrets: .env + SSM (never in git)                       │
└───────────────────────────────────────────────────────────┘
         ▲                        │ alerts / results
   control (SSH)                  ▼
  ┌────────────┐          ┌──────────────┐
  │  Laptop    │          │ Telegram bot │
  │  (admin)   │          │ (control)    │
  └────────────┘          └──────────────┘
""", language="text")

# ============================ ROADMAP TAB ============================
with tab_road:
    st.subheader("Build roadmap & checklist")
    st.caption("Phase 1 = futures (paper). Stocks/options/futures live next. Crypto tabled for last.")

    st.markdown("#### ✅ Done")
    st.markdown("""
| Area | Item |
|---|---|
| Infra | EC2 t3.small + 2GB swap + Elastic IP |
| Infra | CloudFormation IaC + SSM secrets |
| IBKR | **IBC automation** — auto-login, API :4002, daily auto-restart (no re-auth), weekly 2FA |
| IBKR | Execution validated — MES paper round-trip filled |
| Bot | `live.py` — entry/exit/stop, daily trailing, SMA200 exit |
| Bot | Risk engine — budget sleeve, loss halt, fail-closed |
| Strategy | ES breakout backtest — PF 2.73, MaxDD -7.9% |
| Data | DynamoDB + S3 lake, crypto/equities ingest live |
| Ops | VPS Hermes synced + self-checking (Telegram operator) |
""")

    st.markdown("#### 🔄 In progress / next")
    st.markdown("""
| # | Item |
|---|---|
| 1 | Paper-trade the live loop (watch for first signal) |
| 2 | Walk-forward / out-of-sample backtest (confirm PF not overfit) |
| 3 | Stocks module — Robinhood Agentic (fractional, low-risk real money) |
| 4 | Schwab API (stocks/options) — approval pending |
| 5 | Intraday futures (CME sub) — once capital/risk is sorted |
| 6 | Options module — after Robinhood upgrade or Schwab |
""")

    st.markdown("#### ❌ Tabled / blocked")
    st.markdown("""
| Item | Why |
|---|---|
| Crypto | User doesn't trust it yet — deferred until stocks/options/futures are live |
| Live futures | Needs ~$1.3k+ on IBKR (or discount-broker day-margin) — capital decision pending |
| Discount-broker day-margin | High leverage (~195×) = account-wipeout risk — user rejected |
""")

st.caption(f"Updated {dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M')} UTC · Data: DynamoDB `trading-data` · S3 `trading-datalake-920641308584`")
