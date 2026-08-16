# Robinhood Trading Access (VPS)

## Architecture

Robinhood exposes a **hosted MCP server** — `https://agent.robinhood.com/mcp/trading` —
fronted by OAuth 2.0 (authorization_code + refresh_token, PKCE, public client,
`token_endpoint_auth_method=none`). OAuth metadata is in SSM
`/trading/robinhood/meta_json`; the client registration in `/trading/robinhood/client_json`.

The `access_token` is a JWT (ES256) whose claims carry the entitlement snapshot:

| claim | meaning |
|---|---|
| `scope` | `internal` = Robinhood's full-access first-party scope (trading included) |
| `options` | `true` = options trading enabled |
| `level2_access` | `true` = Level-2 options |
| `agent_id` / `meta.on` | bound to the "Robinhood Trading MCP" agent |
| `service_records` | `brokeback_us` (brokerage), `nummus_us` (crypto), `ceres_us` — region/shard |

**Critical fact (verified 2026-08-16):** the public REST API
(`api.robinhood.com/accounts/`) REJECTS this token with `401 "rejected client id"`.
The token is bound to the MCP agent, not the public API. The **only** client-facing
surface is the MCP server — access goes `MCP initialize → tools/list → tools/call`.

## Access module

`infra/robinhood.py` (read-only, no order placement):
- `load_creds()` / `save_creds()` — SSM `/trading/robinhood/*` round-trip.
- `refresh(creds)` — refresh_token grant; `ensure_fresh()` / the audit path persist
  any rotated token back to SSM so laptop & VPS never diverge.
- `mcp_call()` — MCP streamable-HTTP JSON-RPC (initialize / tools/list / tools/call).
- `audit()` — the accessibility-matrix row for Robinhood.
- `python infra/robinhood.py` — one-shot audit.

## Current state (2026-08-16)

**BLOCKED — both tokens revoked.** The SSM `access_token` is still within its `exp`
(~71 h), but Robinhood revoked it server-side (the laptop has since rotated the
token during its own live-trading session). Observed errors:

- MCP `initialize` → `HTTP 401 "token revoked"`
- refresh grant → `HTTP 401 {"error":"invalid_grant"}`

The refresh_token is also dead (a refresh revokes the prior token), so the only
recovery is a **fresh authorization_code flow** (browser login + 2FA). This is
owner/laptop-gated — the redirect_uri is `http://127.0.0.1:58244/callback`
(localhost on the *laptop*), and the login requires Robinhood credentials + 2FA.

## Recovery (owner action — pick ONE)

**A. Re-sync the laptop's CURRENT tokens (fastest).** The laptop Hermes is already
trading live with valid tokens. Push them to SSM from any machine with the instance
role (or a short-lived `aws` CLI with `ssm:PutParameter`):

```
access_token  -> /trading/robinhood/access_token
refresh_token -> /trading/robinhood/refresh_token
expires_in    -> /trading/robinhood/expires_in
expires_at    -> /trading/robinhood/expires_at
scope         -> /trading/robinhood/scope
token_json    -> /trading/robinhood/token_json   # the full OAuth token response
```

(all `SecureString`, `Overwrite=true`). Then re-run `python infra/robinhood.py`.

**B. Re-authorize from scratch.** On the laptop: `hermes mcp login robinhood`
(opens the browser, full OAuth + 2FA), then do step A with the fresh tokens.

## Order-readiness semantics

There is **no simulated/dry-run order endpoint** on the Robinhood MCP surface. The
honest "order placement is possible" signal is therefore: `scope` includes trading
(`internal`) **AND** the account reads successfully with no `restricted` flag. We
never place (or simulate) a live order to prove capability.
