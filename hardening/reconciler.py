"""Broker reconciliation — compare IBKR truth vs internal DynamoDB state.

The single most important missing safety box on the path to live capital:
never trust internal bookkeeping when the broker is the source of truth.
Every reconcile returns one of three statuses:

  MATCH    — broker positions/orders/fills agree with internal state.
  MISMATCH — a KNOWN discrepancy (position drift, orphan/missing stop,
             unaccounted fill). Caller must HALT new entries + alert.
  UNKNOWN  — a broker query raised/timed out. Caller must HALT new entries
             (NEVER "assume flat" — a timeout is UNKNOWN, not a rejection).

Callers MUST halt on anything but MATCH (fail-closed).

This module is duck-typed against the `ib` object and the boto3 `table`
double: it imports NEITHER ib_insync NOR boto3 at module scope, so it is
safe to import from the Streamlit dashboard (no asyncio event loop) and to
unit-test with fakes.
"""
from dataclasses import dataclass, field
from datetime import timezone


# Canonical registry of every POSITION# tag the system trades, with the
# implied side when a POSITION row stores no explicit 'side' field (live.py is
# long-only and omits it; live_intraday always stores 'side'). MES_DONCH15 is
# bidirectional so its side MUST be stored — None here means "resolve from the
# row or fail closed".
TRACKED_TAGS = {
    # daily index (long-only)
    'MES_DONCHIAN': 'LONG', 'MES_RSI2': 'LONG',
    'MNQ_DONCHIAN': 'LONG', 'MNQ_RSI2': 'LONG',
    'MES_RSI2PT': 'LONG', 'MNQ_RSI2PT': 'LONG',
    'MES_REV2': 'LONG', 'MNQ_REV2': 'LONG',
    'MYM_DONCHIAN': 'LONG', 'MYM_RSI2': 'LONG',
    'MYM_RSI2PT': 'LONG', 'MYM_REV2': 'LONG',
    # intraday MES
    'MES_FADESHORT': 'SHORT', 'MES_DONCH15': None,
    # VWAP equity-index intraday sleeve (bidirectional — side stored in row)
    'MES_VWAP': None, 'MNQ_VWAP': None,
    # gold momentum (bidirectional — side MUST be stored in the POSITION row,
    # like MES_DONCH15; None here means "resolve from the row or fail closed")
    'GC_DONCHIAN': None, 'GC_TSMOM': None,
    'MGC_DONCHIAN': None, 'MGC_TSMOM': None,
    # bonds fade-SHORT (KILLED at Gate-1, but a lingering position must still resolve)
    'ZB_RSI2SHORT': 'SHORT', 'ZB_BBANDSHORT': 'SHORT',
    'ZN_RSI2SHORT': 'SHORT', 'ZN_BBANDSHORT': 'SHORT',
}

# IBKR equities RSI2 (long-only) — mirror of bot/live_equities.py UNIVERSE.
# Added 2026-08-21 so the reconciler tracks the IBKR equities paper lane
# (bot/live_equities_ibkr.py) instead of flagging its fills/positions as
# unaccounted drift.
_EQUITY_RSI2_SYMBOLS = [
    'SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'XLF', 'XLK', 'XLV', 'XLP', 'XLI',
    'MU', 'NVDA', 'MSFT', 'AAPL', 'AMD', 'TSLA', 'AMZN', 'INTC', 'GOOGL',
    'META', 'AVGO', 'PLTR', 'ORCL', 'AMAT', 'LRCX', 'LLY', 'NOW', 'NFLX',
    'CSCO', 'GEV', 'CAT', 'V', 'WMT', 'JPM', 'CRM', 'XOM', 'TXN', 'GS',
    'JNJ', 'QCOM', 'IBM', 'UNH', 'BAC', 'COST', 'MA', 'T', 'CVX', 'UBER',
    'KO', 'BA', 'ABBV', 'ISRG', 'C', 'ADBE', 'TMO', 'DHR', 'HD', 'MCD',
    'PG', 'BKNG',
]
TRACKED_TAGS.update({f'{_s}_RSI2': 'LONG' for _s in _EQUITY_RSI2_SYMBOLS})

