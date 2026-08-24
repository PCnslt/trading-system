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

**Singleton client (verified 2026-08-16):** the DCR
`registration_endpoint` returns the SAME well-known `client_id`
(`LtLiNmbs9owbYfWgBlC68Z2VujIPuvGoAiSYr8xW`) regardless of the submitted
`client_name`/`redirect_uri` — Robinhood's hosted MCP has ONE shared OAuth client,
so a **separate per-process client_id cannot be registered**. (It does echo back
the caller's loopback `redirect_uri`, so the port is caller-chosen.) Because there
is one shared client, token safety is enforced by **single-writer discipline**, not
credential separation: only this VPS holds/rotates the live token.

## Access module

`infra/robinhood.py` (read-only, no order placement):
- `load_creds()` / `save_creds()` — SSM `/trading/robinhood/*` round-trip.
- `refresh(creds)` — refresh_token grant; `ensure_fresh()` / the audit path persist
  any rotated token back to SSM so laptop & VPS never diverge.
- `mcp_call()` — MCP streamable-HTTP JSON-RPC (initialize / tools/list / tools/call).
- `audit()` — the accessibility-matrix row for Robinhood.
- `python infra/robinhood.py` — one-shot audit.

## Current state (2026-08-24)

**✅ Re-authenticated (2026-08-16 21:58 ET) — LIVE read path operational.** The
token was revoked server-side during a laptop live-trading session, re-authed on
the VPS the same day, and `hardening/rh_client.py` now reads acct `515821577` live.
(Historical symptom, kept for the record: MCP `initialize` → `HTTP 401 "token
revoked"`; refresh grant → `HTTP 401 {"error":"invalid_grant"}`.)

The refresh_token ROTATES on every refresh (a refresh revokes the prior token).
If re-auth is ever needed again it is a **fresh authorization_code flow** (browser
login + 2FA) — now VPS-owned (see Recovery below), not laptop-gated.

## Recovery (owner action — VPS single-writer re-auth)

Re-auth is now **VPS-owned** (the laptop MCP is retired for trading and must NOT
rotate the token — that is exactly how the store got poisoned). On the VPS:

```
python3 infra/rh_oauth.py --check     # read-only token/client state + MCP liveness
python3 infra/rh_oauth.py --reauth    # DCR (singleton client) + PKCE + loopback listener
```

`--reauth` DCR-registers, prints the authorization URL **and** the port-forward
command, then listens on `127.0.0.1:<port>/callback`. The owner completes consent
from the laptop (browser + 2FA) in two steps:

```
# laptop terminal (forward the loopback port to the VPS):
ssh -L 58245:127.0.0.1:58245 ubuntu@52.7.95.127
# then open the printed https://robinhood.com/oauth?... URL in the laptop browser
```

After consent, the script exchanges the code and persists the fresh token to the
LOCAL file first, then SSM (`/trading/robinhood/*`) — single-writer, crash-safe.
The script never opens a browser or performs the login itself.

## Order-readiness semantics

There is **no simulated/dry-run order endpoint** on the Robinhood MCP surface. The
honest "order placement is possible" signal is therefore: `scope` includes trading
(`internal`) **AND** the account reads successfully with no `restricted` flag. We
never place (or simulate) a live order to prove capability.
