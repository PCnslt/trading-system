"""Execution-hardening package.

Layers that sit AROUND the strategy logic (never inside it):
  - risk_ledger.py     — persistent, fail-closed risk accounting (Phase 1)
  - reconciler.py      — broker-vs-DynamoDB reconciliation (Phase 2)
  - exec_manager.py    — centralized order lifecycle + idempotent TradeIntent (Phase 3)
  - rh_client.py       — Robinhood equities broker client (MCP transport; fail-closed
                         stops + idempotency; refresh-rotating token writeback)

No strategy may call IBKR/Robinhood directly; strategies express intent, these
layers gate it through risk, reconcile broker truth, and submit idempotently.
"""
