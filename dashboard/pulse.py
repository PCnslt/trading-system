"""Live Pulse — auto-refresh read-only activity view (DynamoDB + S3, light reads).

What it shows (the "machine breathing"):
  1. Real-time quote tiles  — futures L1 (QUOTE#<sym> sk='latest') + crypto
     (QUOTE#<sym> latest tick) with price + change, live.
  2. Signals & trades feed  — last N SIGNAL#/TRADE# entries (strategy, symbol,
     direction, time, fill price).
  3. Data inflow            — today's new S3 objects + last-write per prefix.
  4. Gate 5 progress        — X/10 sessions, live RECONCILE state, days since
     window start, (a)-(d) defects.
  5. Open positions         — live paper positions (flat is the normal state).

GROUND-TRUTH RULE (trading-bot-operations skill): freshness/liveness keys on S3
object timestamps + RECONCILE/RUN# state — NEVER on SIGNAL#/TRADE# presence.
"Ran, no signal / flat" renders as HEALTHY, not "down". The signals/trades feed
is an activity view (what the bots emitted), not a liveness assertion: an empty
trade feed means flat (expected for the low-frequency index edge), not broken.

READ-ONLY: no DynamoDB/S3 writes, no orders, no CONTROL mutation.
"""
import json
import os
import re
import datetime as dt
from zoneinfo import ZoneInfo

import boto3
import streamlit as st
from boto3.dynamodb.conditions import Key, Attr

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DYNAMO_TABLE = os.getenv("DYNAMODB_TABLE", "trading-data")
S3_BUCKET = os.getenv("S3_BUCKET", "trading-datalake-920641308584")
NY = ZoneInfo("America/New_York")   # display timezone (ET)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GATE5_LOG = os.path.join(_REPO_ROOT, "docs", "GATE5_LOG.md")

import sys as _sys
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
from data.symbol_registry import L1_LIVE, ASSET_CLASSES, FUTURES, GAPPED_FX

L1_LIVE_SORTED = sorted(L1_LIVE)              # 23 CME/CBOT live-L1 symbols
DELAYED_L1 = sorted({d["sym"] for d in FUTURES
                     if d["exchange"] in ("NYMEX", "COMEX")})   # 12 delayed (energy+metals)
GAPPED_FX_SORTED = sorted(GAPPED_FX)          # 7 no-entitlement FX majors

FUTURES_QUOTE_SYMS = ["MES", "MNQ", "ES", "NQ", "ZB", "ZN"]
CRYPTO_QUOTE_SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
# The 5 data-inflow prefixes the owner watches (task spec).
INFLOW_PREFIXES = ["futures-bars/", "futures-ticks/", "crypto-tick/", "yf/", "macro/"]

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_table = _dynamodb.Table(DYNAMO_TABLE)
_s3 = boto3.client("s3", region_name=AWS_REGION)

_DIR_EMOJI = {
    "LONG": "🟢", "BUY": "🟢", "UP": "🟢", "GOLDEN": "🟢",
    "SHORT": "🔴", "SELL": "🔴", "DOWN": "🔴", "DEATH": "🔴",
    "EXIT": "🔵", "COVER": "🟣", "NONE": "⚪️",
}


# ============================ tiny utils ============================
def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def _num(v):
    """Decimal / str / float -> float (None-safe). Prices are stored as strings."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _ts(item):
    """Epoch seconds from an item's ts field (Decimal/str/int tolerant)."""
    try:
        return int(float(item.get("ts", 0)))
    except (TypeError, ValueError):
        return 0


