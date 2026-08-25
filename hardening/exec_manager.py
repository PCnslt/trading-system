"""Execution manager + idempotent TradeIntent (execution-hardening Phase 3).

The last layer between strategy intent and the broker. A strategy NEVER calls
ib_insync directly — it expresses a `TradeIntent`, and the `ExecutionManager`
is the ONLY component that submits orders, tracks order lifecycle, handles
partial fills, and does cancel/replace.

IDEMPOTENCY (the core guarantee):
  - `TradeIntent.signal_id` is a deterministic md5 of the signal's identity
    (scope, tag, symbol, action, side, bar_time, order_type) — the SAME signal
    always yields the SAME id.
  - `IntentStore.accept(signal_id)` does a DynamoDB CONDITIONAL write
    (attribute_not_exists(pk)). If it succeeds, this is the first (and only)
    acceptance of that signal; if it fails, the signal was already accepted and
    the manager returns DUPLICATE without touching the broker.
  => one signal_id -> at most one accepted intent.

FAIL-CLOSED / UNKNOWN: a fill timeout is UNKNOWN, not a rejection. The manager
never assumes an order was rejected on timeout — it reports UNKNOWN and the
caller must query the broker (via the reconciler) before any retry.

ib_insync (MarketOrder/StopOrder) is imported LAZILY inside methods, so this
module is safe to import from the dashboard (no asyncio event loop required),
matching control.py's flatten_ibkr pattern.
"""
import hashlib
import time
from dataclasses import dataclass, field


class ConditionalWriteConflict(Exception):
    """Conditional-write idempotency conflict (raised by test doubles)."""


def _conditional_put(table, item) -> bool:
    """Idempotent put_item. Returns True if newly created, False if the key
    already existed (ConditionalCheckFailed). Re-raises any other error."""
    try:
        table.put_item(Item=item, ConditionExpression='attribute_not_exists(pk)')
        return True
    except ConditionalWriteConflict:
        return False
    except Exception as e:  # noqa: BLE001 - normalize boto3 ClientError
        code = None
        try:
            code = e.response['Error']['Code']
        except (AttributeError, KeyError, TypeError):
            pass
        if code == 'ConditionalCheckFailedException':
            return False
        raise


@dataclass(frozen=True)
class TradeIntent:
    """A deterministic, idempotent expression of intent to trade.

    Frozen + hashable; signal_id/intent_id are pure functions of the fields, so
    a re-run of the same signal produces the same ids (idempotency).
    """
    scope: str          # bot key ('live', 'live_intraday')
    tag: str            # strategy tag ('MES_DONCHIAN')
    symbol: str         # 'MES'
    action: str         # 'BUY' / 'SELL'
    side: str           # 'LONG' / 'SHORT'
    qty: float
    order_type: str     # 'MKT' / 'STP'
    stop_price: float   # 0.0 when no protective stop
    contract_month: str
    bar_time: str       # deterministic signal time (date or bar ts)
    signal_reason: str = ''

    @property
    def signal_id(self) -> str:
        canonical = '|'.join([self.scope, self.tag, self.symbol, self.action,
                              self.side, self.bar_time, self.order_type])
        return hashlib.md5(canonical.encode()).hexdigest()[:16]

    @property
    def intent_id(self) -> str:
        canonical = '|'.join([self.signal_id, str(self.qty),
                              f"{self.stop_price:.4f}", self.contract_month])
        return hashlib.md5(canonical.encode()).hexdigest()[:16]


class IntentStore:
    """Idempotency ledger: one signal_id -> at most one accepted intent.

    Writes INTENT#<signal_id>/accepted with a conditional write; `accept` is
    False on a duplicate. `INTENT#` rows are audit history, never mutated.
    """

    def __init__(self, table):
        self.table = table

    def accept(self, intent: TradeIntent) -> bool:
        item = {
            'pk': f'INTENT#{intent.signal_id}',
            'sk': 'accepted',
            'intent_id': intent.intent_id,
            'scope': intent.scope, 'tag': intent.tag, 'symbol': intent.symbol,
            'action': intent.action, 'side': intent.side, 'qty': intent.qty,
            'order_type': intent.order_type, 'stop_price': str(intent.stop_price),
            'contract_month': intent.contract_month, 'bar_time': intent.bar_time,
            'reason': intent.signal_reason, 'ts': int(time.time()),
        }
        return _conditional_put(self.table, item)

    def was_accepted(self, signal_id: str) -> bool:
        try:
            r = self.table.get_item(Key={'pk': f'INTENT#{signal_id}', 'sk': 'accepted'})
        except Exception as e:  # noqa: BLE001 - fail-closed: treat unreadable as accepted
            return True
        return bool(r.get('Item'))


