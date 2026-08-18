"""Microstructure / footprint feature computation (Phase 3, order-flow lane).

Pure, side-effect-free functions over the collected data (futures ticks,
orderbook snapshots, and 1m/5m bars) that produce the per-bar features the
Creamer auction signal generator (Phase 4) consumes. No I/O here — the runner
(`bot/microstructure_engine.py`) loads data and persists `MICRO#<sym>` to
DynamoDB.

Features:
  - bid-ask delta        — buyer-initiated minus seller-initiated volume/bar.
  - absorption           — aggressive order at the extreme wick with NO price
                           reward (the "failed auction" — trapped participants).
  - volume profile       — session POC / VAH / VAL (70% value area).
  - orderbook imbalance  — (bid depth − ask depth) / (bid + ask) over top-N.
  - spread + capture cost— inside spread and its round-trip cost in ticks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional


# ==================== bid-ask delta ====================
def classify_trade(last: Optional[float], bid: Optional[float], ask: Optional[float]) -> int:
    """Classify a trade print: +1 buyer-initiated (>= ask), -1 seller-initiated
    (<= bid), 0 unclassified (mid / missing reference)."""
    if last is None:
        return 0
    if ask is not None and last >= ask:
        return 1
    if bid is not None and last <= bid:
        return -1
    return 0


def bid_ask_delta(ticks: Iterable[dict], bar_fn=None) -> dict:
    """Aggregate signed trade volume (delta) over a tick stream.

    `ticks` is an iterable of {ts, bid, ask, last, lastSize}. Returns a dict of
    {bar_key: {'delta': float, 'buys': float, 'sells': float, 'n': int}} where
    bar_key = bar_fn(tick) (default: raw ts). delta = buys − sells (size-weighted).
    """
    bars: dict = {}
    for t in ticks:
        last, bid, ask = (t.get('last'), t.get('bid'), t.get('ask'))
        side = classify_trade(last, bid, ask)
        sz = float(t.get('lastSize') or 0.0)
        k = bar_fn(t) if bar_fn else t.get('ts')
        b = bars.setdefault(k, {'delta': 0.0, 'buys': 0.0, 'sells': 0.0, 'n': 0})
        if side > 0:
            b['buys'] += sz
            b['delta'] += sz
        elif side < 0:
            b['sells'] += sz
            b['delta'] -= sz
        b['n'] += 1
    return bars


# ==================== absorption (failed auction) ====================
def bar_absorption(bar: dict, delta: Optional[float] = None,
                   delta_threshold: float = 0.0) -> dict:
    """Detect absorption on a single OHLCV bar: aggressive volume at the extreme
    wick with NO price reward.

    - sell-absorption (sellers trapped at the LOW): negative delta (aggressive
      sells) hit the low, but the bar closed back above its low — the selling
      failed to advance price → trapped sellers (bullish reversal fuel).
    - buy-absorption (buyers trapped at the HIGH): positive delta (aggressive
      buys) hit the high, but the bar closed back below its high.

    `delta` is the bar's signed delta (buyer−seller volume); when omitted we
    infer a weak proxy from the close position. Returns a small dict of flags.
    """
    o = bar.get('open'); h = bar.get('high'); l = bar.get('low'); c = bar.get('close')
    if None in (o, h, l, c) or h == l:
        return {'sell_absorption': False, 'buy_absorption': False}

    low_wick = (min(o, c) - l) / (h - l)          # fraction of range below min(o,c)
    high_wick = (h - max(o, c)) / (h - l)         # fraction of range above max(o,c)

    sell_abs = buy_abs = False
    if delta is not None:
        # sellers were aggressive (delta < -threshold) at the low but price
        # recovered (closed off the low) -> sellers failed.
        sell_abs = (delta < -abs(delta_threshold)) and (c > l) and (low_wick > 0.0)
        # buyers aggressive at the high but price fell back -> buyers failed.
        buy_abs = (delta > abs(delta_threshold)) and (c < h) and (high_wick > 0.0)
    else:
        # proxy: a long lower wick (rejection) implies sellers failed to hold
        # the low; a long upper wick implies buyers failed at the high.
        sell_abs = low_wick >= 0.5
        buy_abs = high_wick >= 0.5

    return {'sell_absorption': bool(sell_abs), 'buy_absorption': bool(buy_abs),
            'low_wick': round(low_wick, 4), 'high_wick': round(high_wick, 4)}


# ==================== volume profile / value area ====================
def volume_profile(bars: Iterable[dict], price_step: float = 1.0,
                   value_area: float = 0.70) -> dict:
    """Build a volume-at-price histogram and the session value area.

    `bars` = iterable of {high, low, close, volume}. Volume is spread uniformly
    across the bar's high-low range into `price_step` bins. Returns
    {poc, vah, val, profile:{price: volume}, total_volume}. VAH/VAL bound the
    central `value_area` (default 70%) of volume around the POC.
    """
    prof: dict = {}
    for b in bars:
        h = b.get('high'); l = b.get('low'); v = float(b.get('volume') or 0.0)
        if h is None or l is None or v <= 0 or h < l:
            continue
        n = max(1, int(round((h - l) / price_step)))
        per_bin = v / n
        for i in range(n):
            px = l + (i + 0.5) * (h - l) / n
            key = round(px / price_step) * price_step
            prof[key] = prof.get(key, 0.0) + per_bin

    if not prof:
        return {'poc': None, 'vah': None, 'val': None, 'profile': {}, 'total_volume': 0.0}

    total = sum(prof.values())
    poc = max(prof, key=prof.get)
    prices = sorted(prof)
    # expand from POC outward until we include `value_area` of volume
    target = total * value_area
    acc = prof[poc]
    lo_i = hi_i = prices.index(poc)
    while acc < target and (lo_i > 0 or hi_i < len(prices) - 1):
        # step to the side with more volume (keeps the area compact)
        left_v = prof[prices[lo_i - 1]] if lo_i > 0 else -1.0
        right_v = prof[prices[hi_i + 1]] if hi_i < len(prices) - 1 else -1.0
        if right_v >= left_v and hi_i < len(prices) - 1:
            hi_i += 1
            acc += prof[prices[hi_i]]
        elif lo_i > 0:
            lo_i -= 1
            acc += prof[prices[lo_i]]
        else:
            break
    return {'poc': poc, 'vah': prices[hi_i], 'val': prices[lo_i],
            'profile': prof, 'total_volume': total}


# ==================== orderbook imbalance ====================
def orderbook_imbalance(bids: Iterable[dict], asks: Iterable[dict],
                        top_n: int = 5) -> Optional[float]:
    """(bid depth − ask depth) / (bid + ask) over the top-N levels.

    bids/asks are level dicts {price, quantity} sorted best-first. Returns a
    value in [−1, +1] (+1 = bid-heavy, −1 = ask-heavy), or None if no depth.
    """
    b = sum(float(lv.get('quantity') or 0.0) for lv in list(bids)[:top_n])
    a = sum(float(lv.get('quantity') or 0.0) for lv in list(asks)[:top_n])
    if b + a <= 0:
        return None
    return (b - a) / (b + a)


# ==================== spread + capture cost ====================
def spread_and_cost(bid: Optional[float], ask: Optional[float],
                    tick_size: float = 0.25) -> dict:
    """Inside spread and its round-trip capture cost in ticks."""
    if bid is None or ask is None or ask <= bid:
        return {'spread': None, 'spread_ticks': None, 'capture_cost_ticks': None}
    spread = ask - bid
    ticks = spread / tick_size
    return {'spread': spread, 'spread_ticks': ticks,
            'capture_cost_ticks': 2.0 * ticks}   # cross once in, once out


# ==================== feature assembly ====================
@dataclass
class MicroFeatures:
    sym: str
    bar_ts: str
    delta: float = 0.0
    buys: float = 0.0
    sells: float = 0.0
    sell_absorption: bool = False
    buy_absorption: bool = False
    poc: Optional[float] = None
    vah: Optional[float] = None
    val: Optional[float] = None
    book_imbalance: Optional[float] = None
    spread_ticks: Optional[float] = None
    extra: dict = field(default_factory=dict)

    def to_item(self, pk: str = 'MICRO#') -> dict:
        item = {'pk': f'{pk}{self.sym}', 'sk': self.bar_ts,
                'delta': str(self.delta), 'buys': str(self.buys),
                'sells': str(self.sells),
                'sell_absorption': str(self.sell_absorption).lower(),
                'buy_absorption': str(self.buy_absorption).lower()}
        for k, v in (('poc', self.poc), ('vah', self.vah), ('val', self.val),
                     ('book_imbalance', self.book_imbalance),
                     ('spread_ticks', self.spread_ticks)):
            if v is not None:
                item[k] = str(round(v, 6))
        item.update({k: str(v) for k, v in self.extra.items()})
        return item
