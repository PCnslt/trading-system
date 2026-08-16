# SELF_REVIEW — independent system review + cross-check of the laptop's directive

**Date:** 2026-08-16 · **Operator:** VPS Hermes (builder) · **Paper-only, never-lose-money, no live.**

Scope: read the execution/risk/reconciliation code, the bots (`live.py`,
`live_gc.py`, `live_intraday.py`), `hardening/`, `research/` (Gate-1, BOOK_SCAN,
EDGE_SWEEP, INTRADAY_BUILD), and `docs/PROJECT-STATE.md`. Cross-checked the
laptop's PART 2 list against what the code actually does, then produced my own
findings.

---

## 1. CRITICAL DEFECT FOUND (and fixed) — `openOrders()` vs `openTrades()`

The single most important thing this review caught, and one the laptop's list
did **not** flag:

- `ib.openOrders()` returns bare `Order` objects that have **no `.contract`**.
- `hardening/exec_manager.py` (`cancel_stop` / `is_stop_open` /
  `current_stop_price`), `hardening/reconciler.py` (`broker_open_orders`), and
  `bot/control.py` (`flatten_ibkr`) all iterated `openOrders()` while reading
  `o.contract.symbol` and `o.order.*` — Trade attributes.

**Impact:** the instant a real order rested at the broker (i.e. the moment the
paper forward-test first ENTERS a position), every stop-management and
reconciliation call would raise `AttributeError`. The reconciler would return
UNKNOWN (halt); `trail_stop`/`cancel_stop` would crash. The never-lose-money
stop *verification* layer was itself broken at runtime — masked only because the
paper bot had not yet held an open position, and the unit-test doubles encoded
the same wrong shape.

**Fix:** switched to `ib.openTrades()` (Trade carries `.contract` **and**
`.order`); `cancelOrder(trade.order)`. Fixed in exec_manager + reconciler +
flatten + all test doubles. This is a prerequisite for the bracket work (PART
2.1) — a broker-side stop you cannot *read back* is not a guarantee.

---

## 2. Cross-check of the laptop's PART 2 list

| # | Laptop item | My verdict | Notes |
|---|---|---|---|
| 2.1 | Native bracket/OCA orders | ✅ AGREE (highest value) | Implemented in `submit_entry` (market parent transmit=False + stop child parentId+OCA; optional target). Verified by unit tests + a gateway structural smoke test (clientId 99, market closed → no fill). Also fixed the openTrades bug that blocks stop read-back. |
| 2.2 | 1/realized-vol position sizing | ✅ AGREE | Implemented as a HARD cap in `RiskEngine.position_size`, wired into `live.py` + `live_gc.py`. **Calibration caught in review:** a 1% vol budget (tighter than the 2% stop budget) would wrongly reject MNQ; default set to 2% = co-equal with `risk_pct`. Now caps MNQ 4→1 (catches ~3.5× notional the stop-based sizing missed). |
| 2.3 | Horizon-split stops | ✅ AGREE (mostly already true) | `live.py` already conforms (swing: close-based exits + 3×ATR chandelier catastrophic). Formalized with `horizon='swing'` annotations + a binding rule in INTRADAY_BUILD.md. No param re-tune (would violate no-feedback). |
| 2.4 | Prioritize ORB + KAMA | ⚠️ PARTIAL DISAGREE | **ORB was ALREADY tested — NO-GO** (pooled PF@3t 0.97, OOS 0.86). The "ORB is a persistent edge" prior did not survive honest costs on our data. **KAMA (new) also NO-GO on 5-min** (pooled PF 0.70, OOS 0.68, 7,697 trades) — it is a swing/daily tool; on 5-min it whipsaws and churn kills it net-of-cost. Next: re-test KAMA on the daily/2-3d horizon. |
| 2.5 | No-feedback OOS rule | ✅ STRONG AGREE | Encoded as binding in INTRADAY_BUILD.md. OOS ~50% of in-sample = normal. |
| 2.6 | Regime filters skeptical | ✅ AGREE | BOOK_SCAN already found ADX>25 + golden/death cross + 5/8/13 EMA all NO-GO. Encoded "guilty-until-proven-useful." |