@dataclass
class ExecutionResult:
    status: str          # FILLED | PARTIAL | REJECTED | UNKNOWN | DUPLICATE
    filled_qty: float = 0.0
    avg_px: float = 0.0
    signal_id: str = ''
    intent_id: str = ''
    detail: str = ''

    @property
    def ok(self) -> bool:
        return self.status in ('FILLED', 'PARTIAL')


class ExecutionManager:
    """The ONLY component that talks to the broker (placeOrder/cancelOrder).

    Centralizes: idempotency, order submission, fill verification, partial
    fills, protective-stop placement, cancel-before-close. A strategy hands it
    a TradeIntent + a qualified contract; it returns an ExecutionResult.
    """

    def __init__(self, ib, table, scope: str):
        self.ib = ib
        self.scope = scope
        self.intents = IntentStore(table)

    # ---- entry ----
    def submit_entry(self, intent: TradeIntent, contract, stop_tif='GTC',
                     take_profit: float = None, fill_timeout=20.0) -> ExecutionResult:
        """Idempotently enter via a NATIVE BRACKET: entry + protective stop (and
        optional take-profit target) are submitted ATOMICALLY as parent+children,
        so the stop is held BROKER-SIDE from the moment of submission and survives
        a bot/gateway crash. This converts never-lose-money from a CODE guarantee
        (place the stop after observing the fill) into a BROKER guarantee (the stop
        is already resting when the entry fills — no naked-position window).

        1. Conditional-write the intent; DUPLICATE if the signal was accepted.
        2. Refuse an unprotected entry (stop_price <= 0) — NEVER-LOSE-MONEY.
        3. Submit the bracket (market parent, transmit=False + stop child, and an
           optional target, OCA-linked so one exit leg cancels the other).
        4. Verify the entry fill (partial-fill aware).
        5. On a definitive REJECTION cancel any still-resting bracket legs; on
           UNKNOWN keep the stop resting (if the entry actually filled it protects
           the position); on a PARTIAL fill re-rest a stop sized to the FILLED qty.
        A fill timeout -> UNKNOWN (never assume rejected).
        """
        # NEVER-LOSE-MONEY: validate the protective stop BEFORE consuming the
        # idempotency key. A rejected no-stop entry must not burn the signal_id
        # (a corrected retry with a stop would otherwise be blocked as DUPLICATE).
        if intent.stop_price <= 0:
            return ExecutionResult('REJECTED', signal_id=intent.signal_id,
                                   intent_id=intent.intent_id,
                                   detail='no protective stop supplied '
                                          '(never-lose-money: refuse unprotected entry)')

        if not self.intents.accept(intent):
            return ExecutionResult('DUPLICATE', signal_id=intent.signal_id,
                                   intent_id=intent.intent_id,
                                   detail='signal already accepted (idempotent)')

        trade = self._place_bracket(contract, intent, stop_tif, take_profit)
        res = self._confirm(trade, intent, fill_timeout)
        if res.status == 'REJECTED':
            # Definitive no-fill: cancel any still-resting bracket legs (defensive;
            # IBKR already cancels children of a rejected/cancelled parent).
            self.cancel_stop(intent.symbol, ref=intent.tag)
            return res
        if res.status == 'UNKNOWN':
            # Keep the bracket stop resting: if the entry actually filled, the stop
            # protects the position; if not, IBKR cancels the child when the parent
            # resolves. Never strip protection on an uncertain fill.
            return res
        if res.status == 'PARTIAL':
            # Right-size the stop to the ACTUAL filled qty (the bracket stop was
            # sized to intent.qty). qty==1 (micros) cannot partially fill, so this
            # is a qty>1 safety path only.
            self.cancel_stop(intent.symbol, ref=intent.tag)
            self._place_stop(contract, intent.side, res.filled_qty,
                             intent.stop_price, stop_tif, ref=intent.tag)
        return res

    def _place_bracket(self, contract, intent: TradeIntent, stop_tif,
                       take_profit: float = None):
        """Submit entry + protective stop (+ optional target) as a native bracket.

        The entry (market, transmit=False) is held at the broker until the last
        child transmits; the stop is linked via `parentId` so it ACTIVATES ON FILL,
        broker-side (no client round-trip to arm the stop). The stop and optional
        target share an OCA group so one exit leg cancels the other. Returns the
        parent Trade (the entry) for fill confirmation.
        """
        from ib_insync import MarketOrder, StopOrder, LimitOrder

        # GTC (not DAY): DAY orders on futures can be held/deferred when placed
        # during Globex-only hours (the index bot enters at 19:00 ET, after the
        # 16:00 ET RTH close) — 4 RSI2 entries timed out unfilled on 2026-08-20.
        parent = MarketOrder(intent.action, intent.qty, tif='GTC')
        parent.transmit = False
        trade = self.ib.placeOrder(contract, parent)

        close_action = 'SELL' if intent.side == 'LONG' else 'BUY'
        oca = f'BRKT-{intent.signal_id}'

        stop = StopOrder(close_action, intent.qty, intent.stop_price, tif=stop_tif)
        stop.parentId = trade.order.orderId
        stop.ocaGroup = oca
        stop.ocaType = 1
        if intent.tag:
            stop.orderRef = intent.tag

        if take_profit and take_profit > 0:
            target = LimitOrder(close_action, intent.qty, take_profit, tif='GTC')
            target.parentId = trade.order.orderId
            target.ocaGroup = oca
            target.ocaType = 1
            stop.transmit = False
            target.transmit = True      # last child transmits the whole chain
            self.ib.placeOrder(contract, stop)
            self.ib.placeOrder(contract, target)
        else:
            stop.transmit = True        # only child -> it transmits the chain
            self.ib.placeOrder(contract, stop)
        return trade

    # ---- exit ----
    def submit_exit(self, intent: TradeIntent, contract, cancel_stop=True,
                    symbol: str = None, fill_timeout=20.0) -> ExecutionResult:
        """Idempotently close an open position (SELL a long / BUY a short).

        Cancels the resting protective stop FIRST (so stop-fill and exit-fill
        can't race), then places a market close and verifies the fill.
        """
        if not self.intents.accept(intent):
            return ExecutionResult('DUPLICATE', signal_id=intent.signal_id,
                                   intent_id=intent.intent_id,
                                   detail='exit signal already accepted (idempotent)')

        sym = symbol or intent.symbol
        if cancel_stop:
            self.cancel_stop(sym, ref=intent.tag)
        from ib_insync import MarketOrder
        trade = self.ib.placeOrder(contract, MarketOrder(intent.action, intent.qty, tif='GTC'))
        return self._confirm(trade, intent, fill_timeout)

    # ---- protective stop ----
    def _place_stop(self, contract, side, qty, stop_price, tif, ref=None):
        from ib_insync import StopOrder
        action = 'SELL' if side == 'LONG' else 'BUY'   # stop closes the position
        order = StopOrder(action, qty, stop_price, tif=tif)
        if ref:
            order.orderRef = ref                      # tag: targeted trail/exit
        self.ib.placeOrder(contract, order)

    def cancel_stop(self, symbol: str, ref: str = None):
        """Cancel protective STP orders for `symbol`.

        ref=None -> cancel every STP order for the symbol (global flatten path).
        ref set  -> cancel only THIS strategy's stop (orderRef == ref), plus any
                    legacy UNTAGGED stop (empty orderRef) so a pre-tagging
                    position still gets its stop cancelled on exit.
        """
        for t in list(self.ib.openTrades()):
            if t.contract.symbol != symbol or t.order.orderType != 'STP':
                continue
            oref = getattr(t.order, 'orderRef', '')
            if ref is not None and oref not in ('', ref):
                continue
            try:
                self.ib.cancelOrder(t.order)
            except Exception as e:  # noqa: BLE001
                print(f"[exec] cancel stop failed ({symbol}): {e}")

    def is_stop_open(self, symbol: str, side: str, ref: str = None) -> bool:
        """True if a protective stop for `symbol` is still resting.

        ref set -> only this strategy's stop counts (orderRef == ref, or a
        legacy untagged stop)."""
        action = 'SELL' if side == 'LONG' else 'BUY'
        return any(
            t.contract.symbol == symbol and t.order.action == action
            and t.order.orderType == 'STP'
            and (ref is None or getattr(t.order, 'orderRef', '') in ('', ref))
            for t in self.ib.openTrades())

    def current_stop_price(self, symbol: str, side: str, ref: str = None):
        """The tightest resting protective-stop price for `symbol`+`side` (or
        only this strategy's stop when `ref` is set), or None if none resting.
        (Long stop = SELL stop; short = BUY.)"""
        action = 'SELL' if side == 'LONG' else 'BUY'
        prices = []
        for t in self.ib.openTrades():
            if (t.contract.symbol == symbol and t.order.orderType == 'STP'
                    and t.order.action == action):
                if ref is not None and getattr(t.order, 'orderRef', '') not in ('', ref):
                    continue
                px = getattr(t.order, 'auxPrice', None)
                if px is not None:
                    prices.append(float(px))
        if not prices:
            return None
        # tightest = highest for a long, lowest for a short
        return max(prices) if side == 'LONG' else min(prices)

    def trail_stop(self, contract, symbol, side, qty, new_stop, ref=None,
                   tif='GTC') -> ExecutionResult:
        """Tighten a resting protective stop: cancel + re-place at `new_stop`.

        TIGHTEN-ONLY GUARD: a long stop may only move UP, a short stop only
        DOWN. If `new_stop` is not an improvement over the currently resting
        stop (or no stop is resting), this is a NOOP — it never loosens a stop
        and never rests a brand-new stop on a position whose stop vanished
        (a missing stop is the reconciler's job to catch, not to silently heal).

        `ref` scopes the guard AND the cancel to this strategy's own stop
        (orderRef == ref, or a legacy untagged stop), so trailing one strategy
        never touches a co-held strategy's stop on the same symbol.
        """
        cur = self.current_stop_price(symbol, side, ref=ref)
        if cur is None:
            return ExecutionResult('NOOP', detail=(
                f'no resting {side} stop for {symbol} to tighten — reconciler owns this'))
        tighter = (new_stop > cur) if side == 'LONG' else (new_stop < cur)
        if not tighter:
            return ExecutionResult('NOOP', detail=(
                f'trail {new_stop:.2f} not tighter than resting {cur:.2f} (tighten-only)'))
        self.cancel_stop(symbol, ref=ref)
        self._place_stop(contract, side, qty, new_stop, tif, ref=ref)
        return ExecutionResult('TRAILED', detail=f'stop tightened {cur:.2f} -> {new_stop:.2f}')

    # ---- fill verification ----
    def _confirm(self, trade, intent: TradeIntent, fill_timeout=8.0) -> ExecutionResult:
        """Broker-confirmed fill; partial-fill aware; timeout -> UNKNOWN.

        A broker REJECTION carries the reason on the Trade's log (IBKR Error 201 etc.).
        Losing it is expensive: on 2026-08-24/25 nine IBKR entries were rejected with
        "BEFORE WE CAN ACCEPT YOUR ORDER IN THIS SECURITY, PLEASE LOGIN TO CLIENT
        PORTAL AND VERIFY USING THE TOKEN WE EMAILED TO YOU" — an account-verification
        gate only the owner can clear — and every one was reported as
        "ENTRY UNKNOWN (timeout) — reconcile will resolve". That hid a hard,
        actionable blocker for two days and made a config problem look like flaky
        infrastructure. Always surface the broker's own words.
        """
        from execution import confirm_fill
        filled, avg_px, status = confirm_fill(self.ib, trade, timeout=fill_timeout)
        broker_msg = self._trade_reject_reason(trade)
        if status == 'Filled':
            if filled <= 0:
                return ExecutionResult('REJECTED', signal_id=intent.signal_id,
                                       intent_id=intent.intent_id,
                                       detail='Filled but zero qty reported')
            st = 'FILLED' if filled == intent.qty else 'PARTIAL'
            return ExecutionResult(st, filled_qty=filled, avg_px=avg_px,
                                   signal_id=intent.signal_id, intent_id=intent.intent_id)
        if status in ('Cancelled', 'ApiCancelled', 'Inactive', 'Rejected'):
            return ExecutionResult('REJECTED', filled_qty=filled, avg_px=avg_px,
                                   signal_id=intent.signal_id, intent_id=intent.intent_id,
                                   detail=f'order {status}'
                                          + (f' — BROKER SAYS: {broker_msg}' if broker_msg else ''))
        # timeout / still open -> UNKNOWN (query broker before any retry). If the
        # broker DID give us a reason, report it here too — a rejection that arrives
        # after the poll window must not be laundered into a bare "timeout".
        return ExecutionResult('UNKNOWN', filled_qty=filled, avg_px=avg_px,
                               signal_id=intent.signal_id, intent_id=intent.intent_id,
                               detail=f'timeout (status={status})'
                                      + (f' — BROKER SAYS: {broker_msg}' if broker_msg else ''))

    @staticmethod
    def _trade_reject_reason(trade):
        """Best-effort extraction of the broker's rejection text from a Trade."""
        try:
            msgs = []
            for e in (getattr(trade, 'log', None) or []):
                m = (getattr(e, 'message', '') or '').strip()
                if m and ('reject' in m.lower() or 'error' in m.lower()
                          or 'not accept' in m.lower() or 'verify' in m.lower()):
                    msgs.append(m)
            return msgs[-1][:300] if msgs else ''
        except Exception:  # noqa: BLE001 - never let diagnostics break execution
            return ''
