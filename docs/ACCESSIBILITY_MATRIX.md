# Broker Accessibility Matrix

> Generated 2026-08-16T22:27:44-04:00. Read-only audit — no live orders.

| venue | auth | account_visible | permissions | market_data | order_ready |
|---|---|---|---|---|---|
| Robinhood live | OK | OK | {"scope": "internal", "options": true, "level2_access": true, "user_origin": "US"} | OK | YES (scope=trading, account readable, no simulated-order surface) |
| IBKR paper | OK | OK: DUR193467 | futures:MES=OK · equity:AAPL=OK · option:SPY=OK | ES:type=1,last=7809.5 · AAPL:type=1,last=nan | YES (whatIf accepted, no rejection) |
| IBKR live | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED |

## Detail

### Robinhood live

- `detail`: {"tools": ["add_option_to_watchlist", "add_to_watchlist", "cancel_equity_order", "cancel_option_exercise", "cancel_option_order", "create_scan", "create_watchlist", "exercise_option", "follow_watchlist", "get_accounts", "get_earnings_calendar", "get_earnings_results", "get_equity_fundamentals", "get_equity_historicals", "get_equity_orders", "get_equity_positions", "get_equity_price_book", "get_equity_quotes", "get_equity_tax_lots", "get_equity_technical_indicators", "get_equity_tradability", "get_financials", "get_index_historicals", "get_index_quotes", "get_indexes", "get_limited_margin_upgrade_info", "get_option_chains", "get_option_historicals", "get_option_instruments", "get_option_level_upgrade_info", "get_option_orders", "get_option_positions", "get_option_quotes", "get_option_watchlist", "get_pnl_trade_history", "get_popular_watchlists", "get_portfolio", "get_realized_pnl", "get_scanner_filter_specs", "get_scans", "get_watchlist_items", "get_watchlists", "place_equity_order", "place_option_order", "remove_from_watchlist", "remove_option_from_watchlist", "review_equity_order", "review_option_order", "run_scan", "search", "unfollow_watchlist", "update_scan_config", "update_scan_filters", "update_watchlist"], "account_tool": "get_accounts", "portfolio_tool": "get_portfolio", "account": {"content": [{"type": "text", "text": "{\"data\":{\"accounts\":[{\"account_number\":\"5SM57902\",\"rhs_account_number\":\"126579028\",\"type\":\"margin\",\"unsettled_funds\":\"0.0000\",\"br

### IBKR paper

- `detail`: {"NetLiquidation": "1002400.28", "TotalCashValue": "1001280.69", "BuyingPower": "3995112.21"}

### IBKR live

- `detail`: Login BLOCKED (owner action required): (a) IBKR disallows two concurrent sessions per username — paper DUR193467 holds the login (official TWS API: 'It is not possible to login to multiple trading applications simultaneously with the same username'); (b) live first-login requires IB Key 2FA (owner phone; paper mode does not use 2FA). Live gateway process currently not running. Owner actions: (1) create an ADDITIONAL username in Account Management for the live account, (2) approve IB Key 2FA on first login.
