# Intraday → Short-Swing Build

Date: 2026-08-16 · Operator: VPS Hermes (builder) · **Paper-only, never-lose-money, no live.**

> **Owner clarification (folded in):** the objective of this build — and of ALL
> future evaluation — is **CAPITAL PRESERVATION**. "The system should not lose
> money." Returns are secondary. No asset class is a priority.

---

## Objective (ranked, binding)

1. **Capital preservation** — drawdown minimization IS the objective. A low-return,
   tiny-drawdown strategy outranks a high-return, high-drawdown one, always.
2. Returns — evaluated only *after* the drawdown/consistency bar is met.
3. No asset priority — promote whatever has the most stable, lowest-drawdown edge
   (futures micros, equities, crypto, whatever wins on drawdown metrics).

## Horizon

**Intraday → 2–3-day swing.** Two horizons, both in scope:

- **Intraday** (RTH, flatten EOD — no overnight risk): ORB, MOM, VWAP, DONCH15,
  FADESHORT. Live paper: `bot/live_intraday.py` (FADESHORT + DONCH15, MES, clientId 72).
- **Short-swing (2–3 day)** — *new, must be added to every evaluation alongside the
  intraday set*: e.g. Donchian on a 2–3 day lookback, 2–3 day mean-reversion. Not yet
  implemented; add as variants in the next sweep, not as a separate priority lane.

## Evaluation ranking (NEW STANDARD — supersedes the PF-based promote bar)

Rank every strategy **primarily** by:

1. **maxDrawdown** (and worst-case drawdown over any window)
2. **Worst-case** (largest single-trade loss / worst realized day)
3. **Consistency** — win rate + **longest losing streak** (and consecutive-loss count)

**Secondary only:** PF, Sharpe, annualized return. These are tie-breakers, never the
primary filter.

- A **low-return but tiny-drawdown** strategy **OUTRANKS** a high-return high-drawdown one.
- The old bar (OOS PF ≥ 1.2 AND honest-cost PF ≥ 1.0 AND OOS n ≥ 30 AND Sharpe > 0) is
  **retired as the primary filter**; PF is still computed and reported, but a strategy is
  promoted/demoted on its drawdown + consistency profile first.
- "Never lose money" = **drawdown minimization is the objective**, not profit maximization.

## Risk per trade (paper, fail-closed)

- **0.5–1% risk per trade MAX** (budget-notional risked to the hard stop). `risk_pct`
  is capped at `0.01` (1%) — conservative sizing.
- **Hard daily loss cap** — halt the day at −2% of the sleeve budget (existing
  `RiskEngine` daily-loss halt, restart-safe via `RiskLedger`).
- **Mandatory hard stop on every entry + trailing** — already fail-closed
  (`exec_manager.submit_entry` refuses unprotected entries; reconciler HALTs on a
  missing/orphaned stop). Never-lose-money intact.
- Consecutive-loss brake + max-trades/day + max-concurrent-positions=1 unchanged.

## No asset priority

Any market with a stable, low-drawdown edge is promotable. Futures micros (MES/MNQ) are
the current *instrument* of the intraday paper bot, but that is a convenience, not a
preference. Equities/ETF/options/crypto are evaluated on the same drawdown-first bar.

---

## Current strategies (paper)

| Strategy | Horizon | Status | Note |
|---|---|---|---|
| **FADESHORT** (RSI2>90 ∧ close>upper-BB, `live_intraday.py`) | intraday | ▶️ paper | fade-rally SHORT, 2·ATR stop, EOD flatten. |
| **DONCH15** (15m Donchian(20)/ATR breakout, both dirs) | intraday | ▶️ paper | 2·ATR stop, channel-mid exit, EOD flatten. |
| **ORB / MOM / VWAP / DONCH15** (`bot/intraday_scan.py`) | intraday | 🔬 scan | 60d yfinance 5m — statistically weak, smoke only. |
| **2–3 day swing variants** | swing | 🔬 TODO | Donchian 2–3d lookback + 2–3d mean-reversion — add to next sweep. |

## Data + honest caveats

- Live paper bot reads IBKR `reqHistoricalData` (paper DUR193467): 5m (FADESHORT),
  15m (DONCH15). CME real-time bars are NOT yet subscribed — this is historical bars
  pulled each run, not a real-time feed.
- Scan (`intraday_scan.py`) uses yfinance 5m (60d free limit) — ~42–50 sessions,
  ~30–80 trades/strategy. **Not statistically meaningful** for PF/win-rate; treat as a
  directional smoke test, not an edge.
- Once CME real-time is subscribed on IBKR paper, switch the scan loader to IBKR
  (`load_ibkr_bars` is already written) and re-run with 3+ years of intraday bars before
  any promote decision.

## Data source / coverage caveat

- IBKR intraday depth: 1-min ~1–2y (month-partitioned), 1m futures RTH ~1–2y. There is
  **no multi-year 5m/15m futures archive on this account** yet — the honest intraday
  sample is small until real-time collection accumulates. Short-swing (2–3 day) variants
  are testable on the deep daily archives (yfinance 26y continuous / IBKR equities 20y+)
  immediately, which is why they're cheap to add and should ship first.
