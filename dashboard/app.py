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
    st.caption("Flatten/kill flags are read by all active bots (live.py / live_intraday.py) "
               "each run before any order. They persist in DynamoDB until cleared.")

# ============================ ARCHITECTURE TAB ============================
with tab_arch:
    st.subheader("System architecture — TARGET (current vs target annotated)")
    st.caption("This is the target layered design, NOT the as-built state. Layers 2–7 are the hardening "
               "being added — current code skips straight from strategy → IBKR.")

    st.code("""                        RESEARCH / DATA LAKE
        ┌──────────────────────────────────────────────────────┐
        │  TradingView (charts/Pine) · yfinance ES=F           │
        │  AlphaVantage · Binance.US · Serper (news)           │
        │  S3: futures-bars/ (daily+intraday) · fmp/ ·         │
        │     newsapi/ · crypto-tick/ · crypto-candles/ ·      │
        │     news-archive/                                    │
        │  DynamoDB (futures): CONTRACT# · SESSION# · QUOTE#   │
        │  IBKR historical backfill → S3 futures-bars/*        │
        │  Contract resolver → CONTRACT#<sym> + S3 contracts/  │
        │    (full chain + rollover schedule)                  │
        │  Session calendar → SESSION#<sym> + S3 sessions/     │
        │  L1 tick recorder (clientId 74, RTH) → S3            │
        │    futures-ticks/* + QUOTE#<sym>  [IN PROGRESS]      │
        └──────────────────────────┬───────────────────────────┘
                               │ data / signals
                               ▼
                     ┌─────────────────────┐
                     │  STRATEGY RUNNER     │
                     │  (3 bots, Hermes cron)│
                     │  live.py        23:00 │  index MES/MNQ (Donchian + RSI2)
                     │  live_bondsfx   KILLED│  bonds ZB/ZN (disarmed)
                     │  live_intraday  */15  │  intraday MES (RTH)
                     └──────────┬──────────┘
                                │ TradeIntent (deterministic signal_id/intent_id)
                                ▼
                     ┌──────────────────────┐
                     │ RISK / ADMISSION      │
                     │  kill switch (fail-   │
                     │   closed)             │
                     │  daily loss cap       │
                     │  portfolio/inst/strat │
                     │   limits              │
                     │  stale-signal + data- │
                     │   health gate         │
                     │  session + account-id │
                     │  dedupe / idempotency │
                     └──────────┬───────────┘
                                │ approved intent
                                ▼
                     ┌──────────────────────┐
                     │ EXECUTION MANAGER     │
                     │  order lifecycle      │
                     │  idempotency          │
                     │  partial fills        │
                     │  cancel/replace       │
                     │  timeout → UNKNOWN    │
                     └──────────┬───────────┘
                                ▼
               ┌──────────────────────────────┐
               │         IBKR Gateway :4002   │
               │           (paper MES)        │
               │  native auto-restart + token │
               │  re-login (IBC removed)      │
               └───────────────┬───────────────┘
                               │
                 +─────────────+─────────────+
                 ▼                           ▼
            Orders / Fills              Positions
                 │                           │
                 +─────────────+─────────────+
                               ▼
                     ┌──────────────────────┐
                     │ RECONCILIATION        │
                     │ broker truth vs       │
                     │ internal state        │
                     └──────────┬───────────┘
                                │
                +───────────────+───────────────+
                ▼                               ▼
        ┌──────────────┐               ┌───────────────┐
        │ OPERATIONAL   │               │ RISK LEDGER   │
        │ STATE         │               │ (persistent)  │
        │ DynamoDB:     │               │ daily P&L     │
        │ intents/orders│               │ exposure      │
        │ positions     │               │ loss limits   │
        └──────┬───────┘               │ equity        │
               │                       └──────┬────────┘
               +──────────────+───────────────+
                              ▼
                    ┌──────────────────────┐
                    │ OBSERVABILITY        │
                    │  Dashboard :8501     │
                    │  health watchdog:    │
                    │   GWClient + :4002   │
                    │  Telegram (user)     │
                    │  heartbeats + alerts │
                    └──────────────────────┘

     CONTROL PLANE (out-of-band, fail-closed)
     ┌──────────────┐      ┌───────────────────────┐
     │ Laptop       │ ───▶ │ Webhook :8644 (HMAC)  │
     │ (director)   │      │ → VPS Hermes (exec)   │
     └──────────────┘      └───────────────────────┘
             ▲                       │
             └──── Telegram group ────┘  (user visibility, not transport)""", language="text")

    st.markdown("#### Current → Target delta")
    st.markdown("""
- no TradeIntent layer → add it (strategies express intent, don't call broker)
- no Execution Manager → centralize order submission (idempotency, timeout=UNKNOWN)
- no Reconciliation → broker = source of truth for positions/orders/fills
- risk state stateless per-run → persistent Risk Ledger
- IBC-based gateway → native auto-restart + token re-login ✅ **[NOW DONE]**
- control plane fail-open → fail-closed (unreadable state = HALT) ✅ **[NOW DONE]**
- no fill verification → verify fill before writing position/stop ✅ **[NOW DONE]**
""")

