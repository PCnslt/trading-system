# Robinhood ↔ IBKR — Broker Access Research (confirmed facts)

**Date:** 2026-08-16 · **Author:** VPS Hermes (builder) · **Status:** research-backed, empirical

This doc records the CONFIRMED facts about the two equities-capable brokers the
system targets, plus the empirical findings that drive the token-architecture fix.
Each fact is tagged `[VERIFIED]` (observed on the live surface) or `[DOC]`
(vendor/community documented, not yet re-observed).

---

## 1. Robinhood — token lifecycle (the defect this task fixes)

- `[VERIFIED]` The `refresh_token` is **single-use / rotating**. A successful
  refresh returns a NEW `refresh_token` and **immediately revokes both the old
  refresh_token and the old access_token** (`invalid_grant` / `token revoked`).
  Consequence: **two processes sharing one token store poison each other** — each
  refresh the laptop performs revokes the token the VPS is about to use, and vice
  versa. **Never copy/share a token. ONE writer per token store.**
- `[VERIFIED]` On this VPS the SSM `access_token` is currently REVOKED
  (MCP `initialize` → `HTTP 401 "token revoked"`), even though its `exp` had not
  elapsed. Revocation ≠ expiry — a revoked token can still look "fresh" by clock.
  Recovery is a fresh `authorization_code` flow (browser consent) — see §3.
- `[VERIFIED]` A crash between refresh and writeback strands the rotated token
  (unrecoverable except by re-OAuth). The VPS client therefore persists the new
  token to the LOCAL fallback file **before** SSM, then to SSM, inside a lock.

## 2. Robinhood — transport surface (which API trades equities)

