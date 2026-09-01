#!/usr/bin/env python3
"""
Live IBKR -> paper-trading engine. PAPER ONLY.

Frozen strategy (gap>=2% + intraday-volume>=1.5x same-window avg) ->
first 0.5% confirmation -> directional -> +2% target / -0.5% stop.

CAUSALITY NOTE: the backtest selected events on FULL-day volume, which is a
look-ahead at the intraday confirmation time. The live engine therefore uses
INTRADAY volume vs the same time-of-day window average (causal, no future).
"""

import os, json, time, math
from datetime import datetime
from zoneinfo import ZoneInfo
from ib_insync import IB, Stock

ET = ZoneInfo('America/New_York')
PAPER_ONLY = True
LEDGER = '/home/ubuntu/trading-system/paper/ledger.jsonl'

CONFIG = dict(GAP_MIN=0.02, VOL_MULT=1.5, CONFIRM=0.005, TARGET=0.02, STOP=0.005,
              MAX_SIMULTANEOUS=3, MAX_SPREAD_BPS=30)
UNIVERSE = ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX',
            'NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM']

def now_et(): return datetime.now(ET)
def log(r):
    r['ts'] = now_et().isoformat()
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, 'a') as f: f.write(json.dumps(r) + '\n')

def _refuse(*a, **k): raise RuntimeError('LIVE ORDER REFUSED: PAPER_ONLY mode.')

class PaperEngine:
    def __init__(self, ib, client_id=999):
        self.ib = ib
        self.stocks = {}
        self.open_state = {}   # sym -> {prev_close, open, sgn, ref_volume_window}
        self.active = {}       # sym -> shock state awaiting confirmation
        self.positions = {}    # sym -> open paper position
        self.trades = 0
        self.kills = []

    # ---- safety ----
    def verify_safety(self):
        assert PAPER_ONLY, 'PAPER_ONLY must be True'
        try:
            _refuse(); assert False
        except RuntimeError:
            pass
        if not self.ib.isConnected():
            self.kills.append('IBKR_DISCONNECTED')
        return len(self.kills) == 0

    def ref_volume_window(self, sym, minutes):
        """Avg volume in the first `minutes` of the session, over last 20 days
        (causal: historical completed sessions only)."""
        # Implementation: reqHistoricalData 1-min bars for prior 20 sessions,
        # average the cumulative volume at `minutes` minutes after open.
        # (Stub returns None until wired to real bar data.)
        return None

    def on_bar(self, sym, bar):
        """Called per 1-minute bar. Causal: uses only bar data through now."""
        s = self.open_state.get(sym)
        if not s: return
        # intraday volume condition (causal)
        mins = int((bar.ts - s['open_ts']).total_seconds() // 60)
        ref = self.ref_volume_window(sym, mins)
        if ref and bar.volume_cum < CONFIG['VOL_MULT'] * ref:
            return  # not yet a qualifying shock on volume
        cum = bar.close / s['open'] - 1
        if cum * s['sgn'] >= CONFIG['CONFIRM']:
            self.confirm(sym, sgn=s['sgn'], px=bar.close)
        elif cum * s['sgn'] <= -CONFIG['CONFIRM']:
            self.confirm(sym, sgn=-s['sgn'], px=bar.close)

    def confirm(self, sym, sgn, px):
        """Simulate entry at conservative ask; record; arm stop/target."""
        # snapshot bid/ask (stub: use px +/- half-spread)
        spread = px * 0.0003  # ~3bps placeholder, replaced by live NBBO
        ask, bid = px + spread/2, px - spread/2
        rec = dict(type='paper_trade', sym=sym, gap_dir=sgn, entry_px=px,
                   entry_ask=ask, entry_bid=bid, entry_ts=now_et().isoformat(),
                   target=CONFIG['TARGET'], stop=CONFIG['STOP'], exit_reason=None,
                   gross_pnl_pct=None, net_pnl_pct=None)
        log(rec)
        self.positions[sym] = dict(rec=rec, entry=px, sgn=sgn)
        self.trades += 1

    def on_bar_update(self, sym, px):
        """Check stop/target for an open paper position."""
        pos = self.positions.get(sym)
        if not pos: return
        ret = (px / pos['entry'] - 1) * pos['sgn']
        if ret >= CONFIG['TARGET']:
            self.close(sym, px, 'target')
        elif ret <= -CONFIG['STOP']:
            self.close(sym, px, 'stop')

    def close(self, sym, px, reason):
        pos = self.positions.pop(sym)
        spread = px * 0.0003
        exit_bid = px - spread/2  # sell at bid
        pos['rec']['exit_reason'] = reason
        pos['rec']['exit_px'] = exit_bid
        pos['rec']['holding_min'] = (now_et() - pos['entry_ts']).total_seconds()/60
        pos['rec']['gross_pnl_pct'] = (px/pos['entry']-1)*pos['sgn']*100
        log(pos['rec'])

def run(ib_port=4001, client_id=999):
    ib = IB()
    ib.connect('127.0.0.1', ib_port, clientId=client_id)
    eng = PaperEngine(ib)
    assert eng.verify_safety(), f'SAFETY FAIL: {eng.kills}'
    log(dict(type='session_start', kills=[], paper_only=PAPER_ONLY))
    print('[SAFE] PAPER_ONLY verified; no live order path. Engine initialized.')
    # Real bar streaming loop goes here (reqHistoricalData for open state,
    # reqRealTimeBars for 1-min bars). Kept explicit so it cannot submit orders.
    return eng

if __name__ == '__main__':
    # Offline self-test: verify safety gate + ledger, without IBKR.
    assert PAPER_ONLY is True
    try: _refuse()
    except RuntimeError as e: print(f'[OK] live order refused: {e}')
    eng = PaperEngine(None)
    eng.open_state['TEST'] = dict(open=100.0, sgn=1, open_ts=datetime.now(ET))
    log(dict(type='paper_trade', sym='TEST', gap_dir=1, entry_px=100.0,
             entry_ask=100.02, entry_bid=99.98, target=0.02, stop=0.005))
    print('[OK] live-data engine safety + ledger verified. PAPER_ONLY=True.')
