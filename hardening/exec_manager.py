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
    qty: int
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
    filled_qty: int = 0
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
    def submit_entry(self, intent: TradeIntent, contract, has_stop=True,
                     stop_tif='GTC', fill_timeout=8.0) -> ExecutionResult:
        """Idempotently enter: BUY (long) or SELL (short) `intent.qty`.

        1. Conditional-write the intent; DUPLICATE if the signal was accepted.
        2. Place a market order.
        3. Verify the fill (partial-fill aware).
        4. On fill, place the protective stop (when has_stop and stop_price>0).
        A fill timeout -> UNKNOWN (never assume rejected).
        """
        if not self.intents.accept(intent):
            return ExecutionResult('DUPLICATE', signal_id=intent.signal_id,
                                   intent_id=intent.intent_id,
                                   detail='signal already accepted (idempotent)')

        from ib_insync import MarketOrder
        trade = self.ib.placeOrder(contract, MarketOrder(intent.action, intent.qty, tif='DAY'))
        res = self._confirm(trade, intent, fill_timeout)
        if res.status in ('REJECTED', 'UNKNOWN') or res.filled_qty <= 0:
            return res
        if has_stop and intent.stop_price > 0:
            self._place_stop(contract, intent.side, res.filled_qty,
                             intent.stop_price, stop_tif)
        return res

    # ---- exit ----
    def submit_exit(self, intent: TradeIntent, contract, cancel_stop=True,
                    symbol: str = None, fill_timeout=8.0) -> ExecutionResult:
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
            self.cancel_stop(sym)
        from ib_insync import MarketOrder
        trade = self.ib.placeOrder(contract, MarketOrder(intent.action, intent.qty, tif='DAY'))
        return self._confirm(trade, intent, fill_timeout)

    # ---- protective stop ----
    def _place_stop(self, contract, side, qty, stop_price, tif):
        from ib_insync import StopOrder
        action = 'SELL' if side == 'LONG' else 'BUY'   # stop closes the position
        self.ib.placeOrder(contract, StopOrder(action, qty, stop_price, tif=tif))

    def cancel_stop(self, symbol: str):
        for o in list(self.ib.openOrders()):
            if o.contract.symbol == symbol and o.order.orderType == 'STP':
                try:
                    self.ib.cancelOrder(o)
                except Exception as e:  # noqa: BLE001
                    print(f"[exec] cancel stop failed ({symbol}): {e}")

    def is_stop_open(self, symbol: str, side: str) -> bool:
        """True if a protective stop for `symbol` is still resting."""
        action = 'SELL' if side == 'LONG' else 'BUY'
        return any(o.contract.symbol == symbol and o.order.action == action
                   and o.order.orderType == 'STP' for o in self.ib.openOrders())

    # ---- fill verification ----
    def _confirm(self, trade, intent: TradeIntent, fill_timeout=8.0) -> ExecutionResult:
        """Broker-confirmed fill; partial-fill aware; timeout -> UNKNOWN."""
        from execution import confirm_fill
        filled, avg_px, status = confirm_fill(self.ib, trade, timeout=fill_timeout)
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
                                   detail=f'order {status}')
        # timeout / still open -> UNKNOWN (query broker before any retry)
        return ExecutionResult('UNKNOWN', filled_qty=filled, avg_px=avg_px,
                               signal_id=intent.signal_id, intent_id=intent.intent_id,
                               detail=f'timeout (status={status})')
