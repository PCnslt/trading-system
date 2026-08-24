# Robinhood LIVE — client, flags, and blockers

VPS-side Robinhood live path. **LIVE since 2026-08-20** (owner-approved go-live).
Deployed in BOTH `.env` AND `live-equities.service` env: `RH_EXECUTION_MODE=LIVE`,
`RH_LIVE_ENABLED=true`, `RH_MAX_POSITIONS=5`, `RH_DAY_LOSS_CAP=$50`. Code default
stays PAPER/OFF (fail-closed); the systemd unit OVERRIDES `.env`, so a go-live
change must touch both.

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
`$50/day` loss cap (deployed; code default `$150`) + `RH_MAX_POSITIONS=5` (deployed;
code default `20`), and a protective stop (`stop_price > 0`). Full spec:
`docs/ROBINHOOD_EXECUTION.md`.

## Auth status (verified 2026-08-17): TOKEN FRESH — LIVE path operational

Re-authenticated **2026-08-16 21:58 ET**; token fresh (`expires_at` ≈ +7.8d). The
client was also unblocked: `notifications/initialized` was being sent as an RPC
(with an `id`) and the MCP server rejected it (`unexpected id for
notifications/initialized`); it is now sent as a proper fire-and-forget
notification. **Read path verified live** — `get_account()` returns acct
`515821577` (`agentic_allowed=true`), `get_quote('SPY')` returns a live quote.
**No live order has been placed.**

Re-auth recovery (if the token dies again) is still **`infra/rh_oauth.py --reauth`**
(owner browser consent via `ssh -L`) — unchanged.

## Fractional sizing — RESOLVED by whole-share small-ticket sizing

Robinhood stops are **whole-share only** (fractional <1 share carries no broker
stop; `place_equity_entry` reverses them fail-closed). This is **no longer a
blocker**: the live lane trades **whole shares of liquid small-ticket names** at
$700 (~5–15 concurrent positions of $14–$35 each, every one with a real
broker-side stop). The executability gate is 2×ATR/share ≤ 1% ($7) — *not* ticket
price. Full sizing table, the satellite-vs-concentration tradeoff, and rollout:
**`docs/SMALL-CAPITAL-LIVE-PLAN.md`**.

## Verification

`tests/test_rh_client.py` (10 tests) covers the client. Live placement is
exercised only after re-auth, behind both flags, with a protective stop.