---

## 3. What the laptop MISSED (my own findings)

1. **`risk_pct` is still 2%, not the owner's 1%.** `RiskConfig.risk_pct`
   defaults to `0.02`; `live.py` (index) and `live_gc.py` (gold) use the
   default, so they risk **2% per trade** — the "0.5–1% MAX" directive
   (INTRADAY_BUILD.md) is only applied to `live_intraday.py` (0.01). This is a
   real gap, not cosmetic. (Fixing it is a sleeve decision, not a one-liner:
   see §5.1.)
2. **Capital-vs-instrument reality is live, not just academic.** On the $50k
   index sleeve, 1 MNQ ≈ $44k notional (~88% of sleeve). The stop-based sizing
   alone would hold **4 MNQ** (~3.5× notional) because a 2×ATR stop is
   dollar-tight; the vol overlay (now on) correctly caps it to 1. Same story
   for full GC ($100/pt → $400k notional) — `live_gc.py` papers on a $1.5M
   *sizing* sleeve precisely because the real-money size is MGC (micro), not GC.
3. **KAMA belongs on swing, not intraday.** The laptop framed KAMA as an
   *intraday* candidate ("attacks whipsaw drawdown"); the backtest says it's a
   swing/daily instrument. Adding it to the 2-3-day swing evaluation is the
   correct move, not more intraday work.
4. **The 20y-futures depth gap is the real constraint on re-testing
   carry/xsmom/value.** Already noted in memory, but worth re-stating: those
   edges failed on thin/stitched data, and only the yfinance continuous series
   (26y) is deep enough today — so "re-test after deep history" is blocked on
   the 1-min/deep backfill, not on code.

---

## 4. What I disagree with (mildly)

- **"ORB is a persistent edge."** Directionally the *classic* opening-range
  breakout is a real market tendency, but our 30-min-range-break port did not
  clear costs on a liquid 9-symbol universe. If ORB is to be pursued, it must
  be a *different* specification (opening-range with a time-based exit, or a
  trend filter) and treated as a **fresh** OOS test — not a re-tune of the
  existing NO-GO variant.

---

## 5. Prioritized recommendations

1. **Decide `risk_pct` = 1% across the daily/gold lanes (owner decision).**
   Consequence: at 1% × $50k, MNQ and full GC will be rejected by BOTH the stop
   and the vol overlay (correctly — they are oversized for that sleeve). The
   choice is: (a) raise the index sleeve so 1% can hold MNQ, (b) trade MES-only
   on index, (c) accept MGC (micro gold) for gold. This is a *capital* decision,
   not a bug — surface it to the owner rather than silently keep 2%.
2. **Re-test KAMA + the 2-3-day swing variants on the DAILY archive now.** The
   daily data (yfinance 26y continuous / IBKR equities 20y+) is already deep;
   this is the cheap, high-value next evaluation and needs no new data.
3. **Keep the 1-min backfill weekend-gated** (done — PART 1) until it completes;
   then re-run the intraday Gate-1 on the deeper 1-min archive before any
   intraday promote.
4. **Wire the vol overlay's `vol_target_pct` per-lane, not globally.** 2% is the
   correct default today; when risk_pct moves to 1%, vol_target_pct must move
   with it (co-equality is the invariant).
5. **Add a broker-side bracket smoke test to the weekly checklist** — the
   structural test (parent+stop+OCA accepted, then cancelled) is cheap and
   catches gateway/order-shape regressions before a live entry does.

---

## 6. Bottom line

The laptop's six items are directionally sound and mostly already-consistent
with the codebase; the highest-value item (bracket orders) is done and carries
with it the one critical fix the list missed (`openTrades`). The two "new edge"
priors (ORB, KAMA) both fail net-of-cost on intraday data — honest backtests
over priors. The genuinely open decision is **risk sizing**: the owner's 1%-max
directive is not yet applied to the daily/gold lanes, and applying it forces the
capital-vs-instrument conversation that has been papered over by oversized
sleeves.
