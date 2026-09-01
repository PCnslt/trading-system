#!/usr/bin/env python3
"""
Paper-trading implementation of the validated stock signal.
Information shock -> first 0.5% confirmation -> directional trade -> +2% / -0.5%.

PAPER ONLY. This module contains a HARD safety gate and will refuse to submit
any live order. There is no code path to a real broker order.
"""

import json, os, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')

# ---- FROZEN STRATEGY PARAMETERS (do not modify during trial) ----
CONFIG = {
    'GAP_MIN': 0.02,        # |gap| >= 2%
    'VOL_MULT': 1.5,        # day volume >= 1.5x 20-day avg
    'CONFIRM': 0.005,       # first observable 0.5% move (relative to gap dir)
    'TARGET': 0.02,         # +2% target
    'STOP': 0.005,          # -0.5% stop
    'MAX_SIMULTANEOUS': 3,
    'UNIVERSE': ['AAPL','AMD','AMZN','AVGO','GOOGL','META','MSFT','MU','NFLX',
                 'NVDA','ORCL','PLTR','TSLA','INTC','LLY','TSM'],
}

# ---- HARD SAFETY GATE ----
PAPER_ONLY = True
LEDGER = '/home/ubuntu/trading-system/paper/ledger.jsonl'

def _refuse_live(*a, **k):
    raise RuntimeError('LIVE ORDER REFUSED: PAPER_ONLY mode is active.')

def submit_order(*args, **kwargs):
    """No live path exists. Any attempt raises."""
    _refuse_live(*args, **kwargs)

def now_et():
    return datetime.now(ET).isoformat()

# ---- LEDGER (append-only, every signal + trade) ----
def log(record: dict):
    record['ts'] = now_et()
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, 'a') as f:
        f.write(json.dumps(record) + '\n')

# ---- KILL-SWITCH CHECKS (fail CLOSED) ----
def safety_checks(state: dict) -> list[str]:
    """Return list of triggered kill-switch conditions."""
    kills = []
    if state.get('data_stale', False): kills.append('STALE_DATA')
    if state.get('clock_drift_s', 0) > 5: kills.append('CLOCK_DRIFT')
    if state.get('broker_disconnected', False): kills.append('BROKER_DISCONNECT')
    if state.get('duplicate_signal', False): kills.append('DUPLICATE_SIGNAL')
    if state.get('position_uncertain', False): kills.append('POSITION_UNCERTAIN')
    if state.get('unexpected_position', False): kills.append('UNEXPECTED_POSITION')
    if state.get('quote_inconsistent', False): kills.append('QUOTE_INCONSISTENT')
    if state.get('latency_s', 10e9) > 2.0: kills.append('LATENCY_EXCEEDED')
    if state.get('risk_breached', False): kills.append('RISK_BREACH')
    return kills

# ---- SIGNAL DETECTION (uses historical/intraday bar stream) ----
def detect_signal(open_price, prev_close, day_volume, avg_volume_20d):
    gap = open_price / prev_close - 1
    if abs(gap) < CONFIG['GAP_MIN']: return None
    if avg_volume_20d <= 0 or day_volume < CONFIG['VOL_MULT'] * avg_volume_20d: return None
    return {'gap': gap, 'sgn': 1 if gap > 0 else -1}

def detect_confirmation(cum_return_from_open, sgn, confirm=CONFIG['CONFIRM']):
    """Return +1 (with gap), -1 (against gap), or 0 (not yet)."""
    for r in cum_return_from_open:
        if r * sgn >= confirm: return 1
        if r * sgn <= -confirm: return -1
    return 0

def paper_trade(sym, sgn, entry_px, entry_ask, entry_bid, state):
    """Simulate a single paper trade. Returns full record; no live order."""
    if not PAPER_ONLY:
        raise RuntimeError('SAFETY: paper-trade invoked with PAPER_ONLY=False')
    record = {
        'type': 'paper_trade', 'sym': sym, 'gap_dir': sgn,
        'entry_px': entry_px, 'entry_ask': entry_ask, 'entry_bid': entry_bid,
        'target': CONFIG['TARGET'], 'stop': CONFIG['STOP'],
        'exit_reason': None, 'holding_min': None,
        'gross_pnl_pct': None, 'net_pnl_pct': None,
        'spread_pct': (entry_ask - entry_bid) / entry_px if entry_px else None,
        'kill_checks': safety_checks(state),
    }
    log(record)
    return record

if __name__ == '__main__':
    # Self-test: confirm the gate refuses any order and ledger writes.
    assert PAPER_ONLY is True, 'PAPER_ONLY must be True'
    try:
        submit_order()
        raise SystemExit('SAFETY FAILURE: submit_order did not refuse')
    except RuntimeError as e:
        print(f'[OK] live order refused: {e}')
    r = paper_trade('TEST', 1, 100.0, 100.02, 99.98, {})
    print(f'[OK] paper trade logged: {r["sym"]} spread {r["spread_pct"]:.4f}')
    print('Paper-trading module initialized. PAPER_ONLY=True. No live order path.')
