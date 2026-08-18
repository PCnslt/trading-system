"""Tick recorder `kind` tagging tests (bot/tick_recorder.py).

The order-flow extension tags each L1 tick with what actually changed vs the
prior tick — 'trade' (last print), 'quote' (bid/ask), or both — so Phase 3
(bid-ask delta / absorption) can distinguish trade prints from quote updates.
"""
import tick_recorder as TR


class _T:
    def __init__(self, symbol, bid=None, ask=None, last=None):
        self.contract = type('C', (), {'symbol': symbol})()
        self.bid = bid
        self.ask = ask
        self.last = last
        self.bidSize = 1
        self.askSize = 1
        self.lastSize = 1
        self.volume = 100


def _mk(monkeypatch):
    monkeypatch.setattr(TR, '_in_rth', lambda now=None: True)
    monkeypatch.setattr(TR, 'SYMS', ['MES'])
    from collections import defaultdict
    buffer = defaultdict(list)
    latest = {}
    return TR.on_tick_factory(buffer, latest), buffer, latest


def test_kind_first_tick_is_trade_and_quote(monkeypatch):
    on_tick, buffer, _ = _mk(monkeypatch)
    on_tick([_T('MES', bid=5000.0, ask=5000.25, last=5000.0)])
    assert buffer['MES'][0]['kind'] == 'trade+quote'


def test_kind_trade_only_when_last_changes(monkeypatch):
    on_tick, buffer, _ = _mk(monkeypatch)
    on_tick([_T('MES', bid=5000.0, ask=5000.25, last=5000.0)])
    on_tick([_T('MES', bid=5000.0, ask=5000.25, last=5000.25)])   # only last moved
    assert buffer['MES'][1]['kind'] == 'trade'


def test_kind_quote_only_when_bid_moves(monkeypatch):
    on_tick, buffer, _ = _mk(monkeypatch)
    on_tick([_T('MES', bid=5000.0, ask=5000.25, last=5000.0)])
    on_tick([_T('MES', bid=5000.25, ask=5000.25, last=5000.0)])   # only bid moved
    assert buffer['MES'][1]['kind'] == 'quote'


def test_kind_skips_other_symbols(monkeypatch):
    monkeypatch.setattr(TR, '_in_rth', lambda now=None: True)
    monkeypatch.setattr(TR, 'SYMS', ['MES'])
    buffer = {}
    on_tick = TR.on_tick_factory(buffer, {})
    on_tick([_T('ES', bid=6000.0, ask=6000.25, last=6000.0)])   # not in SYMS
    assert buffer == {}
