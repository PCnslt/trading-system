"""data_engine — a self-contained market-data collection engine, DECOUPLED from the
trading system.

This package is deliberately independent of `bot/`, `data/`, `hardening/`, and
anything that touches IBKR / DynamoDB trading state / clientIds. It owns its
own config (registry.json), its own S3 prefix namespace (`yf/stocks/…` and
`data-engine/…`), and its own crontab (`crontab.txt`). It can be split into its
own repo later with zero surgery: it imports only boto3 / yfinance / pandas /
requests / python-dotenv.

Data collected here is research-grade depth (yfinance is an unofficial source,
no SLA) — it is NOT a replacement for the broker-verified IBKR archive.
"""

__version__ = "1.0.0"
__all__ = ["config", "s3store", "universe"]