def _age_str(ts_epoch):
    """Human age of an epoch ts; '—' if missing/zero."""
    if not ts_epoch:
        return "—"
    age = now_utc().timestamp() - float(ts_epoch)
    if age < 0:
        return "just now"
    m = int(age // 60)
    if m < 1:
        return f"{int(age)}s"
    if m < 60:
        return f"{m}m"
    h = m // 60
    if h < 48:
        return f"{h}h{m % 60:02d}m"
    return f"{h // 24}d"


def _ts_hms(ts_epoch):
    if not ts_epoch:
        return "—"
    try:
        return dt.datetime.fromtimestamp(int(ts_epoch), NY).strftime("%H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return "—"


def _split_tag(tag, item):
    """pk tag (e.g. 'MES_DONCHIAN') -> (symbol, strategy), using the strategy
    field when present, falling back to the bare tag."""
    strat = item.get("strategy") or ""
    sym = tag
    if strat and tag.endswith("_" + strat):
        sym = tag[: -(len(strat) + 1)]
    return sym, strat


# ============================ quotes ============================
@st.cache_data(ttl=1, show_spinner=False)
def _futures_quote(sym):
    r = _table.get_item(Key={"pk": f"QUOTE#{sym}", "sk": "latest"})
    return r.get("Item") or {}


@st.cache_data(ttl=15, show_spinner=False)
def _crypto_quote(sym):
    """(price, change_pct, ts) — change vs today's first tick (00:00 UTC open)."""
    try:
        r = _table.query(KeyConditionExpression=Key("pk").eq(f"QUOTE#{sym}"),
                         ScanIndexForward=False, Limit=1)
        cur = r.get("Items", [None])[0]
    except Exception:
        cur = None
    if not cur:
        return None
    today = now_utc().date().isoformat()
    prev = None
    try:
        rp = _table.query(
            KeyConditionExpression=Key("pk").eq(f"QUOTE#{sym}") & Key("sk").gte(f"{today}T00:00"),
            ScanIndexForward=True, Limit=1)
        prev = rp.get("Items", [None])[0]
    except Exception:
        prev = None
    price = _num(cur.get("price"))
    change = None
    if price is not None and prev is not None:
        op = _num(prev.get("price"))
        if op:
            change = (price - op) / op * 100.0
    return {"price": price, "change_pct": change, "ts": _ts(cur)}


@st.cache_data(ttl=3600, show_spinner=False)
def _futures_prev_closes():
    """Prev daily close per futures sym (futures-bars/daily/<sym>/<latest-date>.json),
    used for the quote tile's 'change vs prev close'. Daily bars barely change."""
    out = {}
    for sym in FUTURES_QUOTE_SYMS:
        latest_date = ""
        try:
            token = None
            while True:
                kw = dict(Bucket=S3_BUCKET, Prefix=f"futures-bars/daily/{sym}/")
                if token:
                    kw["ContinuationToken"] = token
                resp = _s3.list_objects_v2(**kw)
                for o in resp.get("Contents", []):
                    d = o["Key"].rsplit("/", 1)[-1].removesuffix(".json")
                    if d > latest_date:
                        latest_date = d
                if resp.get("IsTruncated"):
                    token = resp.get("NextContinuationToken")
                else:
                    break
        except Exception:
            latest_date = ""
        close = None
        if latest_date:
            try:
                o = _s3.get_object(Bucket=S3_BUCKET,
                                   Key=f"futures-bars/daily/{sym}/{latest_date}.json")
                close = _num(json.loads(o["Body"].read()).get("close"))
            except Exception:
                close = None
        out[sym] = {"close": close, "date": latest_date}
    return out


# ============================ signals / trades ============================
@st.cache_data(ttl=15, show_spinner=False)
def _scan_feed(limit=30):
    """Recent SIGNAL# + TRADE# items merged into one feed, newest first.

    No ProjectionExpression: 'close'/'mode' are DynamoDB RESERVED words and a
    projection touching them throws ValidationException. Items are tiny; the
    full-item scan matches the existing dashboard pattern.
    """
    feed = []
    for pfx in ("SIGNAL#", "TRADE#"):
        try:
            r = _table.scan(FilterExpression=Attr("pk").begins_with(pfx))
            for it in r.get("Items", []):
                it["_kind"] = "signal" if pfx == "SIGNAL#" else "trade"
                feed.append(it)
        except Exception:
            continue
    feed.sort(key=lambda x: _ts(x), reverse=True)
    return feed[:limit]


# ============================ data inflow ============================
@st.cache_data(ttl=120, show_spinner=False)
def _s3_inflow():
    """Per-prefix: today's new object count + last-write ts (bounded, cached)."""
    today = now_utc().date().strftime("%Y-%m-%d")
    out = {}
    for p in INFLOW_PREFIXES:
        today_n = 0
        last_ts = 0
        last_key = None
        total = 0
        truncated = False
        pages = 0
        try:
            token = None
            while pages < 20:  # bound ~20k objects per prefix — first-load stays fast
                kw = dict(Bucket=S3_BUCKET, Prefix=p)
                if token:
                    kw["ContinuationToken"] = token
                resp = _s3.list_objects_v2(**kw)
                pages += 1
                for o in resp.get("Contents", []):
                    total += 1
                    lm = o["LastModified"]
                    if lm.strftime("%Y-%m-%d") == today:
                        today_n += 1
                    if lm.timestamp() > last_ts:
                        last_ts = lm.timestamp()
                        last_key = o["Key"]
                if resp.get("IsTruncated"):
                    token = resp.get("NextContinuationToken")
                else:
                    break
            else:
                truncated = True
        except Exception:
            out[p] = {"error": True, "today": None, "last_ts": None, "last_key": None, "total": None}
            continue
        out[p] = {"today": today_n, "last_ts": last_ts, "last_key": last_key,
                  "total": total, "truncated": truncated}
    return out


# ============================ gate 5 ============================
def _read_gate5():
    """Parse docs/GATE5_LOG.md for the session counter + window dates + defects."""
    info = {"sessions_done": 0, "sessions_total": 10, "declared": None,
            "first_session": None, "defects": [], "present": False}
    try:
        with open(_GATE5_LOG, "r", encoding="utf-8") as f:
            text = f.read()
        info["present"] = True
        # tolerate **bold** markers around the label
        m = re.search(r"Declared:\*{0,2}\s*(\d{4}-\d{2}-\d{2})", text)
        if m:
            info["declared"] = m.group(1)
        m = re.search(r"First counted session:\*{0,2}\s*(\w{3}\s+\d{4}-\d{2}-\d{2})", text)
        if m:
            info["first_session"] = m.group(1)
        m = re.search(r"Sessions completed:\s*(\d+)\s*/\s*(\d+)", text)
        if m:
            info["sessions_done"] = int(m.group(1))
            info["sessions_total"] = int(m.group(2))
        # per-session log rows -> surface recorded (a)-(d) defects
        for line in text.splitlines():
            s = line.strip()
            if not s.startswith("|") or s.startswith("|---") or s.startswith("| #"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 8 or cells[1] in ("", "Date (RTH)", "_(none yet)_", "—"):
                continue
            sid, a, b, c, d, verdict = cells[0], cells[3], cells[4], cells[5], cells[6], cells[-1]
            for label, cell in (("(a)", a), ("(b)", b), ("(c)", c), ("(d)", d)):
                if cell and cell.lower() not in ("—", "-", "ok", "pass", "0", ""):
                    info["defects"].append(f"session {sid} {label}: {cell}")
            if verdict and verdict.lower() not in ("—", "-", "ok", "pass", ""):
                info["defects"].append(f"session {sid}: {verdict}")
    except Exception:
        pass
    return info


@st.cache_data(ttl=15, show_spinner=False)
def _reconcile_state():
    r = _table.get_item(Key={"pk": "RECONCILE", "sk": "system"})
    return r.get("Item") or {}


@st.cache_data(ttl=15, show_spinner=False)
def _control_state():
    r = _table.get_item(Key={"pk": "CONTROL", "sk": "system"})
    return r.get("Item") or {}


@st.cache_data(ttl=15, show_spinner=False)
def _open_positions():
    try:
        r = _table.scan(FilterExpression=Attr("pk").begins_with("POSITION#"))
        items = r.get("Items", [])
    except Exception:
        return [], True
    open_rows = [it for it in items if _num(it.get("pos")) not in (None, 0)]
    return open_rows, False


# ============================ render ============================
def _quote_tile(sym, price, change, sub, note):
    delta = None
    if change is not None:
        delta = f"{change:+.2f}%"
    lbl = f"**{sym}**"
    if price is None:
        st.metric(lbl, "—", delta=None, help=note or "no live data")
    else:
        st.metric(lbl, f"${price:,.4f}" if price < 10 else f"${price:,.2f}",
                  delta=delta, delta_color="normal", help=note or "")
    if sub:
        st.caption(sub)


def _render_quotes():
    st.subheader("🟢 Real-time quotes")
    # futures
    st.markdown("**Futures — L1** (CME/CBOT, RTH 09:30–16:00 ET)")
    prev = _futures_prev_closes()
    fcols = st.columns(len(FUTURES_QUOTE_SYMS))
    for col, sym in zip(fcols, FUTURES_QUOTE_SYMS):
        with col:
            q = _futures_quote(sym)
            last = _num(q.get("last"))
            bid = _num(q.get("bid"))
            ask = _num(q.get("ask"))
            price = last if last is not None else ((bid + ask) / 2 if (bid and ask) else None)
            pc = prev.get(sym, {}).get("close")
            change = ((price - pc) / pc * 100.0) if (price is not None and pc) else None
            sub = None
            note = None
            if q:
                bb = f"{bid:,.2f}" if bid is not None else "—"
                aa = f"{ask:,.2f}" if ask is not None else "—"
                sub = f"bid {bb} · ask {aa} · {_age_str(_ts(q))} ago"
                note = f"L1 (clientId 74). Prev close {pc} ({prev.get(sym, {}).get('date')})"
            else:
                note = "No L1 snapshot yet — recorder RTH-idle (first session Mon 09:30 ET)"
            _quote_tile(sym, price, change, sub, note)
    # crypto
    st.markdown("**Crypto — Binance.US**")
    ccols = st.columns(len(CRYPTO_QUOTE_SYMS))
    for col, sym in zip(ccols, CRYPTO_QUOTE_SYMS):
        with col:
            cq = _crypto_quote(sym)
            if cq:
                _quote_tile(sym, cq["price"], cq["change_pct"],
                            f"{_age_str(cq['ts'])} ago", "change vs 00:00 UTC open")
            else:
                _quote_tile(sym, None, None, None, "no crypto tick yet")


def _render_feed():
    st.subheader("🔔 Signals & trades — live feed")
    feed = _scan_feed(30)
    if not feed:
        st.caption("No signals or trades yet — flat (normal for the low-frequency index edge).")
        return
    for it in feed:
        tag = it["pk"].split("#", 1)[-1]
        sym, strat = _split_tag(tag, it)
        if it["_kind"] == "trade":
            direction = it.get("side", "—")
            px = _num(it.get("entry")) if _num(it.get("entry")) is not None else _num(it.get("exit_px"))
            qty = it.get("qty", "—")
            lbl = f"{_DIR_EMOJI.get(direction, '⚪️')} `{tag}` — **{direction}** {qty}"
            if px is not None:
                lbl += f" @ {px:,.2f}"
            stop = _num(it.get("stop"))
            if stop:
                lbl += f" · stop {stop:,.2f}"
            reason = str(it.get("reason", ""))[:80]
            st.markdown(f"{lbl} · `{_ts_hms(_ts(it))} ET` · {reason}")
        else:
            direction = it.get("signal", "—")
            close = _num(it.get("close"))
            mode = it.get("mode", "")
            venue = it.get("venue", "")
            lbl = f"{_DIR_EMOJI.get(direction, '⚪️')} `{tag}` — **{direction}**"
            if close is not None:
                lbl += f" · close {close:,.2f}"
            if mode:
                lbl += f" · `{mode}`"
            reason = str(it.get("reason", ""))[:90]
            st.markdown(f"{lbl} · `{_ts_hms(_ts(it))} ET` · {reason}")


def _render_inflow():
    st.subheader("📥 Data inflow — today's S3 objects")
    inflow = _s3_inflow()
    rows = []
    for p in INFLOW_PREFIXES:
        d = inflow.get(p, {})
        name = p.rstrip("/")
        if d.get("error"):
            rows.append((name, "⚠️ read error", "—", ""))
            continue
        last = dt.datetime.fromtimestamp(d["last_ts"], NY).strftime(
            "%H:%M ET") if d.get("last_ts") else "—"
        ttl_suffix = " (≥)" if d.get("truncated") else ""
        rows.append((name, f"{d.get('today', 0)}{ttl_suffix} new today",
                     last, f"total {d.get('total', 0)}"))
    st.table([("prefix", "today", "last write", "total")] + rows)
    st.caption("“today” = objects LastModified today (UTC). Bulk backfills inflate the "
               "count — it reflects live write activity, not steady-state inflow.")


def _render_gate5():
    st.subheader("🚦 Gate 5 — paper-forward validation")
    g = _read_gate5()
    rec = _reconcile_state()
    done = g["sessions_done"]
    total = g["sessions_total"] or 10
    st.progress(min(done / total, 1.0))
    st.markdown(f"**{done}/{total} sessions** "
                f"· window declared {g['declared'] or '—'}")
    if g["declared"]:
        try:
            days = (now_utc().date() - dt.date.fromisoformat(g["declared"])).days
            st.caption(f"Days since window start: {days} · "
                       f"first counted session: {g['first_session'] or '—'}")
        except ValueError:
            pass
    # live reconcile = the (a)/(c) ground truth (daemon writes every 45s)
    rst = rec.get("status", "no-data")
    rts = _ts_hms(_ts(rec))
    if rst == "MATCH":
        st.success(f"Reconcile: `MATCH` @ {rts} ET — broker and internal state agree")
    else:
        st.error(f"Reconcile: `{rst}` @ {rts} ET — fail-closed (bots halt)")
        if rec.get("reason"):
            st.caption(rec.get("reason"))
    # (a)-(d) criteria — live signal for (a), log-tracked for the rest
    if g["defects"]:
        st.error("⚠️ (a)–(d) defect(s) recorded in GATE5_LOG.md — counter reset:")
        for d in g["defects"]:
            st.markdown(f"- {d}")
    elif not g["present"]:
        st.warning("GATE5_LOG.md not found — tracking file missing")
    else:
        st.markdown(
            "Criteria **(a)** fill→MATCH ✅ · **(b)** fill-verify ✅ · **(c)** no unexplained HALTs ✅ · "
            "**(d)** ledger persists ✅ — *counter resets on any defect (tracked in `docs/GATE5_LOG.md`).*")


def _render_positions():
    st.subheader("📊 Open positions")
    rows, err = _open_positions()
    if err:
        st.warning("Could not read POSITION# state (read error).")
        return
    if not rows:
        st.success("All flat — 0 open positions (paper).")
        return
    for p in rows:
        tag = p["pk"].split("#", 1)[-1]
        side = p.get("side", "LONG")
        pos = _num(p.get("pos")) or 0
        entry = _num(p.get("entry"))
        stop = _num(p.get("stop"))
        arrow = "▲" if side == "LONG" else "▼"
        st.markdown(f"{arrow} **{tag}** — {int(pos)} {side.lower()} "
                    f"· entry {entry if entry is not None else '—'} "
                    f"· stop {stop if stop is not None else '—'}")


@st.fragment(run_every="5s")
def render_pulse():
    """The whole Live Pulse panel, auto-refreshing every 5s."""
    st.caption(f"Auto-refresh 5s · read-only · "
               f"updated {dt.datetime.now(NY).strftime('%H:%M:%S')} ET · "
               f"DynamoDB `{DYNAMO_TABLE}` + S3 `{S3_BUCKET}`")
    _render_quotes()
    st.divider()
    c1, c2 = st.columns([3, 2])
    with c1:
        _render_feed()
    with c2:
        _render_inflow()
    st.divider()
    c3, c4 = st.columns([2, 1])
    with c3:
        _render_gate5()
    with c4:
        _render_positions()


# ============================ DATA — HOT (live tick/quote) ============================
def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _render_l1_tile(sym):
    q = _futures_quote(sym)
    bid = _num(q.get("bid"))
    ask = _num(q.get("ask"))
    last = _num(q.get("last"))
    bsz = q.get("bidSize")
    asz = q.get("askSize")
    lsz = q.get("lastSize")
    vol = q.get("volume")
    price = last if last is not None else ((bid + ask) / 2 if (bid is not None and ask is not None) else None)
    if price is None:
        st.metric(sym, "—", help="no L1 snapshot yet (recorder RTH-idle)")
        st.caption("—")
        return
    spread = (ask - bid) if (bid is not None and ask is not None) else None
    help_txt = "last"
    if lsz is not None:
        help_txt += f" · lastSize {lsz}"
    if vol is not None:
        help_txt += f" · vol {vol}"
    st.metric(sym, f"{price:,.2f}", help=help_txt)
    sub = f"bid {bid:,.2f} · ask {ask:,.2f}" if (bid is not None and ask is not None) else "bid/ask —"
    if spread is not None:
        sub += f" · sp {spread:,.2f}"
    if bsz is not None and asz is not None:
        sub += f" · {bsz}x{asz}"
    sub += f" · {_age_str(_ts(q))} ago"
    st.caption(sub)


def _render_honest_limits():
    st.subheader("⚠️ Honest tick-granularity boundary")
    st.info("""
**Second-by-second L1 is available ONLY for the 23 CME+CBOT symbols, RTH Mon–Fri (09:30–16:00 ET).**

| Coverage | Count | Symbols | Tick granularity |
|---|---|---|---|
| 🟢 **Live L1** (CME/CBOT) | 23 | ES NQ MES MNQ RTY M2K YM MYM · ZB ZN ZF ZT UB TN · ZC ZW ZS ZM ZL ZO HE LE · 6M | **second-by-second** (event-driven capture, 1s hot flush) |
| 🟡 **Delayed only** (NYMEX/COMEX energy+metals) | 12 | CL NG RB HO QM QG · GC SI HG PL PA MGC | Error 354 "not subscribed" → **15-min delayed** |
| 🔴 **No entitlement** (CME FX majors) | 7 | 6E 6J 6B 6A 6C 6S 6N | "No security definition" → **cannot quote** |

The recorder subscribes to `L1_LIVE` only, so delayed / no-entitlement symbols are **never recorded as
real-time** — we never fake or pad them. Second-by-second for those needs **separate paid
subscriptions** (CME energy/metals L1 + CME FX-futures L1).
""")


@st.fragment(run_every="3s")
def render_data_hot():
    st.caption(f"Auto-refresh 3s · read-only · DynamoDB `{DYNAMO_TABLE}` · "
               f"updated {dt.datetime.now(NY).strftime('%H:%M:%S')} ET")
    _render_honest_limits()
    st.divider()
    st.subheader("🟢 Live L1 quotes — all 23 symbols (`QUOTE#<sym>` sk=`latest`)")
    st.caption("Recorder clientId 74 · RTH-gated · bid / ask / last / size / volume per tile.")
    groups = {}
    for sym in L1_LIVE_SORTED:
        groups.setdefault(ASSET_CLASSES.get(sym, "?"), []).append(sym)
    for cls in ("index", "rates", "ags", "fx"):
        syms = groups.pop(cls, None)
        if not syms:
            continue
        st.markdown(f"**{cls.upper()}** ({len(syms)})")
        for row in _chunks(syms, 6):
            cols = st.columns(len(row))
            for col, sym in zip(cols, row):
                with col:
                    _render_l1_tile(sym)
    for cls, syms in sorted(groups.items()):
        st.markdown(f"**{cls.upper()}** ({len(syms)})")
        for row in _chunks(syms, 6):
            cols = st.columns(len(row))
            for col, sym in zip(cols, row):
                with col:
                    _render_l1_tile(sym)
    st.divider()
    st.markdown("**🪙 Crypto — Binance.US** (honest: ~10-min tick cadence, NOT second-by-second)")
    for row in _chunks(CRYPTO_QUOTE_SYMS, 4):
        cols = st.columns(len(row))
        for col, sym in zip(cols, row):
            with col:
                cq = _crypto_quote(sym)
                if cq:
                    _quote_tile(sym, cq["price"], cq["change_pct"], f"{_age_str(cq['ts'])} ago",
                                "change vs 00:00 UTC open")
                else:
                    _quote_tile(sym, None, None, None, "no crypto tick yet")
    st.divider()
    st.subheader("🟡 Delayed / 🔴 no-entitlement (NOT second-by-second — see boundary above)")
    st.markdown(f"**Delayed (12):** `{' '.join(DELAYED_L1)}` — historical bars still collected, L1 not recorded.")
    st.markdown(f"**No entitlement (7):** `{' '.join(GAPPED_FX_SORTED)}` — no security definition on paper.")


# ============================ DATA — COLD (S3 archive) ============================
@st.cache_data(ttl=600, show_spinner=False)
def _s3_cold_inventory():
    """Per top-level S3 prefix: total objects + latest LastModified + latest key (cached 10min)."""
    out = {}
    try:
        top = _s3.list_objects_v2(Bucket=S3_BUCKET, Delimiter="/")
    except Exception:
        return out
    for cp in top.get("CommonPrefixes", []):
        p = cp["Prefix"]
        total = 0
        last_ts = 0.0
        last_key = None
        truncated = False
        pages = 0
        try:
            token = None
            while pages < 5:  # bound ~5000 objects per prefix — first-load stays fast
                kw = dict(Bucket=S3_BUCKET, Prefix=p)
                if token:
                    kw["ContinuationToken"] = token
                resp = _s3.list_objects_v2(**kw)
                pages += 1
                for o in resp.get("Contents", []):
                    total += 1
                    if o["LastModified"].timestamp() > last_ts:
                        last_ts = o["LastModified"].timestamp()
                        last_key = o["Key"]
                if resp.get("IsTruncated"):
                    token = resp.get("NextContinuationToken")
                else:
                    break
            else:
                truncated = True
        except Exception:
            out[p] = {"error": True}
            continue
        out[p] = {"total": total, "last_ts": last_ts, "last_key": last_key, "truncated": truncated}
    return out


@st.cache_data(ttl=600, show_spinner=False)
def _ibkr_inventory():
    """Per-prefix counts under ibkr/ (broker-quality archive). Cached 10min."""
    out = {}
    try:
        top = _s3.list_objects_v2(Bucket=S3_BUCKET, Prefix="ibkr/", Delimiter="/")
        for cp in top.get("CommonPrefixes", []):
            p = cp["Prefix"]
            total = 0
            pages = 0
            token = None
            try:
                while pages < 8:  # bound scan; ibkr/ can be large (1-min month partitions)
                    kw = dict(Bucket=S3_BUCKET, Prefix=p)
                    if token:
                        kw["ContinuationToken"] = token
                    resp = _s3.list_objects_v2(**kw)
                    pages += 1
                    total += len(resp.get("Contents", []))
                    if resp.get("IsTruncated"):
                        token = resp.get("NextContinuationToken")
                    else:
                        break
            except Exception:
                out[p] = {"error": True}
                continue
            out[p] = {"total": total}
    except Exception:
        pass
    return out


def render_data_cold():
    st.subheader("🧊 Cold archive — S3 `trading-datalake-920641308584`")
    st.caption("Every fetch is persisted here (never discarded). Bounded scan (≤5k objects/prefix) — "
               "large prefixes (yf/, futures-bars/) are truncated: counts show ≥ and 'latest write' "
               "reflects the scanned window, not the whole prefix. Freshness/liveness is on Live Pulse.")
    inv = _s3_cold_inventory()
    rows = []
    for p in sorted(inv.keys()):
        d = inv[p]
        name = p.rstrip("/")
        if d.get("error"):
            rows.append((name, "⚠️ read error", "—", "—"))
            continue
        last = dt.datetime.fromtimestamp(d["last_ts"], NY).strftime(
            "%Y-%m-%d %H:%M ET") if d.get("last_ts") else "—"
        ttl = "≥" if d.get("truncated") else ""
        rows.append((name, f"{ttl}{d.get('total', 0)}", last, d.get("last_key") or "—"))
    st.table([("prefix", "objects", "latest write", "latest key")] + rows)

    # Broker-quality /ibkr/ archive sub-breakdown (IBKR-only pivot, quality=BROKER)
    ibkr = _ibkr_inventory()
    if ibkr:
        st.markdown("#### 🏦 IBKR broker archive (`ibkr/`, `quality=BROKER`) — full-depth backfill")
        st.caption("Source of truth (broker-verified, replacing yfinance for broker-available assets). "
                   "Equities daily 20y+ · futures CONTFUT ~3-4y (20y NOT achievable on paper — expired "
                   "contracts don't resolve) · 1-min month-partitioned · crypto micros MBT/MET · options chains.")
        irows = []
        for p in sorted(ibkr.keys()):
            d = ibkr[p]
            irows.append((p.rstrip("/"), "⚠️ read error" if d.get("error") else str(d.get("total", 0))))
        st.table([("ibkr/ sub-prefix", "objects")] + irows)

    st.warning("`futures-ticks/` = 0 objects — the tick recorder has not yet captured a live RTH session "
               "(deployed after Friday RTH close + IB Gateway down since Sat 02:11 ET). First real capture: "
               "the next RTH session after the gateway logs back in.")
