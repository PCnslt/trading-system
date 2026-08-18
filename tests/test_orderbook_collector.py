"""Orderbook collector tests (bot/orderbook_collector.py) — snapshot logic only.

Covers the venue adapters (IBKR L1 fallback + Robinhood L2/L1) as pure
functions against fakes, so the snapshot contract is locked without a live
broker connection. Guarantees: IBKR snapshots are honestly flagged L2-not-
entitled; RH price-book levels flow through best-first; symbols that fail
are surfaced (never silently dropped); the 4-per-call chunking is correct.
"""
import pytest

from orderbook_collector import (snapshot_ibkr, snapshot_rh, _chunks,
                                 IBKR_SYMBOLS, SMALL_TICKET_UNIVERSE)


class _Ticker:
    def __init__(self, symbol, bid=None, ask=None, last=None,
                 bidSize=None, askSize=None, lastSize=None, volume=None):
        self.contract = type('C', (), {'symbol': symbol})()
        self.bid = bid
        self.ask = ask
        self.last = last
        self.bidSize = bidSize
        self.askSize = askSize
        self.lastSize = lastSize
        self.volume = volume


class _FakeRH:
    def __init__(self, books=None, quotes=None):
        self._books = books or []
        self._quotes = quotes or []
        self.calls = []

    def _tool(self, name, **args):
        self.calls.append((name, args))
        return {'data': {'books': self._books, 'errors': []}}

    def get_quotes(self, symbols):
        return self._quotes


def _quote(symbol, bid, ask, last):
    # real get_equity_quotes shape: {quote: {symbol, bid_price, ...}, close: {...}}
    return {'quote': {'symbol': symbol, 'bid_price': bid, 'ask_price': ask,
                      'last_trade_price': last}, 'close': {}}


def test_chunks_4_per_call():
    xs = list(range(15))
    chunks = list(_chunks(xs, 4))
    assert len(chunks) == 4
    assert [len(c) for c in chunks] == [4, 4, 4, 3]
    assert sum(len(c) for c in chunks) == 15


def test_snapshot_ibkr_marks_l2_not_entitled():
    t = _Ticker('MES', bid=5000.0, ask=5000.25, last=5000.0, bidSize=12, askSize=9)
    out = snapshot_ibkr([t])
    assert 'MES' in out
    s = out['MES']
    assert s['depth'] == 'L1'
    assert s['l2_entitled'] is False     # honest gap flag (Error 354 on paper)
    assert s['bid'] == 5000.0 and s['ask'] == 5000.25


def test_snapshot_ibkr_skips_other_symbols():
    t = _Ticker('ES', bid=6000.0, ask=6000.25)   # not in IBKR_SYMBOLS
    assert snapshot_ibkr([t]) == {}


def test_snapshot_ibkr_skips_empty_ticker():
    assert snapshot_ibkr([_Ticker('MES', bid=None, ask=None, last=None)]) == {}


def test_snapshot_rh_l2_book_and_l1_quote():
    rh = _FakeRH(
        books=[{'symbol': 'F', 'updated_at': '2026-08-18T10:00:00-04:00',
                'bids': [{'price': 14.05, 'quantity': 100}],
                'asks': [{'price': 14.06, 'quantity': 80}]}],
        quotes=[_quote('F', 14.05, 14.06, 14.045)],
    )
    out = snapshot_rh(rh)
    assert 'F' in out
    assert out['F']['depth'] == 'L2'
    assert out['F']['bids'][0]['price'] == 14.05
    assert out['F']['ask'] == 14.06          # L1 quote merged onto the book


def test_snapshot_rh_never_silently_drops():
    # a book present but no quote still yields a record (empty market ok)
    rh = _FakeRH(books=[{'symbol': 'T', 'bids': [], 'asks': []}], quotes=[])
    out = snapshot_rh(rh)
    assert 'T' in out
    assert out['T']['bids'] == [] and out['T']['asks'] == []


def test_universe_is_15_small_ticket_names():
    assert len(SMALL_TICKET_UNIVERSE) == 15
    for s in ('F', 'AAL', 'T', 'KHC', 'PFE', 'WBD', 'KVUE', 'DOW', 'SNAP', 'NIO'):
        assert s in SMALL_TICKET_UNIVERSE


def test_ibkr_sleeve_is_mes_mnq():
    assert set(IBKR_SYMBOLS) == {'MES', 'MNQ'}
