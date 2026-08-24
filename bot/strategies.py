"""Pluggable strategy registry — signal definitions for the multi-strategy engine.

Each strategy exposes a pure entry-predicate over a per-name indicator dict, so
adding a strategy NEVER touches the execution/portfolio layer. `live` marks a
strategy whose edge is validated on equities; non-live strategies are PAPER
forward-tests only (they can never place a live order).

Phase 2: the strategy-agnostic engine runs every strategy here over the broad
universe (1,459 names) and emits per-strategy signals.
"""
import numpy as np


def rsi2_entry(d):
    """Deployed RSI(2) mean-reversion: RSI2 < 5 AND close > SMA200. LIVE+paper."""
    r2, c, ma = d.get('rsi2'), d.get('close'), d.get('sma200')
    if r2 is None or ma is None or (isinstance(ma, float) and np.isnan(ma)):
        return False
    return r2 < 5.0 and c > ma


def rev2_entry(d):
    """REV2 2-3 day reversal (index-futures lane 33, OOS PF 1.19-1.70):
    2-day drop < -1x ATR AND close > SMA200 (Connors filter, same as RSI2).
    Independent of RSI2 (corr +0.07-0.14). Equities = PAPER forward-test."""
    c, ma, atr = d.get('close'), d.get('sma200'), d.get('atr14')
    drop2 = d.get('drop2')
    if ma is None or atr is None or drop2 is None or (isinstance(ma, float) and np.isnan(ma)):
        return False
    if atr <= 0:
        return False
    return drop2 < -atr and c > ma


STRATEGIES = {
    'RSI2': {
        'entry': rsi2_entry,
        'family': 'mean-reversion',
        'validated': 'equities S&P100 -> S&P1500 (deployed live + paper)',
        'live': True,
    },
    'REV2': {
        'entry': rev2_entry,
        'family': 'mean-reversion',
        'validated': 'index futures lane 33 (OOS 1.19-1.70); equities = forward-test',
        'live': False,
    },
}
