"""Execution manager + idempotent TradeIntent tests (execution-hardening Phase 3).

Covers: deterministic signal_id/intent_id, idempotency (one signal_id -> one
accepted intent via conditional write), fill verification (full/partial/
rejected/timeout->UNKNOWN), protective-stop placement, and exit cancel-then-close.
"""
import pytest

from hardening.exec_manager import (TradeIntent, IntentStore, ExecutionManager,
                                    ExecutionResult, _conditional_put)


def make_intent(**kw):
    base = dict(scope='live', tag='MES_DONCHIAN', symbol='MES', action='BUY',
                side='LONG', qty=1, order_type='MKT', stop_price=0.0,
                contract_month='202609', bar_time='2026-08-14', signal_reason='x')
    base.update(kw)
    return TradeIntent(**base)


# ---- fakes ----
class _Exec:
    def __init__(self, shares, price):
        self.shares = shares
        self.price = price


class _Fill:
    def __init__(self, shares, price):
        self.execution = _Exec(shares, price)


class FakeTrade:
    def __init__(self, status='Filled', fills=None, order=None, orderId=1):
        self._status = status
        self.fills = fills or []
        # .order carries the actual ib_insync Order (with .orderId) so bracket
        # code can read trade.order.orderId for the parentId link.
        self.order = order if order is not None else type('O', (), {'orderId': orderId})()

    @property
    def orderStatus(self):
        return type('OS', (), {'status': self._status})()


class _Order:
    def __init__(self, action, orderType, totalQuantity, symbol='MES', auxPrice=None,
                 orderRef=''):
        self.contract = type('C', (), {'symbol': symbol})()
        self.order = type('O', (), {'action': action, 'orderType': orderType,
                                    'totalQuantity': totalQuantity,
                                    'auxPrice': auxPrice, 'orderRef': orderRef})()


class FakeIB:
    def __init__(self, fill_status='Filled', fill_shares=1, fill_price=100.0):
        self.fill_status = fill_status
        self.fill_shares = fill_shares
        self.fill_price = fill_price
        self.placed = []       # every order passed to placeOrder (MarketOrder/StopOrder)
        self.open = []         # resting orders (stops)
        self.cancelled = []
        self.slept = 0
        self._order_id = 0

    def sleep(self, s):
        self.slept += s

    def placeOrder(self, contract, order):
        self._order_id += 1
        order.orderId = self._order_id      # mirror IBKR's id assignment
        self.placed.append(order)
        fills = [_Fill(self.fill_shares, self.fill_price)] if self.fill_status == 'Filled' else []
        return FakeTrade(self.fill_status, fills, order=order, orderId=self._order_id)

    def openOrders(self):
        return list(self.open)

    def openTrades(self):
        # production code iterates openTrades() (Trade objects carry BOTH
        # .contract and .order). These fakes are Trade-like, so openTrades()
        # returns them directly.
        return list(self.open)

    def cancelOrder(self, o):
        # o is an Order (production passes trade.order); map back to the
        # Trade-like in self.open so test assertions on the trade still hold.
        trade = o if o in self.open else None
        if trade is None:
            for t in self.open:
                if t.order is o:
                    trade = t
                    break
        if trade is not None:
            self.open.remove(trade)
        self.cancelled.append(trade if trade is not None else o)


def make_manager(ib, table, scope='live'):
    return ExecutionManager(ib, table, scope=scope)


# ---- TradeIntent determinism ----
def test_signal_id_deterministic_and_stable():
    a = make_intent()
    b = make_intent()
    assert a.signal_id == b.signal_id
    assert a.intent_id == b.intent_id


def test_signal_id_differs_on_action():
    assert make_intent(action='BUY').signal_id != make_intent(action='SELL').signal_id


def test_signal_id_differs_on_bar_time():
    assert make_intent(bar_time='2026-08-14').signal_id != make_intent(bar_time='2026-08-15').signal_id


def test_intent_id_differs_on_qty_but_signal_id_same():
    a = make_intent(qty=1)
    b = make_intent(qty=2)
    assert a.signal_id == b.signal_id       # same signal
    assert a.intent_id != b.intent_id       # different intent (qty differs)


# ---- IntentStore idempotency ----
def test_intent_store_accept_once(fake_table):
    store = IntentStore(fake_table)
    intent = make_intent()
    assert store.accept(intent) is True
    assert store.accept(intent) is False    # second acceptance -> duplicate
    assert store.was_accepted(intent.signal_id) is True


