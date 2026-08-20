"""Creamer order-flow auction — 4-step framework (Phase 4, order-flow lane).

Signal-only (exec=NONE) port of the reference strategy
(`trading/orderflow-auction-strategy`): trade when the auction forces
participation on one side and it FAILS (trapped participants), then ride the
unwind. Pure, side-effect-free functions; the runner
(`bot/auction_signals.py`) loads MNQ 5-min bars and logs candidate setups to
DynamoDB `AUCTION#<sym>`.

The 4 steps:
  1. Environment  — market structure on 1h/4h: value up / down / sideways.
  2. Location     — value-area discount/premium + fib golden pocket
                    (0.705/0.788/0.886) OUTSIDE value area.
  3. Confirmation — absorption + shift of dominance + bid/ask imbalance.
  4. Execution    — stop below failed sellers / below 0.886; targets at swing
                    points / POC.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

FIB_LEVELS = (0.705, 0.788, 0.886)


# ==================== Step 1 — environment (market structure) ====================
def find_swings(highs: List[float], lows: List[float], n: int = 2) -> Tuple[List[int], List[int]]:
    """Swing highs/lows via n-bar left+right fractals. Returns (high_idxs, low_idxs)."""
    sh, sl = [], []
    for i in range(n, len(highs) - n):
        if highs[i] == max(highs[i - n:i + n + 1]):
            sh.append(i)
        if lows[i] == min(lows[i - n:i + n + 1]):
            sl.append(i)
    return sh, sl


def market_structure(highs: List[float], lows: List[float], n: int = 2) -> str:
    """value up / down / sideways from the last two swing highs and swing lows.

    up   = higher high AND higher low (HH/HL)
    down = lower high AND lower low (LH/LL)
    sideways otherwise (or insufficient swings).
    """
    sh, sl = find_swings(highs, lows, n)
    if len(sh) >= 2 and len(sl) >= 2:
        hh = highs[sh[-1]] > highs[sh[-2]]
        hl = lows[sl[-1]] > lows[sl[-2]]
        lh = highs[sh[-1]] < highs[sh[-2]]
        ll = lows[sl[-1]] < lows[sl[-2]]
        if hh and hl:
            return 'up'
        if lh and ll:
            return 'down'
    return 'sideways'


# ==================== Step 2 — location (value area + golden pocket) =============
def fib_golden_pocket(swing_low: float, swing_high: float) -> dict:
    """Retracement levels for a swing low->high. Returns {ratio: price}.

    Golden pocket = the 0.705 / 0.788 / 0.886 retracement zone. 0.886 is the
    invalidation bound: price beyond it = no trade.
    """
    rng = swing_high - swing_low
    return {f'{r:.3f}': swing_high - r * rng for r in FIB_LEVELS}


def value_area_position(price: float, vah: float, val: float) -> str:
    """'premium' (above VAH) / 'discount' (below VAL) / 'inside'."""
    if vah is None or val is None:
        return 'inside'
    if price > vah:
        return 'premium'
    if price < val:
        return 'discount'
    return 'inside'


def golden_pocket_outside_value(pocket: dict, vah: float, val: float) -> bool:
    """True when the whole golden pocket lies OUTSIDE the value area (either
    fully below VAL or fully above VAH) — a required location condition."""
    lo = min(pocket.values())
    hi = max(pocket.values())
    if vah is None or val is None:
        return True
    return hi < val or lo > vah


# ==================== Step 3 — confirmation ====================
def shift_of_dominance(deltas: List[float], lookback: int = 3) -> bool:
    """True when signed delta flipped from one side's dominance to the other.

    Specifically: the prior `lookback` bars were dominated by one sign (sum has
    one sign) and the current bar's delta flips to the opposite sign — the
    "shift of dominance" that confirms an auction has turned.
    """
    if len(deltas) < 2:
        return False
    cur = deltas[-1]
    prior = sum(deltas[-1 - lookback:-1])
    return (cur > 0 and prior < 0) or (cur < 0 and prior > 0)


def confirmation(absorption: dict, shift: bool, imbalance: Optional[float],
                 side: str) -> dict:
    """Assemble the 3 confirmation legs for a candidate `side` ('long'/'short').

    long : sell-absorption (sellers trapped at the low) + bullish shift of
           dominance + bid-heavy imbalance (if available).
    short: buy-absorption + bearish shift + ask-heavy imbalance.
    Returns {passed, reasons:[...]}. The imbalance leg is optional (None when
    no orderbook yet) and does not veto — flagged as 'pending'.
    """
    reasons = []
    if side == 'long':
        if absorption.get('sell_absorption'):
            reasons.append('sell-absorption (sellers trapped)')
        if shift:
            reasons.append('shift of dominance to buyers')
        if imbalance is not None:
            reasons.append('bid-heavy imbalance' if imbalance > 0 else 'ask-heavy (against)')
        else:
            reasons.append('imbalance pending (no book)')
        passed = bool(absorption.get('sell_absorption')) and shift
    else:
        if absorption.get('buy_absorption'):
            reasons.append('buy-absorption (buyers trapped)')
        if shift:
            reasons.append('shift of dominance to sellers')
        if imbalance is not None:
            reasons.append('ask-heavy imbalance' if imbalance < 0 else 'bid-heavy (against)')
        else:
            reasons.append('imbalance pending (no book)')
        passed = bool(absorption.get('buy_absorption')) and shift
    return {'passed': passed, 'reasons': reasons}


# ==================== Step 4 — execution (stop / targets) ====================
def execution_levels(side: str, entry: float, pocket: dict, failed_extreme: float,
                     poc: Optional[float]) -> dict:
    """Stop and targets for a candidate.

    long : stop = min(failed sellers' extreme, the 0.886 retracement) — below
           the level that would invalidate the auction; targets = POC then the
           swing high (pocket is denominated from a low->high swing).
    short: mirrored.
    """
    invalidation = pocket.get('0.886')
    if side == 'long':
        stop = min(x for x in (failed_extreme, invalidation) if x is not None)
        # target ABOVE entry: POC only if it's actually above; else the shallow
        # retracement (0.705) which sits above a proper long entry.
        t1 = poc if (poc is not None and poc > entry) else pocket.get('0.705')
        t2 = pocket.get('0.705')
    else:
        stop = max(x for x in (failed_extreme, invalidation) if x is not None)
        # target BELOW entry: POC only if it's actually below; else the deep
        # retracement (0.886) which sits below a proper short entry. (The old
        # unconditional `t1 = poc` produced targets ABOVE a short entry, so a
        # "win" was trivially true and the R multiple went negative.)
        t1 = poc if (poc is not None and poc < entry) else pocket.get('0.886')
        t2 = pocket.get('0.886')
    return {'stop': stop, 'target_poc': t1, 'target_swing': t2}


# ==================== orchestrator ====================
def auction_setup(side: str, price: float, highs: List[float], lows: List[float],
                  vah: Optional[float], val: Optional[float], poc: Optional[float],
                  deltas: List[float], absorption: dict, imbalance: Optional[float],
                  swing_low: Optional[float], swing_high: Optional[float],
                  failed_extreme: Optional[float], participation: float,
                  min_participation: float = 20000.0, swing_n: int = 2) -> Optional[dict]:
    """Run the 4-step framework for one candidate direction. Returns a setup
    dict when all non-optional legs pass, else None.

    participation is the current 5-min candle volume (contracts); below
    `min_participation` the setup is skipped (Creamer's participation floor).
    """
    if participation < min_participation:
        return None
    env = market_structure(highs, lows, swing_n)
    if env == 'sideways':
        return None
    # long requires an uptrend (discount); short a downtrend (premium)
    if (side == 'long' and env != 'up') or (side == 'short' and env != 'down'):
        return None
    if swing_low is None or swing_high is None:
        return None
    pocket = fib_golden_pocket(swing_low, swing_high)
    # price must have retraced INTO the golden pocket (between 0.705 and 0.886)
    lo, hi = min(pocket.values()), max(pocket.values())
    if not (lo <= price <= hi):
        return None
    # location: only trade DISCOUNT (below value) in an uptrend / PREMIUM (above
    # value) in a downtrend. The original "whole golden pocket outside value" gate
    # never fires on single-session 5-min data (swing + value area are same-scale,
    # so the pocket always overlaps value) — verified 0/36 entry bars on 2026-08-20.
    # The faithful Creamer location rule is price-vs-value-area (discount/premium),
    # which is what `value_area_position` encodes.
    vpos = value_area_position(price, vah, val)
    if side == 'long' and vpos != 'discount':
        return None
    if side == 'short' and vpos != 'premium':
        return None
    shift = shift_of_dominance(deltas)
    conf = confirmation(absorption, shift, imbalance, side)
    if not conf['passed']:
        return None
    ex = execution_levels(side, price, pocket, failed_extreme, poc)
    return {
        'side': side, 'environment': env, 'entry': price,
        'golden_pocket': {k: round(v, 2) for k, v in pocket.items()},
        'value_area': {'vah': vah, 'val': val, 'poc': poc},
        'confirmation': conf['reasons'],
        'stop': ex['stop'], 'target_poc': ex['target_poc'],
        'target_swing': ex['target_swing'], 'participation': participation,
    }


# ==================== score-based variant (replaces the AND-gate) ====================
# Confirmation (absorption + shift) carries the most weight — that is the actual
# "failed auction" edge; env/location/pocket gate it. Participation is a HARD gate
# (Creamer: below the floor = skip), not a weighted factor — see auction_score.
SCORE_WEIGHTS = {'env': 0.15, 'location': 0.15, 'pocket': 0.15,
                 'absorption': 0.30, 'shift': 0.25}
SCORE_THRESHOLD = 0.60


def auction_score(side: str, price: float, highs: List[float], lows: List[float],
                  vah: Optional[float], val: Optional[float], poc: Optional[float],
                  deltas: List[float], absorption: dict, imbalance: Optional[float],
                  swing_low: Optional[float], swing_high: Optional[float],
                  failed_extreme: Optional[float], participation: float,
                  min_participation: float = 20000.0, swing_n: int = 2) -> dict:
    """Score a candidate bar 0-1 across the 5 Creamer factors (weighted).

    Replaces the old 6-condition AND-gate (which had ~0 joint hit-rate) with a
    faithful WEIGHTED read of the same factors — closer to how the discretionary
    strategy actually weighs evidence. Participation is a HARD gate (returns
    score 0.0 when below the floor). A bar with `score >= SCORE_THRESHOLD` is a
    candidate setup. `components` is returned for transparency/ranking.
    """
    env = market_structure(highs, lows, swing_n)
    comp = {k: 0.0 for k in SCORE_WEIGHTS}
    comp['participation'] = min(1.0, participation / (2.0 * min_participation)) \
        if participation >= min_participation else 0.0

    # hard gate — participation floor (Creamer: below = skip)
    if participation < min_participation:
        return {'score': 0.0, 'components': comp, 'environment': env, 'setup': False}

    # 1. environment — trend must align with the trade direction
    env_ok = (side == 'long' and env == 'up') or (side == 'short' and env == 'down')
    comp['env'] = 1.0 if env_ok else 0.0

    # 2. location — discount for long / premium for short (partial credit inside value)
    vpos = value_area_position(price, vah, val)
    if side == 'long':
        comp['location'] = 1.0 if vpos == 'discount' else (0.4 if vpos == 'inside' else 0.0)
    else:
        comp['location'] = 1.0 if vpos == 'premium' else (0.4 if vpos == 'inside' else 0.0)

    # 3. golden pocket — in-pocket (0.705-0.886 retracement); deeper = stronger
    if swing_low is not None and swing_high is not None and swing_high > swing_low:
        pocket = fib_golden_pocket(swing_low, swing_high)
        lo, hi = min(pocket.values()), max(pocket.values())
        if lo <= price <= hi:
            r = (price - lo) / (hi - lo) if hi > lo else 0.0
            comp['pocket'] = 0.5 + 0.5 * r          # 0.5 shallow -> 1.0 deep (0.886)

    # 4. absorption — failed auction at the extreme (trapped participants)
    if side == 'long':
        comp['absorption'] = 1.0 if absorption.get('sell_absorption') else 0.0
    else:
        comp['absorption'] = 1.0 if absorption.get('buy_absorption') else 0.0

    # 5. shift of dominance — delta flips in the trade's direction
    if shift_of_dominance(deltas):
        cur = deltas[-1] if deltas else 0.0
        aligned = (side == 'long' and cur > 0) or (side == 'short' and cur < 0)
        comp['shift'] = 1.0 if aligned else 0.3    # flipped but not yet aligned

    score = sum(SCORE_WEIGHTS[k] * comp[k] for k in SCORE_WEIGHTS)
    return {'score': round(score, 3),
            'components': {k: round(v, 3) for k, v in comp.items()},
            'environment': env,
            'setup': score >= SCORE_THRESHOLD}
