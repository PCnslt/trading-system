# Broker Accessibility Matrix

> Generated 2026-08-16T15:28:47-04:00. Read-only audit — no live orders.

| venue | auth | account_visible | permissions | market_data | order_ready |
|---|---|---|---|---|---|
| Robinhood live | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED |
| IBKR paper | OK | OK: DUR193467 | futures:MES=OK · equity:AAPL=OK · option:SPY=OK | ES:type=1,last=nan · AAPL:type=1,last=nan | YES (whatIf accepted, no rejection) |
| IBKR live | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED |

## Detail

### Robinhood live

- `detail`: MCP 401: 'token revoked'; refresh failed: HTTP 401: {"error":"invalid_grant"}

### IBKR paper

- `detail`: {"NetLiquidation": "1002400.38", "TotalCashValue": "1001280.79", "BuyingPower": "4005123.16"}

### IBKR live

- `detail`: Login BLOCKED (owner action required): (a) IBKR disallows two concurrent sessions per username — paper DUR193467 holds the login (official TWS API: 'It is not possible to login to multiple trading applications simultaneously with the same username'); (b) live first-login requires IB Key 2FA (owner phone; paper mode does not use 2FA). Live gateway process currently not running. Owner actions: (1) create an ADDITIONAL username in Account Management for the live account, (2) approve IB Key 2FA on first login.