# ============================ ROADMAP TAB ============================
with tab_road:
    st.subheader("Build roadmap & checklist")
    st.caption("Phase 1 = futures (paper). 100% paper until edges earn trust. Crypto tabled.")

    st.markdown("#### ✅ Checklist (current state)")
    st.markdown("""
| Area | Item | Status |
|---|---|---|
| Infra | EC2 t3.small (us-east-1) + 2GB swap + Elastic IP (52.7.95.127) | done |
| Infra | CloudFormation IaC + SSM secrets | done |
| Infra | DynamoDB `trading-data` + S3 `trading-datalake-920641308584` | done |
| Infra | Hermes gateway (systemd) + webhook :8644 (laptop→VPS) | done |
| IBKR | Native IB Gateway auto-restart + token re-login (IBC removed, 263bd24) | done |
| IBKR | MES paper round-trip filled | done |
| IBKR | Real-time CME/CBOT L1 → paper DUR193467 | done |
| Bots | live.py (index MES/MNQ, 23:00 UTC) — PROMOTED | done |
| Bots | live_bondsfx.py (bonds ZB/ZN, 23:05 UTC) | KILLED (Gate-1: dies at 1-tick slip) |
| Bots | live_intraday.py (intraday MES, */15 RTH) | done |
| Bots | Kill switch (control.py) read by all 3 bots before order | done |
| Bots | Cross-bot guard (intraday stands down if daily holds MES) | done |
| Bots | Same-day RUN# dedupe guard | done |
| Bots | Control plane fail-open → fail-closed | done (0b769c9) |
| Bots | Dashboard set_control flag-wipe → read-modify-write | done (2f5ba70) |
| Bots | Flatten per-bot → global (ack-based) | done (766b694) |
| Bots | Risk-engine guardrails dead code → wired + persistent | done (0e66637) |
| Bots | Sizing cap silent breach → enforced (returns 0) | done (434cca1) |
| Bots | Exit race double-fill → cancel-then-close | done (40eefb9) |
| Bots | Non-deterministic hash() → hashlib.md5 | done (2b4906f) |
| Bots | _reconcile must not flatten daily MES | done (3f53bbe) |
| Bots | Fill verification before writing position/stop | done (0858c77) |
| Bots | MarketOrder/StopOrder to module scope (latent NameError) | done (b9576e7) |
| Bots | status_report sk time parsing | done (9a14de8) |
| Bots | datetime.utcnow() → timezone-aware | done (614a47b) |
| Bots | pytest suite (47 safety-invariant + regression tests) | done (fc99d8f) |
| Bots | Dashboard crash: lazy-import ib_insync in control.py | done (e68ee33) |
| Risk | Persistent risk state (survive restart) — RISK#&lt;date&gt;/&lt;scope&gt; ledger, load-on-start, fail-closed | done |
| Risk | Daily loss cap fully functional end-to-end (persisted accounting, checked before every entry, survives restart) | done |
| Strategy | ES breakout backtest PF 2.73, MaxDD -7.9% | done |
| Strategy | Walk-forward/OOS: Donchian long PF 2.08/2.16 (ES/NQ n=59/53), ADX 2.55/1.77 (thin) | done |
| Strategy | First paper signals fired (index 23:00 + bonds 23:05 UTC — flat, no entry, expected) | done |
| Strategy | Gate-1 decision: index LONG PROMOTED, bonds fade-SHORT KILLED, BBAND_INDEX_LONG skipped, screening CLOSED | done |
| Data | Historical backfill → S3 futures-bars: 12 sym (ES/NQ/MES/MNQ/RTY/YM/ZB/ZN/ZF/ZT/UB/TN), daily ~3y index / ~16mo rates + intraday 1h/15m/5m/1m | done |
| Data | S3 cold-archive (7 gaps closed) | done |
| Data | Research ingest (FMP/NewsAPI/crypto → S3) | done |
| Data | Data-lake build-out (contract metadata + rollover, session calendar, L1 tick recorder) | done |
| Data | Broker reconciliation (startup + periodic 45s daemon) — positions/orders/fills vs DynamoDB, halt+alert on mismatch/UNKNOWN | done |
| Data | Data-health gate + stale-signal gate | next phase |
| Obs | Streamlit dashboard :8501 (Live + Architecture + Roadmap) | done |
| Obs | Telegram group (user visibility) | done |
| Obs | Daily summary 23:45, health watchdog */30, weekly scan | done |
| Obs | Health watchdog fixed — native GWClient + :4002 check (was checking removed IBC) | done |
| Obs | Reconcile daemon (clientId 76, 45s → RECONCILE/system) + */5 watchdog → Telegram | done |
| Obs | Heartbeats, severity levels, correlation IDs, daily report | next phase |
| Ops | Cron split (data=crontab, bots=Hermes cron) | done |
| Ops | Verify ideas online before proposing/implementing | standing rule |
| Ops | Research-First (verify edges before implementing) | standing rule |
| Ops | Continuous-Documentation (docs/ + dashboard kept current) | standing rule |
""")

    st.markdown("#### ❌ Tabled / blocked")
    st.markdown("""
| Item | Why |
|---|---|
| Crypto | user distrust — deferred |
| Live futures | needs capital + proven edge |
| Options (Robinhood L2) | defer until futures edge trusted |
| Schwab API | ON HOLD (pending API approval — re-evaluate when it arrives) |
| Discount-broker day-margin | rejected (wipeout risk) |
""")

    st.markdown("#### 🔬 Research enhancement (FUTURE)")
    st.markdown("""\
| # | Item | Depends on | Status |
|---|---|---|---|
| R1 | FinBERT sentiment layer over NewsAPI/Serper/X headlines | `HF_TOKEN` | FUTURE |
| R2 | finance-embeddings → Pinecone semantic search / RAG | `PINECONE_API_KEY` | FUTURE |
| R3 | FinGPT (LLM sentiment) | HF token / GPU | FUTURE (later) |
| R4 | X/Twitter v2 social sentiment | X API key | FUTURE |
| R5 | Options flow (Robinhood L2) + SEC EDGAR filings | Robinhood MCP + EDGAR | FUTURE |
| R6 | HF datasets for research/backtest | `HF_TOKEN` | FUTURE |
""")

    st.markdown("#### 🗺️ Roadmap (refocused — Gate-1 decision, 2026-08-14)")
    st.markdown("""
**Strategy question CLOSED — one independent edge:**
- **INDEX LONG = PROMOTED** ✅ — Donchian + RSI2-LONG (live.py) is the live-capital candidate. Honest numbers: Donchian PF 1.56 full / 1.52 OOS / 1.43 @3t; RSI2-LONG 1.99 / 2.57 / 1.88 @3t (corr 0.002 → independent bets).
- **BONDS fade-SHORT = KILLED** 🛑 — dies at 1-tick slippage (S3 re-run + validate_edges.py agree); live_bondsfx.py disarmed, cron paused.
- **BBAND_INDEX_LONG = SKIPPED** — redundant with RSI2-LONG (corr 0.69, 73% trade overlap); revisit only if RSI2-LONG underperforms live.
- **Screening CLOSED** — weekly scan paused; no new strategy screening.

**Path to live capital (in order):**
1. Execution-layer hardening — broker reconciliation ✅ DONE (Phase 2) + execution manager (Phase 3, next).
2. Persistent risk ledger — restart-safe daily P&L + loss cap. ✅ DONE (Phase 1)
3. Paper-forward the index edge (live.py) until Gate 5 (paper validation) passes.
4. Micro-live — min size, hard loss limit, tested kill.
""")

    st.markdown("#### 🎯 Promotion gates → live (only after all above)")
    st.markdown("""
1. Strategy validity (OOS, fees, slippage, sensitivity, regime, correlation) — ✅ answered (index LONG = sole edge)
2. Execution validity (exec manager, order state machine, idempotency)
3. Risk validity (persistent ledger, functional caps, kill + flatten verified)
4. Operational validity (restart-safe, reconciliation, heartbeats, monitoring)
5. Paper validation (min days/trades, no reconciliation incidents, fill quality)
6. Shadow mode (real signals, no submission)
7. Micro-live (min size, hard loss limit, tested kill + rollback)
""")

st.caption(f"Updated {dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M')} UTC · Data: DynamoDB `trading-data` · S3 `trading-datalake-920641308584`")
