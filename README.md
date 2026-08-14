# Trading System

24/7 multi-market automated trading system. Futures → stocks → options → crypto.

## Architecture
- **Data lake:** DynamoDB (hot) + S3 parquet (cold) — the compounding asset
- **Strategy engine:** per-market Python modules + Pine Script research on TradingView
- **Execution:** IBKR (futures) · Charles Schwab (stocks/options) · Robinhood (crypto)
- **Dashboard:** Streamlit, read-only cockpit + 3 safe controls (pause/flatten/kill)
- **Orchestration:** Hermes (cron + gateway) on the VPS

## Directory layout
```
infra/       AWS setup scripts (idempotent)
bot/         strategy + risk + execution
data/        ingestion pipeline (APIs/brokers → DynamoDB + S3)
dashboard/   Streamlit app
```

## Security
- `.env` lives only on the VPS — never committed
- `.env.example` is the committed template
- Broker secrets via OAuth where possible

## Status
PLANNING → provisioning ($0 AWS free tier). See `.hermes/plans/trading-system-checklist.md`.
