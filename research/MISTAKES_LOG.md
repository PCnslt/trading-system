# Trading Mistakes & Lessons Log

Every mistake below is a real-money or process error, dated, with the root cause and
the fix. This is the "why did we lose / what did I get wrong" record, kept separate
from `TRADING_JOURNAL.md` (which shows the trades and P&L).

---

## 2026-08-27 — Bought into Jackson Hole without macro awareness (the flag the owner raised twice)

**What happened:** Bought XOM ($105) and MUSA ($91) mid-day on RSI(2) oversold signals,
plus an AMAT buy-and-same-day-cut earlier the same day. Fed Chair Kevin Warsh's FIRST
Jackson Hole keynote — the single most market-moving event of the week — was <24h away
(Aug 28, 10:00 ET). I did not check the macro calendar before any of those buys.

**The mistake in one line:** trading reactively on technical signals without the macro
context a day trader must have. The per-stock `news_gate.py` answers "is THIS name safe",
but says nothing about "is tomorrow a binary macro event". That is the exact gap the owner
flagged twice this session ("have you considered the news? why don't you know about
Jackson Hole?").

**Consequence:** all 5 holdings red the next morning, but small (−$4.34, −1.09%). The −1%
is market noise; the *process gap* is the real defect, and the owner's capital was exposed
to event risk I hadn't sized for.

**Fix (built after the fact):** `bot/macro_events.py` + daily 06:15 ET cron surfaces Fed
speakers / FOMC / Jackson Hole / CPI / PCE / NFP for today AND tomorrow, before the open.
Rule going forward: **check the macro calendar BEFORE any buy, never after.**

---

## 2026-08-27 — Distinguish "strategy drawdown" from "my mistake" (don't conflate)

The 3 original RSI(2) entries (FHN/BLZE/INDV, entered 08-25) have been slightly red since
entry. That is the strategy's **normal shape**: it deliberately buys deeply-oversold,
falling stocks and waits for reversion — some dips take longer than 3 sessions, and INDV
(−3.2%) is approaching its stop. This is NOT a bug and NOT a mistake; it is the edge's
expected underwater phase. The actual 08-27 mistake was the *new* capital (MUSA/XOM/AMAT)
added into unexamined event risk.

Lesson: when the owner says "everything is red, what did you do wrong", first separate
(a) positions whose red is the strategy working as designed, from (b) positions whose red
came from a process error (macro blindness, sizing, chasing). Name both honestly — telling
the owner "that's normal" about (b) destroys trust, and telling them "I screwed up" about
(a) misleads them about the strategy.

---

## Standing lessons (accumulated)

- Check the macro calendar before any buy. `macro_events.py` (06:15 ET) is the source.
- A per-stock news gate ≠ a macro calendar. Both are required.
- "Buy the oversold dip" ≠ "ignore the calendar." A binary Fed event the next morning is a
  reason to size down or stand aside, not a reason to add.
- Verify the current rule before recommending against it: the PDT rule was scrapped
  2026-06-04 (I recommended a guard against a rule that no longer exists — stale memory).
