# Options Research Architecture v3 — GATE + information-consensus + statistical hygiene

## GATE architecture (final decision framework)
GATE 1: P(|move| > 2%) already high? (from info-arrival) — NO → no trade
GATE 2: does option info determine DIRECTION beyond stock info? — NO → no trade
GATE 3: is the option cheap enough? (MOVE_EDGE = conditional move / implied move > threshold)
GATE 4: is the contract liquid enough? (tight spread, adequate vol/OI, RH-executable)
GATE 5: expected net option P&L positive at ASK→BID?

## Robust flow proxies (never TRUE_OOI; all IBKR_PROXY_*)
- O/S ratio (option vol / stock vol) + abnormal O/S + O/S change — NO buy/sell classification needed
- OI-demand consensus: Δcall OI vs Δput OI, near-ATM vs OTM — 3+ independent proxies must AGREE
- CPIV level × CPIV variability (but control borrow-cost before calling it "information")
- Option shock BEFORE stock shock (option abnormal + stock quiet → future move)

## Information consensus (the real interaction)
5 channels: stock / option / volume / market / sector → +1/0/-1.
Test 5/5, 4/5, 3/5 agreement AND option-vs-stock DISAGREEMENT.
Only investigate option info as the DIRECTION resolver on already-large-move events (Gate 1 first).

## Statistical hygiene (non-negotiable)
- OBSERVATIONS ≠ INDEPENDENT EVENTS. Cluster by stock AND day; block bootstrap; report EFFECTIVE sample size.
- Lead-lag BOTH directions (option→stock AND stock→option); option→stock must survive controlling for contemporaneous stock return.
- Sequential checkpoints N=30/60/120/250/500, each = diagnostic only until 120.
- Placebo: midday option activity predicting EARLIER returns must be null; future→past = leakage = reject pipeline.

## Event-triggered high-frequency capture (add to scheduled 30-min)
Trigger: |stock 5m|>0.5%, |stock 15m|>1%, option vol >3×, O/S >3×, |IV z|>2, large gap, earnings/news.
On trigger: capture every 1–5 min for −30m…+120m around the event. Store EVENT_ID + full feature vector + forward returns (5m…5d).

## Success metric (unchanged)
Expected net $P&L per $1 premium risked, ASK→BID, with move-edge × direction-edge both required.