- `[VERIFIED]` `api.robinhood.com` REST is **crypto-only** (API-key auth). The
  equities OAuth token is REJECTED by the public REST API (`rejected client id` —
  the JWT's `meta.oid` is an MCP client, not a REST client).
- `[VERIFIED]` Equities trading is the **hosted MCP server only**:
  `https://agent.robinhood.com/mcp/trading` (server `robinhood-trading`,
  protocol `2025-06-18`, Streamable HTTP + SSE). 54 tools under the
  `mcp_robinhood_*` namespace; each `tools/call` result is double-encoded
  (`{"content":[{"type":"text","text":"<inner JSON>"}]}`).
- `[VERIFIED]` The MCP trades **only the dedicated "Agentic" account**
  (`agentic_allowed=true`, e.g. `515821577`) — an **equities-only, long-only
  beta** account — NOT the main brokerage account. There is no options/orders
  surface for the main account on this MCP.

## 3. Robinhood — OAuth (DCR / PKCE / loopback)

- `[VERIFIED]` OAuth metadata (SSM `meta_json`): `issuer` =
  `https://agent.robinhood.com/mcp/trading`; `authorization_endpoint` =
  `https://robinhood.com/oauth`; `token_endpoint` =
  `https://api.robinhood.com/oauth2/token/`; `registration_endpoint` =
  `https://agent.robinhood.com/oauth/trading/register` (DCR).
- `[VERIFIED]` Public client: `token_endpoint_auth_method=none` → **no
  client_secret**. `grant_types`: `authorization_code` + `refresh_token`.
  PKCE `S256` only (`code_challenge_methods_supported: ["S256"]`).
  **No device-code grant** is advertised.
- `[VERIFIED]` **Loopback `redirect_uri` is accepted** (`http://127.0.0.1:<port>/callback`).
- `[VERIFIED]` Refresh is headless (POST `refresh_token` + `client_id`); the
  initial consent requires a **desktop browser ONCE** (Robinhood login + 2FA),
  which is owner-gated.

### 3a. CRITICAL finding — DCR issues a SINGLETON client_id (no per-process client)

`[VERIFIED 2026-08-16, empirical]` POSTing to the DCR
`registration_endpoint` returns **the same fixed client_id every time, regardless
of the submitted `client_name` / `redirect_uris`**:

```
POST https://agent.robinhood.com/oauth/trading/register
  {"client_name":"vps-own-client-xyzzy",
   "redirect_uris":["http://127.0.0.1:59999/callback"], ...}
→ 200 {"client_id":"LtLiNmbs9owbYfWgBlC68Z2VujIPuvGoAiSYr8xW",
        "client_name":"Robinhood Trading",
        "redirect_uris":["http://127.0.0.1:59999/callback"],
        "token_endpoint_auth_method":"none"}
```

- The returned `client_id` `LtLiNmbs9owbYfWgBlC68Z2VujIPuvGoAiSYr8xW` is identical
  to the one the laptop originally registered via `hermes mcp login`. Robinhood's
  hosted MCP exposes a **single well-known OAuth client**; DCR cannot mint a
  separate per-process `client_id`.
- The endpoint does echo back the caller's `redirect_uri`, so the **loopback port
  is effectively caller-chosen** (the VPS may use its own port, e.g. `58245`).
- **Consequence for the token-architecture fix:** "register the VPS its OWN
  client_id" is *not possible as stated* — there is only one shared client. The
  correct hardening is **single-writer discipline on the ONE shared token store**:
  the VPS is the sole holder/rotator of the live Robinhood token; the laptop MCP is
  retired for trading and may only READ SSM to confirm (no rotation).

## 4. Robinhood — order constraints (sizing / stops)

- `[VERIFIED]` Fractional orders: **$1 minimum**, **NMS-listed securities only**,
  dollar-denominated (`dollar_amount`) for market orders in regular hours.
- `[DOC→UNCONFIRMED]` `stop_market` / `stop_limit` order types exist, but whether
  they accept a **fractional** quantity (sub-1-share) is **UNCONFIRMED** —
  historically stop/stop-limit are **GFD + market-hours + whole-share only**. The
  VPS client currently treats a sub-1-share position as **cannot-carry-a-broker-stop**
  and reverses it fail-closed.
- **Empirical check (built, pending token re-auth):** `hardening/rh_client.py`
  exposes `check_fractional_stop()` → `review_equity_order` (the MCP simulate
  path, places NO order) with a fractional `dollar_amount`/`quantity` +
  `stop_market`, so the whole-share-vs-fractional question is settled by data, not
  assumption. Runner: `infra/rh_check_fractional_stop.py`. **Result as of
  2026-08-16: BLOCKED — token revoked, must re-auth before the check can run.**

## 5. IBKR — session / credentials / ports

- `[VERIFIED]` **One brokerage session per username** (paper + live share the same
  login identity; concurrent same-username sessions are restricted — run one at a
  time until confirmed).
- `[VERIFIED]` Paper and live have **SEPARATE credentials/accounts**: paper
  `DUR193467`, live `U26949861`.
- `[VERIFIED]` API ports: **live `4001`**, **paper `4002`**. The port IS the
  safety boundary — a bot on 4002 can never reach live capital. The live gateway
  unit (`ibgateway-live.service`) is DISABLED and must stay disabled until funded.
- `[VERIFIED]` The live "Trading Mode" dropdown DEFAULTS to Paper on a fresh
  config dir and is NOT driven by `jts.ini tradingMode` — at first login you must
  switch it manually and verify `managedAccounts()==['U26949861']` before wiring
  any bot.

---

## Single-writer token architecture (the fix)

1. **ONE writer, ONE store.** Only the VPS may hold/rotate the live Robinhood
   token (`/trading/robinhood/*`). The laptop MCP is **retired for trading** and
   may only READ SSM to confirm state — never refresh, never write.
2. Re-auth is VPS-owned: `infra/rh_oauth.py --reauth` DCR-registers (singleton
   client), prints the authorization URL + `ssh -L <port>:127.0.0.1:<port>
   ubuntu@52.7.95.127` port-forward, and listens on the loopback port so the owner
   completes browser consent from the laptop. After consent it persists the fresh
   token to the LOCAL file, then SSM.
3. Because there is one shared `client_id`, a "separate VPS client_id" is
   impossible — the discipline is enforced in code (single-writer docstring +
   single-flight refresh with a race guard) rather than by credential separation.