def test_intent_store_was_accepted_false_before(fake_table):
    store = IntentStore(fake_table)
    assert store.was_accepted(make_intent().signal_id) is False


def test_conditional_put_conflict_returns_false(fake_table):
    fake_table.put_item(Item={'pk': 'INTENT#abc', 'sk': 'accepted'})
    assert _conditional_put(fake_table, {'pk': 'INTENT#abc', 'sk': 'accepted'}) is False
    assert _conditional_put(fake_table, {'pk': 'INTENT#xyz', 'sk': 'accepted'}) is True


# ---- submit_entry ----
def test_submit_entry_filled_places_stop(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=2, fill_price=101.0)
    mgr = make_manager(ib, fake_table)
    intent = make_intent(qty=2, stop_price=95.0)
    res = mgr.submit_entry(intent, contract=None, fill_timeout=8.0)
    assert res.status == 'FILLED'
    assert res.filled_qty == 2
    assert res.avg_px == pytest.approx(101.0)
    # market order + protective stop both placed
    assert len(ib.placed) == 2
    stop = ib.placed[1]
    assert stop.orderType == 'STP' and stop.action == 'SELL'


def test_submit_entry_partial_fill(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=3, stop_price=90.0), None)
    assert res.status == 'PARTIAL'
    assert res.filled_qty == 1


def test_submit_entry_duplicate_is_idempotent(fake_table):
    ib = FakeIB()
    mgr = make_manager(ib, fake_table)
    intent = make_intent(qty=1, stop_price=90.0)
    first = mgr.submit_entry(intent, None)
    second = mgr.submit_entry(intent, None)
    assert first.status == 'FILLED'
    assert second.status == 'DUPLICATE'
    # only ONE entry order ever placed (the duplicate placed nothing)
    assert len([o for o in ib.placed if o.orderType == 'MKT']) == 1


def test_submit_entry_rejected(fake_table):
    ib = FakeIB(fill_status='Rejected')
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=90.0), None)
    assert res.status == 'REJECTED'
    assert res.filled_qty == 0


def test_submit_entry_timeout_is_unknown_not_rejected(fake_table):
    ib = FakeIB(fill_status='Submitted')   # stays open -> timeout
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=90.0), None,
                           fill_timeout=0.01)
    assert res.status == 'UNKNOWN'          # timeout is UNKNOWN, never "rejected"


def test_submit_entry_rejects_no_stop(fake_table):
    # NEVER-LOSE-MONEY: an entry with no protective stop is refused fail-closed.
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=0.0), None)
    assert res.status == 'REJECTED'
    assert all(o.orderType != 'MKT' for o in ib.placed)   # nothing sent to broker


def test_rejected_no_stop_does_not_burn_idempotency_key(fake_table):
    # A no-stop rejection must NOT consume the signal_id — a corrected retry
    # (same signal, now with a stop) is accepted and trades.
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    rejected = mgr.submit_entry(make_intent(qty=1, stop_price=0.0), None)
    assert rejected.status == 'REJECTED'
    retry = mgr.submit_entry(make_intent(qty=1, stop_price=90.0), None)
    assert retry.status == 'FILLED'


def test_submit_entry_always_places_stop(fake_table):
    # The stop is rested unconditionally (no has_stop opt-out anymore).
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=90.0), None)
    assert res.status == 'FILLED'
    assert any(o.orderType == 'STP' for o in ib.placed)


# ---- native bracket orders (PART 2.1: broker-side stop, no naked-position window) ----
def test_bracket_submits_parent_then_linked_stop(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=90.0, tag='MES_DONCHIAN'), None)
    assert res.status == 'FILLED'
    parent = [o for o in ib.placed if o.orderType == 'MKT'][0]
    stop = [o for o in ib.placed if o.orderType == 'STP'][0]
    # parent held (transmit=False); stop is a broker-side child (parentId + transmit)
    assert parent.transmit is False
    assert stop.parentId == parent.orderId
    assert stop.transmit is True
    assert stop.orderRef == 'MES_DONCHIAN'
    assert stop.ocaGroup == f'BRKT-{res.signal_id}'


