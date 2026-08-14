# Trading System

24/7 multi-market automated trading system. Futures → stocks → options → crypto.

## Architecture
- **Data lake:** DynamoDB `trading-data` (hot) + S3 `trading-datalake-…` JSON (cold) — the compounding asset. Futures: `futures-bars/` (12 sym historical) · `futures-ticks/` (L1) · `contracts/` · `sessions/`; hot keys `CONTRACT#` `SESSION#` `QUOTE#` `RISK#`.
- **Strategy engine:** per-market Python modules + Pine Script research on TradingView
- **Execution:** IBKR (futures) · Robinhood (options)
- **Dashboard:** Streamlit, read-only cockpit + 3 safe controls (pause/flatten/kill)
- **Orchestration:** Hermes (cron + gateway) on the VPS

## Directory layout
```
infra/       AWS setup scripts (idempotent)
bot/         strategy + risk + execution
hardening/   execution/risk hardening layers (ledger, reconciler, exec manager)
data/        ingestion pipeline (APIs/brokers → DynamoDB + S3)
dashboard/   Streamlit app
```

## Security
- `.env` lives only on the VPS — never committed
- `.env.example` is the committed template
- Broker secrets via OAuth where possible

## Status
BUILDING — futures phase (paper forward-test). 2 bots live on cron:
`live.py` (index, 23:00 UTC — PROMOTED) · `live_intraday.py` (MES, 15-min RTH).
`live_bondsfx.py` (bonds ZB/ZN) KILLED at Gate-1 (dies at 1-tick slippage) — disarmed.
Kill-switch + dashboard live. See `.hermes/plans/trading-system-checklist.md`.