# NEVER-LOSE-MONEY: every open position MUST rest a protective STOP order at the
# broker. There is no per-tag opt-out anymore — the RSI2 buy-dip and intraday
# FADESHORT previously rested no stop (backtest had none); they now rest their
# 2xATR distance as a hard stop. `expected_stops` therefore expects a stop on
# EVERY open position regardless of tag.


class ReconcileQueryError(Exception):
    """Internal state / broker query failed — surface as UNKNOWN."""


def symbol_of(tag: str) -> str:
    """Symbol prefix of a POSITION#/TRADE# tag (e.g. 'MES_DONCHIAN' -> 'MES')."""
    return tag.split('_', 1)[0]


def signed_pos(tag: str, state: dict) -> int:
    """Signed position (+long / -short) for a POSITION# row.

    Raises ValueError (-> UNKNOWN) when an OPEN position has an unresolvable
    side — never guess a direction on real exposure.
    """
    pos = int(state.get('pos', 0) or 0)
    if pos == 0:
        return 0
    side = state.get('side') or TRACKED_TAGS.get(tag)
    if side == 'LONG':
        return pos
    if side == 'SHORT':
        return -pos
    raise ValueError(f"open position tag {tag!r} has no resolvable side")


@dataclass
class ReconcileResult:
    status: str                      # 'MATCH' | 'MISMATCH' | 'UNKNOWN'
    reason: str
    positions: dict = field(default_factory=dict)   # sym -> {'broker': int, 'expected': int}
    open_orders: dict = field(default_factory=dict) # sym -> {'broker': [...], 'expected': [...]}
    unaccounted_fills: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == 'MATCH'


# ---- broker-side queries (duck-typed; raise -> UNKNOWN) ----
def broker_positions(ib) -> dict:
    """symbol -> net signed position at the broker.

    CRYPTO positions (secType=CRYPTO, fractional qty) are EXCLUDED — the crypto
    lane manages its own software stop (IBKR crypto = market/limit only, no native
    stop) and has no integer-contract counterpart in TRACKED_TAGS. ``int(p.position)``
    would crash on a fractional BTC/ETH qty and false-flag a MISMATCH otherwise.
    """
    out = {}
    for p in ib.positions():
        if getattr(p.contract, 'secType', None) == 'CRYPTO':
            continue
        sym = p.contract.symbol
        out[sym] = out.get(sym, 0) + int(p.position)
    return out


def broker_open_orders(ib) -> dict:
    """symbol -> list of {'action','orderType','totalQuantity'} open orders.

    Uses openTrades() (Trade objects carry BOTH .contract and .order).
    openOrders() returns bare Order objects with NO .contract — reading
    .contract off them raises AttributeError the moment any order rests.
    """
    out = {}
    for t in ib.openTrades():
        sym = t.contract.symbol
        out.setdefault(sym, []).append({
            'action': t.order.action,
            'orderType': t.order.orderType,
            'totalQuantity': float(t.order.totalQuantity),
        })
    return out


def broker_executions(ib):
    """Yield (symbol, side, shares, time) for each broker execution/fill.

    Prefers ib.fills() (Fill objects carry .contract.symbol); falls back to
    ib.executions() (Execution objects carry no symbol — skip symbol-less ones
    by resolving via .contract when present, else yield with a placeholder).
    """
    try:
        fills = ib.fills()
    except Exception:
        fills = None
    if fills:
        for f in fills:
            yield _exec_info(f)
        return
    try:
        execs = ib.executions()
    except Exception as e:  # noqa: BLE001
        raise ReconcileQueryError(f"broker executions/fills query failed: {e}") from e
    for e in execs:
        yield _exec_info(e)


