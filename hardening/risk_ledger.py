"""Persistent risk ledger — restart-safe risk accounting for the RiskEngine.

The risk engine's daily accounting (daily_pnl, daily_trades,
consecutive_losses, halt state, open positions) is safety-critical: if a bot
crashes or is re-run, the daily-loss cap and consecutive-loss brake must NOT
reset to zero (that would silently reopen a blown day's risk budget).

This module persists that state to DynamoDB under a single-table key:

    {pk: 'RISK#<date>', sk: '<scope>'}

  - `<date>`   = UTC date (ISO `YYYY-MM-DD`) — one ledger row per calendar day.
  - `<scope>`  = the bot's own key ('live', 'live_intraday', 'live_bondsfx'),
                so two bots sharing one account never clobber each other's
                accounting.

FAIL-CLOSED contract:
  - `load()` raises `RiskStateUnavailable` on ANY read error (network,
    throttling, missing table) — the caller must HALT new entries. Only a
    clean "item absent" (first run of the day) returns an empty dict (fresh).
  - `save()` raises `RiskStateUnavailable` on ANY write error; the engine
    records the failure and blocks subsequent entries (see RiskEngine).

The ledger takes an already-constructed boto3 Table (or a test double) — it
does NOT import boto3 or ib_insync at module scope, so it is safe to import
from the Streamlit dashboard (no asyncio event-loop requirement).
"""


import time
from decimal import Decimal


class RiskStateUnavailable(Exception):
    """Risk state unreadable/unwritable — callers must HALT new entries."""


class RiskLedger:
    """Read/write a RiskEngine's daily accounting to DynamoDB RISK#<date>/<scope>."""

    PK_PREFIX = 'RISK#'

    def __init__(self, table, scope: str):
        self.table = table
        self.scope = scope

    def key(self, date_str: str) -> dict:
        return {'pk': f'{self.PK_PREFIX}{date_str}', 'sk': self.scope}

    def load(self, date_str: str) -> dict:
        """Return the persisted state for `date_str` ({} if absent).

        Raises RiskStateUnavailable on read error — absent is the ONLY
        non-raising "empty" path (fresh day).
        """
        try:
            r = self.table.get_item(Key=self.key(date_str))
        except Exception as e:  # noqa: BLE001 - fail-closed on any read error
            raise RiskStateUnavailable(f"risk ledger read failed: {e}") from e
        item = r.get('Item')
        if not item:
            return {}
        # strip the key fields so callers get a clean state dict
        return {k: v for k, v in item.items() if k not in ('pk', 'sk')}

    def save(self, date_str: str, state: dict) -> None:
        """Persist `state` under RISK#<date_str>/<scope>.

        Raises RiskStateUnavailable on write error.

        DynamoDB rejects Python floats ("Float types are not supported") — the
        engine's `daily_pnl` is a float, so coerce any float to Decimal here
        (single choke point for ALL bots, not per-caller). ints/bools/strs/None
        pass through untouched (boto3 serializes them natively).
        """
        item = {}
        for k, v in state.items():
            item[k] = Decimal(str(v)) if isinstance(v, float) else v
        item.update(self.key(date_str))
        item['ts'] = int(time.time())
        try:
            self.table.put_item(Item=item)
        except Exception as e:  # noqa: BLE001 - fail-closed on any write error
            raise RiskStateUnavailable(f"risk ledger write failed: {e}") from e
