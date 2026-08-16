# Robinhood LIVE — client, flags, and blockers

VPS-side Robinhood live path. **PAPER remains the operating default** — LIVE is
double-gated and fail-closed. No live order has been placed.

## The client (prior build, confirmed)

The canonical Robinhood submitter is **`hardening/rh_client.py`** (committed
`77fbb1e`) — the ONLY module that submits Robinhood orders. Wired into
`bot/live_equities.py` (which gained a gated `EXECUTION_MODE`).

- Loads OAuth creds from SSM `/trading/robinhood/*`; refreshes via
  `refresh_token` (PKCE public client, `auth_method=none` → no client_secret);
  **persists the rotated token back to SSM atomically** (local file first, then
  SSM — the refresh_token ROTATES and revokes the old access token).
- **Transport = the Robinhood MCP gateway** (`agent.robinhood.com/mcp/trading`),
  NOT the public REST API (which rejects this `client_id`). This is why a naive
  `api.robinhood.com` Bearer call returns 401 `rejected client id`.
- Methods: `get_account`, `get_positions`, `get_quote(s)`,
  `place_equity_order` (market/limit, fractional dollar_amount), `place_stop`
  (stop_market/stop_limit), `cancel_order`, `list_orders`, `place_equity_entry`
  (fail-closed), `review_equity_order` (simulate).
- **FAIL-CLOSED:** `place_equity_entry` REJECTS `stop_price<=0` and reverses any
  fill it cannot protect (incl. fractional <1 share) — never a naked position.
  Idempotent deterministic `ref_id` (UUIDv5) on every placement.
- `infra/rh_oauth.py` = interactive PKCE re-auth recovery (run on the laptop).

## The live flags (go-live switch)

Live execution requires **BOTH** (each independent, both default OFF):

| Flag | Default | Live value |
|---|---|---|
| `RH_EXECUTION_MODE` | `PAPER` | `LIVE` |
| `RH_LIVE_ENABLED` | `false` | `true` |
| `RH_LIVE_ACCOUNT` | `515821577` | the `agentic_allowed` account |

Order-time LIVE also requires: `agentic_allowed` account mode, `RISK_PCT <= 0.01`,
`$150/day` loss cap, and a protective stop (`stop_price > 0`). Full spec:
`docs/ROBINHOOD_EXECUTION.md`.

## Auth status (verified 2026-08-16): TOKEN DEAD — re-auth required

The SSM token is **not expired** but was **revoked**: during validation the
`refresh_token` was rotated and the rotated value was not persisted before the
process exited, so Robinhood revoked BOTH old tokens. (`api.robinhood.com`
returns 401 `rejected client id`; refresh returns `invalid_grant`.)

### Remaining USER-ONLY blocker (new)

Run **`infra/rh_oauth.py` on the laptop** (browser + Robinhood login) to
re-authenticate and write a fresh token set to SSM `/trading/robinhood/*`.

### Secondary blocker (fractional sizing)

Robinhood stops are **whole-share only**; fractional positions (<1 share) cannot
carry a broker stop. `place_equity_entry` reverses them fail-closed, so the
fractional RSI2 edge is **not live-executable at ~$700** — needs whole-share
sizing or more capital before it can run LIVE.

## Verification

`tests/test_rh_client.py` (10 tests) covers the client. Live placement is
exercised only after re-auth, behind both flags, with a protective stop.