def _exec_info(e):
    """Normalize an ib_insync Execution / Fill (or a test double) to
    (symbol, side, shares, time).

    Execution: .symbol (str), .side, .shares, .time.
    Fill:      .contract.symbol, .execution.{side,shares}, .time.
    """
    if hasattr(e, 'contract'):
        sym = e.contract.symbol
    else:
        sym = e.symbol
    if hasattr(e, 'side'):
        side, shares = e.side, e.shares
    else:
        side, shares = e.execution.side, e.execution.shares
    t = getattr(e, 'time', None)
    if t is None:
        t = getattr(getattr(e, 'execution', None), 'time', None)
    return sym, side, shares, t


# ---- internal-side queries ----
def _scan_prefix(table, prefix: str) -> list:
    """Paginated scan for every item whose pk begins with `prefix`.

    CRITICAL: a single table.scan() returns ONE page (<=1MB of scanned data).
    Once the table grows past ~1MB, a non-paginated scan SILENTLY MISSES rows
    that sort into later pages — producing false 'unaccounted fills' (TRADE#)
    and false 'position drift' (POSITION#). Loop LastEvaluatedKey until the
    whole table is covered.
    """
    items = []
    lek = None
    while True:
        kw = dict(FilterExpression='begins_with(pk, :p)',
                  ExpressionAttributeValues={':p': prefix})
        if lek:
            kw['ExclusiveStartKey'] = lek
        try:
            r = table.scan(**kw)
        except Exception as e:  # noqa: BLE001 - fail-closed on read error
            raise ReconcileQueryError(f"internal {prefix} scan failed: {e}") from e
        items.extend(r.get('Items', []))
        lek = r.get('LastEvaluatedKey')
        if not lek:
            break
    return items


def _scan_positions(table):
    """Open POSITION#<tag>/current rows for broker-tracked (futures) tags only.

    Crypto paper-execution (MOM20) writes POSITION#<sym>_MOM20 with a FRACTIONAL
    'pos' (e.g. 0.039992 BTC) and has NO broker counterpart (simulated fills).
    Those rows are skipped — the reconciler only reconciles the integer-contract
    futures tags in TRACKED_TAGS. (Without this filter, int('0.039992') crashes
    the whole reconcile -> UNKNOWN the moment a crypto paper position opens.)
    """
    out = []
    for it in _scan_prefix(table, 'POSITION#'):
        tag = it['pk'].split('#', 1)[1]
        if tag not in TRACKED_TAGS:
            continue
        if int(it.get('pos', 0) or 0) != 0:
            out.append((tag, it))
    return out


def expected_positions(rows) -> dict:
    """symbol -> net signed expected position (sum of internal POSITION# rows)."""
    out = {}
    for tag, state in rows:
        sym = symbol_of(tag)
        out[sym] = out.get(sym, 0) + signed_pos(tag, state)
    return out


def expected_stops(rows) -> dict:
    """symbol -> list of (action, qty) protective STP orders expected to be resting.

    NEVER-LOSE-MONEY: EVERY open position must rest a protective stop. A missing
    stop on any open position = MISMATCH -> halt.
    """
    out = {}
    for tag, state in rows:
        pos = int(state.get('pos', 0) or 0)
        if pos <= 0:
            continue
        side = state.get('side') or TRACKED_TAGS.get(tag)
        action = 'SELL' if side == 'LONG' else 'BUY'   # the stop CLOSES the position
        out.setdefault(symbol_of(tag), []).append((action, pos))
    return out


def broker_stops(open_orders) -> dict:
    """symbol -> list of (action, qty) resting STP orders at the broker."""
    out = {}
    for sym, orders in open_orders.items():
        stops = [(o['action'], int(o['totalQuantity']))
                 for o in orders if o['orderType'] == 'STP']
        if stops:
            out[sym] = stops
    return out