def test_bracket_with_take_profit_adds_oca_target(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=90.0), None, take_profit=120.0)
    assert res.status == 'FILLED'
    mkt = [o for o in ib.placed if o.orderType == 'MKT']
    stp = [o for o in ib.placed if o.orderType == 'STP']
    lmt = [o for o in ib.placed if o.orderType == 'LMT']
    assert len(mkt) == 1 and len(stp) == 1 and len(lmt) == 1
    stop, target = stp[0], lmt[0]
    # stop + target share one OCA group (one fill cancels the other); the LAST
    # leg (target) transmits the whole chain.
    assert stop.ocaGroup == target.ocaGroup == f'BRKT-{res.signal_id}'
    assert stop.parentId == target.parentId == mkt[0].orderId
    assert stop.transmit is False and target.transmit is True


def test_bracket_keeps_stop_resting_on_unknown_fill(fake_table):
    # On an uncertain (timeout) fill the bracket stop is LEFT resting — it is the
    # only protection if the entry actually filled. Never stripped on UNKNOWN.
    ib = FakeIB(fill_status='Submitted')
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=1, stop_price=90.0), None, fill_timeout=0.01)
    assert res.status == 'UNKNOWN'
    assert any(o.orderType == 'STP' for o in ib.placed)


def test_bracket_partial_fill_resizes_stop_to_filled_qty(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    res = mgr.submit_entry(make_intent(qty=3, stop_price=90.0), None)
    assert res.status == 'PARTIAL'
    # bracket stop (qty 3) placed, then a corrected stop (qty 1) re-rested
    stops = [o for o in ib.placed if o.orderType == 'STP']
    assert stops[-1].totalQuantity == 1


# ---- submit_exit ----
def test_submit_exit_cancels_stop_then_closes(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=99.0)
    stop = _Order('SELL', 'STP', 1)
    ib.open.append(stop)
    mgr = make_manager(ib, fake_table)
    intent = make_intent(action='SELL', qty=1, stop_price=0.0)
    res = mgr.submit_exit(intent, None, cancel_stop=True)
    assert res.status == 'FILLED'
    assert stop in ib.cancelled                       # stop cancelled first
    assert any(o.orderType == 'MKT' and o.action == 'SELL' for o in ib.placed)


def test_submit_exit_duplicate(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=99.0)
    mgr = make_manager(ib, fake_table)
    intent = make_intent(action='SELL', qty=1)
    assert mgr.submit_exit(intent, None).status == 'FILLED'
    assert mgr.submit_exit(intent, None).status == 'DUPLICATE'


# ---- is_stop_open ----
def test_is_stop_open(fake_table):
    ib = FakeIB()
    mgr = make_manager(ib, fake_table)
    assert mgr.is_stop_open('MES', 'LONG') is False
    ib.open.append(_Order('SELL', 'STP', 1))
    assert mgr.is_stop_open('MES', 'LONG') is True


# ---- current_stop_price ----
def test_current_stop_price_reads_auxprice(fake_table):
    ib = FakeIB()
    mgr = make_manager(ib, fake_table)
    assert mgr.current_stop_price('MES', 'LONG') is None
    ib.open.append(_Order('SELL', 'STP', 1, auxPrice=95.0))
    assert mgr.current_stop_price('MES', 'LONG') == pytest.approx(95.0)


def test_current_stop_price_tightest(fake_table):
    # if (erroneously) two stops rest, the tightest binds: highest for a long
    ib = FakeIB()
    mgr = make_manager(ib, fake_table)
    ib.open.append(_Order('SELL', 'STP', 1, auxPrice=95.0))
    ib.open.append(_Order('SELL', 'STP', 1, auxPrice=97.0))
    assert mgr.current_stop_price('MES', 'LONG') == pytest.approx(97.0)


# ---- trail_stop (tighten-only) ----
def test_trail_stop_tightens_long(fake_table):
    ib = FakeIB()
    old = _Order('SELL', 'STP', 1, auxPrice=95.0)
    ib.open.append(old)
    mgr = make_manager(ib, fake_table)
    res = mgr.trail_stop(None, 'MES', 'LONG', 1, new_stop=97.0)
    assert res.status == 'TRAILED'
    assert old in ib.cancelled                       # resting stop cancelled
    assert old not in ib.open
    new = ib.placed[-1]                              # new tighter stop placed
    assert new.orderType == 'STP' and new.action == 'SELL'
    assert new.auxPrice == pytest.approx(97.0)


def test_trail_stop_noop_when_not_tighter(fake_table):
    ib = FakeIB()
    old = _Order('SELL', 'STP', 1, auxPrice=95.0)
    ib.open.append(old)
    mgr = make_manager(ib, fake_table)
    res = mgr.trail_stop(None, 'MES', 'LONG', 1, new_stop=94.0)   # would LOOSEN
    assert res.status == 'NOOP'
    assert ib.cancelled == []                        # nothing touched
    assert len(ib.placed) == 0
    assert old in ib.open


def test_trail_stop_noop_when_no_resting_stop(fake_table):
    ib = FakeIB()                                    # no resting stop
    mgr = make_manager(ib, fake_table)
    res = mgr.trail_stop(None, 'MES', 'LONG', 1, new_stop=97.0)
    assert res.status == 'NOOP'
    assert len(ib.placed) == 0                       # never rests a brand-new stop


def test_trail_stop_short_tightens_down(fake_table):
    ib = FakeIB()
    old = _Order('BUY', 'STP', 1, auxPrice=105.0)    # short stop above entry
    ib.open.append(old)
    mgr = make_manager(ib, fake_table)
    res = mgr.trail_stop(None, 'MES', 'SHORT', 1, new_stop=103.0)
    assert res.status == 'TRAILED'
    assert old in ib.cancelled
    new = ib.placed[-1]
    assert new.orderType == 'STP' and new.action == 'BUY'
    assert new.auxPrice == pytest.approx(103.0)


def test_trail_stop_short_noop_when_loosening(fake_table):
    ib = FakeIB()
    old = _Order('BUY', 'STP', 1, auxPrice=105.0)
    ib.open.append(old)
    mgr = make_manager(ib, fake_table)
    res = mgr.trail_stop(None, 'MES', 'SHORT', 1, new_stop=106.0)   # would LOOSEN
    assert res.status == 'NOOP'
    assert ib.cancelled == []
    assert len(ib.placed) == 0


# ---- ref-tagging (targeted trail/exit when two strategies co-hold one symbol) ----
def test_submit_entry_tags_stop_with_ref(fake_table):
    ib = FakeIB(fill_status='Filled', fill_shares=1, fill_price=100.0)
    mgr = make_manager(ib, fake_table)
    intent = make_intent(qty=1, stop_price=95.0, tag='MES_DONCHIAN')
    res = mgr.submit_entry(intent, None)
    assert res.status == 'FILLED'
    stop = [o for o in ib.placed if o.orderType == 'STP'][0]
    assert stop.orderRef == 'MES_DONCHIAN'


def test_trail_stop_targeted_does_not_cancel_other_strategy(fake_table):
    ib = FakeIB()
    don = _Order('SELL', 'STP', 1, auxPrice=95.0, orderRef='MES_DONCHIAN')
    rsi = _Order('SELL', 'STP', 1, auxPrice=93.0, orderRef='MES_RSI2')
    ib.open.append(don)
    ib.open.append(rsi)
    mgr = make_manager(ib, fake_table)
    res = mgr.trail_stop(None, 'MES', 'LONG', 1, new_stop=97.0, ref='MES_DONCHIAN')
    assert res.status == 'TRAILED'
    assert don in ib.cancelled and don not in ib.open     # Donchian stop moved
    assert rsi not in ib.cancelled and rsi in ib.open     # RSI2 stop untouched
    assert ib.placed[-1].orderRef == 'MES_DONCHIAN'       # new stop re-tagged


def test_trail_stop_ref_scopes_tighten_guard(fake_table):
    # A co-held strategy with a TIGHTER stop must not block this strategy's trail.
    ib = FakeIB()
    don = _Order('SELL', 'STP', 1, auxPrice=95.0, orderRef='MES_DONCHIAN')
    rsi = _Order('SELL', 'STP', 1, auxPrice=98.0, orderRef='MES_RSI2')  # tighter
    ib.open.append(don)
    ib.open.append(rsi)
    mgr = make_manager(ib, fake_table)
    res = mgr.trail_stop(None, 'MES', 'LONG', 1, new_stop=96.0, ref='MES_DONCHIAN')
    assert res.status == 'TRAILED'       # 96 > Donchian's own 95, despite RSI2's 98
    assert don in ib.cancelled
    assert rsi in ib.open and rsi not in ib.cancelled
