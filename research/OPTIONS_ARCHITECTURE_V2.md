# Options Research Architecture v2 — Information Intersection

## The reframe (no more isolated-anomaly hunting)
**Can option-market information improve a mediocre stock signal enough to make ONE long call/put profitable after ask→bid costs?** Not "does X predict Y" alone.

## The seven-question gate (every "promising" result must answer)
1. What information is known BEFORE entry?
2. Why should it predict direction?
3. Why does it still exist post-publication?
4. How large is the conditional move?
5. How quickly does it occur (time-to-target)?
6. What option contract best monetizes it?
7. Does ask→bid with $700 produce positive EV?

## Five priority leads (mechanism → free-now vs forward)
| # | Lead | Mechanism | Free-now? |
|---|---|---|---|
| 1 | Opening option flow → same-day return | option→stock info flow | ❌ forward (IBKR capture) |
| 2 | Option flow + stock confirmation | information sequence | partial (stock half now) |
| 3 | Call/put IV spread as directional FILTER (control borrow) | surface info | ❌ forward |
| 4 | Post-earnings IV crush → directional continuation | avoid event premium | ✅ stock half now |
| 5 | Move magnitude + time-to-target → optimal DTE | bridge stock→option | ✅ now (needs intraday bars) |

## Ablation design (does option info ADD value?)
A=stock only · B=option only · C=stock+option · D=+vol regime · E=+liquidity.
Kill option feature if C ≈ A. Success metric = **expected net $P&L per $1 option capital** (ask→bid), NOT win rate / mean return.

## Free-now diagnostics (historical stock data, run immediately)
- Information arrival (gap + volume shock + range expansion) → time-to-target distribution
- Signal decay curve (5m→5d) → choose DTE from the curve, not arbitrarily
- Post-earnings directional continuation (after IV crush), direction from surprise+gap+confirmation
- P(|move| > break-even) at each horizon, not E(return)