def _internal_traded_today(table, today_iso) -> set:
    """symbols with >=1 internal TRADE# row dated today."""
    out = set()
    for it in _scan_prefix(table, 'TRADE#'):
        sk = it.get('sk', '') or ''
        # live.py sk = 'YYYY-MM-DD#epoch'; live_intraday sk = 'YYYY-MM-DDTHH:MM...'
        if sk.startswith(today_iso):
            out.add(symbol_of(it['pk'].split('#', 1)[1]))
    return out


def _is_utc_today(t, today_iso) -> bool:
    if t is None:
        return True   # no timestamp -> can't rule it out (fail toward detection)
    try:
        if getattr(t, 'tzinfo', None) is not None:
            return t.astimezone(timezone.utc).date().isoformat() == today_iso
        return t.date().isoformat() == today_iso
    except Exception:  # noqa: BLE001
        return True


def _unaccounted_fills(ib, table, today_iso) -> list:
    """Tracked symbols the broker executed today with ZERO internal TRADE# today."""
    broker_traded = set()
    for sym, side, shares, t in broker_executions(ib):
        if sym in {symbol_of(t) for t in TRACKED_TAGS} and _is_utc_today(t, today_iso):
            broker_traded.add(sym)
    internal_traded = _internal_traded_today(table, today_iso)
    return sorted(broker_traded - internal_traded)


# ---- top-level reconcile ----
def reconcile(ib, table, today_iso: str = None) -> ReconcileResult:
    """Compare broker truth vs internal state. Non-MATCH => halt + alert.

    today_iso defaults to the current UTC date; pass it explicitly for tests.
    """
    from datetime import datetime
    today_iso = today_iso or datetime.now(timezone.utc).date().isoformat()

    # 1. broker positions (timeout/error -> UNKNOWN, never "assume flat")
    try:
        bpos = broker_positions(ib)
    except Exception as e:  # noqa: BLE001
        return ReconcileResult('UNKNOWN', f"broker positions query failed: {e}")

    # 2. internal expected positions
    try:
        rows = _scan_positions(table)
        epos = expected_positions(rows)
    except (ReconcileQueryError, ValueError) as e:
        return ReconcileResult('UNKNOWN', str(e))

    # 3. broker open orders
    try:
        borders = broker_open_orders(ib)
    except Exception as e:  # noqa: BLE001
        return ReconcileResult('UNKNOWN', f"broker orders query failed: {e}")

    # 4. compare positions (authoritative gate)
    pos_report = {}
    pos_issues = []
    for sym in sorted(set(bpos) | set(epos)):
        b = bpos.get(sym, 0)
        e = epos.get(sym, 0)
        pos_report[sym] = {'broker': b, 'expected': e}
        if b != e:
            pos_issues.append(f"{sym}: broker {b} vs expected {e}")

    # 5. compare protective stops (orphan / missing)
    estops = expected_stops(rows)
    bstops = broker_stops(borders)
    ord_report = {}
    stop_issues = []
    for sym in sorted(set(bstops) | set(estops)):
        b = sorted(bstops.get(sym, []))
        e = sorted(estops.get(sym, []))
        ord_report[sym] = {'broker': b, 'expected': e}
        if b != e:
            stop_issues.append(f"{sym}: broker stops {b} vs expected {e}")

    # 6. unaccounted fills (executions with no internal TRADE# today)
    try:
        unf = _unaccounted_fills(ib, table, today_iso)
    except ReconcileQueryError as e:
        return ReconcileResult('UNKNOWN', str(e))

    if pos_issues or stop_issues or unf:
        reasons = []
        if pos_issues:
            reasons.append('position drift: ' + '; '.join(pos_issues))
        if stop_issues:
            reasons.append('stop mismatch: ' + '; '.join(stop_issues))
        if unf:
            reasons.append('unaccounted fills: ' + ', '.join(unf))
        return ReconcileResult('MISMATCH', ' | '.join(reasons),
                               positions=pos_report, open_orders=ord_report,
                               unaccounted_fills=unf)

    return ReconcileResult('MATCH', 'broker and internal state agree',
                           positions=pos_report, open_orders=ord_report)
