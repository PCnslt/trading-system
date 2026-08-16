# Micro-Live Plan (DRAFT — do NOT execute)

> Trigger: **Gate 5 PASSES.** This is a plan, not an order. All paper until Gate 5 passes.

## Scope

- **Instrument:** 1 × **MES** (micro E-mini S&P 500, multiplier **$5/point**). No MNQ initially — add only after MES micro-live is stable.
- **Sizing:** **max 1 contract.** No scale-in, no pyramiding. One position per sleeve (Donchian / RSI2) — same single-position gate as paper.
- **Strategies:** index-LONG only — Donchian (close>20d-high, 2×ATR GTC stop) + RSI2 buy-dip (RSI2<10, no stop). Bonds remain SHELVED; intraday lane stays paper until separately gated.

## Risk controls (all already wired, paper-validated)

- **Hard daily-loss cap:** enforced from the persistent risk ledger (`RISK#<date>/live`) before every entry, survives restart. Micro-live cap set conservatively (~$150 = ~30 MES points) so one bad day can't exceed the sleeve's risk budget.
- **Kill-switch:** **flatten + halt on ANY reconcile `MISMATCH` or `UNKNOWN`** (fail-closed; the 45s reconcile-daemon writes `RECONCILE/system`, bots halt on non-MATCH). `CONTROL/system = KILLED` flattens everything globally.
- **Idempotency:** `TradeIntent` → `INTENT#<signal_id>` conditional write (one signal → at most one accepted intent; duplicate → no order).
- **Exit race:** cancel-then-close (stop canceled before market close) — already hardened.

## Rollout steps (future)

1. Confirm Gate 5 PASS (0/10 sessions, zero execution defects).
2. Verify live account: funding, permissions, market data (see blockers).
3. Single MES round-trip on the **live** account (entry → stop → exit) — do NOT leave it on overnight.
4. Flip `LIVE=true` with micro-live sizing (1 MES, $150 daily cap), watch one full RTH session.
5. Escalate only after N clean micro-live sessions (define N at Gate 7).

## Blockers (must resolve before ANY live order)

1. **Account funding** — live IBKR account must hold ≥ initial margin for 1 MES (~$1.3k IBKR initial) **plus** buffer for the daily-loss cap + maintenance margin. Confirm live balance first.
2. **Live account permissions** — futures trading permission + order-type permissions (MKT + GTC STP) must be confirmed on the LIVE account (paper DUR193467 is not evidence of live entitlements).
3. **Live market data** — live account needs CME L1 real-time (separate entitlement from paper; paper has it, live must be verified).
4. **Gateway swap** — exec manager + reconciler run identically live (clientId/broker config unchanged except account), but the live gateway/credential swap must be smoke-tested with one round-trip before micro-live stays on.
5. **Timing** — no flip during a data-collection backfill or a gateway 2FA window (Sun ~09:00 ET).

## Not yet needed

- L2 depth, historical options bars, deeper futures history — see dashboard "Future data subscriptions."
