"""Trading system dashboard — read-only cockpit + safe controls + architecture/roadmap.

Reads live data from DynamoDB. Controls write flags to DynamoDB that the
bot reads. No arbitrary order entry here.
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
from dashboard.pulse import render_pulse, render_data_hot, render_data_cold
from dashboard.trading_view import render_trading

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
NY = ZoneInfo("America/New_York")   # display timezone (ET)

ARCH_HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "assets", "architecture.html")


def _load_architecture_html():
    """Read assets/architecture.html (SVG topology) for the Architecture tab."""
    try:
        with open(ARCH_HTML_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

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


def _scan_all(filter_expr):
    """Paginated scan — a single table.scan() returns ONE page (<=1MB); the
    table has grown past that, so loop LastEvaluatedKey to avoid silently
    missing rows (same bug class as hardening/reconciler.py::_scan_prefix)."""
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
    """All currently-open positions (POSITION#* items with pos>0)."""
    items = _scan_all(Attr('pk').begins_with('POSITION#') & Attr('sk').eq('current'))
    return [it for it in items if int(it.get('pos', 0)) > 0]


@st.cache_data(ttl=15)
def scan_signals(limit=30):
    """Recent signals across all strategies (SIGNAL#* items), newest first."""
    items = _scan_all(Attr('pk').begins_with('SIGNAL#'))
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

tab_trade, tab_pulse, tab_data_hot, tab_data_cold, tab_sched, tab_live, tab_arch, tab_road = st.tabs(
    ["📈 Trading", "💓 Live Pulse", "🔥 Data — Hot", "🧊 Data — Cold",
     "🗓️ 24/7 Schedule", "📊 Live", "🗺️ Architecture", "📋 Roadmap"])

# ============================ TRADING TAB ============================
with tab_trade:
    render_trading()

# ============================ LIVE PULSE TAB ============================
with tab_pulse:
    render_pulse()

# ============================ DATA — HOT TAB ============================
with tab_data_hot:
    render_data_hot()

# ============================ DATA — COLD TAB ============================
with tab_data_cold:
    render_data_cold()

# ============================ 24/7 SCHEDULE TAB ============================
with tab_sched:
    st.subheader("🗓️ 24/7 Schedule — the machine's rhythm (all times ET)")
    st.caption("Source of truth: system crontab (`infra/crontab.txt` + `data_engine/crontab.txt`) "
               "and Hermes cron (`~/.hermes/cron/jobs.json`). Everything below is live on this VPS.")

    st.markdown("#### 🌍 Market sessions — who's open when")
    st.markdown("""| Market | Venue | Session | ET window |
|---|---|---|---|
| Crypto | Binance.US | **24/7/365** | always |
| Forex spot | interbank | 24/5 | Sun **17:00** → Fri **17:00** |
| Futures | CME Globex | 24/5 | Sun **18:00** → Fri **17:00** (reopens Sun 17:00 CT) |
| US Equities (RTH) | NYSE/Nasdaq | Mon–Fri | **09:30 → 16:00** |""")

    st.markdown("#### ⏱️ The 24/7 clock — what fires when (ET)")
    st.markdown("""| ET | What runs | Layer |
|---|---|---|
| **every 45s** | reconcile-daemon → `RECONCILE/system` (broker vs state) | systemd |
| **every 5m** | reconcile watchdog → Telegram on non-MATCH | Hermes cron |
| **every 10m** | crypto_tick.py → Binance.US L1 ticks (`QUOTE#` + `crypto-tick/`) | system crontab |
| **every 30m** | IB Gateway health watchdog → Telegram | Hermes cron |
| **every 30m** | crypto signal lanes (sweep + Donch200) — signal-only, local | Hermes cron |
| **every 30m** | market_research.py → news sentiment (`NEWS#`) | system crontab |
| **Mon–Fri */15, 09:00–16:45** | intraday MES (FADESHORT + DONCH15); bot self-gates entries 09:30–15:30, flatten 15:45 | Hermes cron |
| **Mon–Fri 09:30–16:00** | futures L1 tick recorder (clientId 74) → `futures-ticks/` | systemd |
| 21:15 | ~~data engine: US stocks daily (~6.9k)~~ ⛔ PAUSED — pivoted to IBKR | system crontab |
| 22:00 | ~~data engine: liquid rank top-1000~~ ⛔ PAUSED (list still used by IBKR collector) | system crontab |
| 22:30 / 22:45 | ~~data engine: 1h/1m intraday~~ ⛔ PAUSED — pivoted to IBKR | system crontab |
| — (resumable) | **IBKR full-depth backfill** → `ibkr/*` (futures daily → crypto → equities daily 20y+ → 1-min) | `run_ibkr_full_backfill.sh` |
| 00:00 | IB Gateway native auto-restart (token re-login, no 2FA) | systemd |
| Sun 08:00 | ~~data engine: universe refresh (~7k)~~ ⛔ PAUSED (universe list still cached + used by IBKR collector) | system crontab |
| Sun 09:00 | IB Gateway weekly cold restart → 2FA re-login | systemd timer |
| 17:00 | ingest.py (daily aggregates) | system crontab |
| 17:45 | options_chains.py (futures options metadata) | system crontab |
| 18:00 | fred_collect.py (macro) | system crontab |
| 18:15 | fmp_ingest.py (quote/profile) | system crontab |
| 18:30 | yf_collect.py (ETFs/sectors/futures/**fx+crosses**/crypto — daily + 1h) | system crontab |
| 18:45 | newsapi_ingest.py | system crontab |
| **19:00** | **live.py — index EOD** (MES/MNQ Donchian + RSI2) | Hermes cron |
| 19:10 | live_gc.py (gold momentum — PAPER EXEC: GC Donchian L/S + TSMOM) | Hermes cron |
| 19:15 | equity_signals.py (equities, signal-only) | Hermes cron |
| 19:20 | daily_collect.py (futures bars) | system crontab |
| 19:45 | daily trading summary → Telegram | Hermes cron |""")

    st.markdown("#### 🔴 Honest 24/7 gap (stated plainly)")
    st.warning("""**Saturday = crypto only.** Crypto is the *only* market trading on Saturdays, and
**crypto has 0 validated edge** (the promoted Donchian-20+200d is a buy-and-hold proxy,
LOWEST live-priority) **and the owner distrusts it** → it runs as a **paper-only signal
lane** (execution `NONE`, no live trades). **Everything else reopens Sunday evening** —
forex ~17:00 ET, futures Globex 18:00 ET, equities Monday.

**This is not passivity — it's the market calendar + no-edge.** The machine never stops:
crypto ticks, news, health watchdogs, and the reconcile daemon run 24/7/365 regardless.""")
    st.info("""**Sunday-globex correction:** futures are NOT closed until Monday — CME Globex
**reopens Sunday 18:00 ET** (17:00 CT). `live.py` fires **daily at 19:00 ET
(includes Sunday)**, so tonight it evaluates the freshly-reopened Sunday globex session
(~1h of new price action). It does **not** skip Sunday.""")

    st.markdown("#### ⏸️ Paused (kept, not running)")
    st.markdown("""| Job | Why |
|---|---|
| Paper signals — bonds (19:05 ET) | SHELVED (Gate-1: dies at 1-tick slip) |
| Weekly strategy scan (Sun 14:00 ET) | screening CLOSED (Gate-1) |""")

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
    st.subheader("System architecture — AS-BUILT (the running system)")
    st.caption("Hardening DONE — this IS the running architecture: strategy → risk/admission → "
               "execution manager → IBKR → reconcile → risk ledger. No \"target-only\" layers remain.")

    _arch = _load_architecture_html()
    if _arch:
        st.caption("🗺️ Primary view — full SVG topology (laptop → VPS → IBKR → AWS → Telegram). "
                   "Solid = trade path · dashed = broker-truth / state. Scroll to explore.")
        st.components.v1.html(_arch, height=880, scrolling=True)
    else:
        st.warning("assets/architecture.html not found — falling back to legacy ASCII.")

    with st.expander("🗜️ Legacy ASCII topology (secondary view)", expanded=False):
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
                     │  live_bondsfx  SHELVED│  bonds ZB/ZN (disarmed)
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

    st.markdown("#### Hardening — all landed & live (as-built)")
    st.markdown("""
- TradeIntent layer ✅ — strategies express intent, don't call broker (deterministic signal_id/intent_id)
- Execution Manager ✅ — centralized order submission (idempotency, timeout=UNKNOWN)
- Reconciliation ✅ — broker = source of truth for positions/orders/fills
- Persistent Risk Ledger ✅ — restart-safe daily P&L + loss cap (never-lose-money)
- IBC-based gateway → native auto-restart + token re-login ✅ **[DONE]**
- control plane fail-open → fail-closed (unreadable state = HALT) ✅ **[DONE]**
- fill verification before writing position/stop ✅ **[DONE]**
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
| Bots | live.py (index MES/MNQ, 19:00 ET) — PROMOTED | done |
| Bots | live_bondsfx.py (bonds ZB/ZN, 19:05 ET) | SHELVED (Gate-1: dies at 1-tick slip; code kept + disarmed) |
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
| Bots | Execution manager (no strategy calls IBKR) + idempotent TradeIntent (signal_id conditional write) | done |
| Bots | MarketOrder/StopOrder to module scope (latent NameError) | done (b9576e7) |
| Bots | status_report sk time parsing | done (9a14de8) |
| Bots | datetime.utcnow() → timezone-aware | done (614a47b) |
| Bots | pytest suite (47 safety-invariant + regression tests) | done (fc99d8f) |
| Bots | Dashboard crash: lazy-import ib_insync in control.py | done (e68ee33) |
| Risk | Persistent risk state (survive restart) — RISK#&lt;date&gt;/&lt;scope&gt; ledger, load-on-start, fail-closed | done |
| Risk | Daily loss cap fully functional end-to-end (persisted accounting, checked before every entry, survives restart) | done |
| Strategy | ES breakout backtest PF 2.73, MaxDD -7.9% | done |
| Strategy | Walk-forward/OOS: Donchian long PF 2.08/2.16 (ES/NQ n=59/53), ADX 2.55/1.77 (thin) | done |
| Strategy | First paper signals fired (index 19:00 + bonds 19:05 ET — flat, no entry, expected) | done |
| Strategy | Gate-1 decision: index LONG PROMOTED, bonds fade-SHORT SHELVED, BBAND_INDEX_LONG TABLED, screening CLOSED | done |
| Strategy | Gate-5 paper-forward validation (index-LONG) — 10 RTH-session execution-correctness gate | STARTED (docs/GATE5_LOG.md) |
| Data | Historical backfill → S3 futures-bars: 12 sym (ES/NQ/MES/MNQ/RTY/YM/ZB/ZN/ZF/ZT/UB/TN), daily ~3y index / ~16mo rates + intraday 1h/15m/5m/1m | done |
| Data | S3 cold-archive (7 gaps closed) | done |
| Data | Research ingest (FMP/NewsAPI/crypto → S3) | done |
| Data | Data-lake build-out (contract metadata + rollover, session calendar, L1 tick recorder) | done |
| Data | Broker reconciliation (startup + periodic 45s daemon) — positions/orders/fills vs DynamoDB, halt+alert on mismatch/UNKNOWN | done |
| Data | Data-health gate + stale-signal gate | next phase |
| Obs | Streamlit dashboard :8501 (Trading charts+logs + Live Pulse + Data — Hot + Data — Cold + Live + Architecture + Roadmap) | done |
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

    st.markdown("#### 📡 Future data subscriptions (when needed)")
    st.markdown("""
| Sub | Unlocks | Status |
|---|---|---|
| L2 market depth | order-flow / depth strategies | NOT needed yet — DB fill in progress |
| Historical options bars | options edges | NOT needed yet — DB fill in progress |
| Deeper futures history >3y | long-run futures research | NOT needed yet — DB fill in progress; **CME DataMine** (3rd-party), NOT an IBKR sub (IBKR caps ~3y index / ~16mo rates); yfinance already covers 10–16y |
""")

    st.markdown("#### 🗺️ Roadmap (refocused — Gate-1 decision, 2026-08-14)")
    st.markdown("""
**Strategy question CLOSED — one independent edge:**
- **INDEX LONG = PROMOTED** ✅ — Donchian + RSI2-LONG (live.py) is the live-capital candidate. Honest numbers: Donchian PF 1.56 full / 1.52 OOS / 1.43 @3t; RSI2-LONG 1.99 / 2.57 / 1.88 @3t (corr 0.002 → independent bets).
- **BONDS fade-SHORT = SHELVED** 📦 — dies at 1-tick slippage (S3 re-run + validate_edges.py agree); code kept + disarmed no-op, cron paused. Revisit only if cost/regime materially changes.
- **BBAND_INDEX_LONG = TABLED** 📦 — paper forward-test candidate (redundant w/ RSI2-LONG, corr 0.69, PF 1.84 / OOS 1.71); revisit if RSI2-LONG underperforms live.
- **Screening CLOSED** — weekly scan paused; no new strategy screening.

**Path to live capital (in order):**
1. Execution-layer hardening — broker reconciliation ✅ (Phase 2) + execution manager & idempotency ✅ (Phase 3).
2. Persistent risk ledger — restart-safe daily P&L + loss cap. ✅ DONE (Phase 1)
3. Paper-forward the index edge (live.py) until Gate 5 (paper validation) passes — **STARTED 2026-08-14** (docs/GATE5_LOG.md).
4. Micro-live — min size, hard loss limit, tested kill.
""")

    st.markdown("#### 🎯 Promotion gates → live (only after all above)")
    st.markdown("""
1. Strategy validity (OOS, fees, slippage, sensitivity, regime, correlation) — ✅ answered (index LONG = sole edge)
2. Execution validity (exec manager, order state machine, idempotency) — ✅ done (Phase 3)
3. Risk validity (persistent ledger, functional caps, kill + flatten verified) — ✅ done (Phase 1)
4. Operational validity (restart-safe, reconciliation, heartbeats, monitoring)
5. Paper validation — Gate 5: 10 RTH sessions, zero execution defects (criteria below + docs/GATE5_LOG.md)
6. Shadow mode (real signals, no submission)
7. Micro-live (min size, hard loss limit, tested kill + rollback)
""")

    st.markdown("#### 🎯 Gate 5 — paper-forward validation (IN PROGRESS)")
    st.markdown("""**Target: 10 RTH sessions of `live.py` index-LONG paper-forward, zero execution defects.**
Gate on execution-correctness per fired signal/cycle (index edge is low-frequency ~12 signals/yr), NOT
signal count — the intraday MES lane supplies execution-volume validation.

| # | Criterion (ALL must hold over the window) |
|---|---|
| (a) | Every fired signal → correct `TradeIntent` → verified fill → reconcile `MATCH` end-to-end |
| (b) | Zero fill-verification failures |
| (c) | Zero **unexplained** HALTs (each must trace to a documented cause) |
| (d) | Risk ledger (`RISK#<date>/<scope>`) persists correctly across restarts |

Tracking: **`docs/GATE5_LOG.md`** · counter resets on any (a)–(d) failure.
""")

    st.markdown("#### 🚧 Micro-live blockers (checklist — do NOT resolve unilaterally)")
    st.markdown("""\
    | # | Blocker | Owner | Status |
    |---|---|---|---|
    | 1 | Live account funding ≥ ~$1.3k (1 MES initial margin + buffer) | OWNER | ⬜ |
    | 2 | Live futures + order-type permissions (MKT + GTC STP) | OWNER | ⬜ |
    | 3 | Live CME L1 real-time entitlement | OWNER | ⬜ |
    | 4 | Gateway/credential swap smoke-test (one live round-trip) | VPS prep | ⬜ |
    | 5 | No flip during backfill / Sun 2FA window (09:00 ET) | VPS prep | ⬜ |

    > #1–#3 are OWNER actions; #4–#5 are VPS preps. This is a **visibility checklist**,
    > not an execution plan — nothing here is resolved unilaterally. Micro-live stays
    > OFF until all five are cleared AND Gate 5 passes. See `docs/MICRO-LIVE-PLAN.md`.
    """)

    _recon = latest("RECONCILE", 1)
    _r = _recon[0] if _recon else {}
    _rst = _r.get("status", "no-data")
    try:
        _rts = dt.datetime.fromtimestamp(int(_r.get("ts")), NY).strftime("%Y-%m-%d %H:%M ET") if _r.get("ts") else "—"
    except (TypeError, ValueError, OSError):
        _rts = "—"
    _ricon = "✅" if _rst == "MATCH" else "⚠️ fail-closed (bots halt on non-MATCH)"
    st.markdown(f"- Reconcile daemon (45s → `RECONCILE/system`): `{_rst}` @ {_rts} {_ricon}")
    st.markdown("- Window: declared 2026-08-14 · first counted RTH session Mon 2026-08-17 · 0/10 sessions.")

st.caption(f"Updated {dt.datetime.now(NY).strftime('%Y-%m-%d %H:%M')} ET · Data: DynamoDB `trading-data` · S3 `trading-datalake-920641308584`")
