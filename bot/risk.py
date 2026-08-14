"""Risk engine — the guardrails. Fail-closed, never guess.

Incorporates the proven patterns from the odte-spy-bot:
- Risk BUDGET (trading sleeve), not full NetLiq — a huge paper account would
  otherwise make %-based sizing inert (always hit max contracts).
- Daily-loss halt, consecutive-loss brake, time stop, anomaly/staleness guard.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time


@dataclass
class RiskConfig:
    # --- Sizing ---
    risk_budget_usd: float = 100_000   # trading sleeve, NOT full account NetLiq
    risk_pct: float = 0.02             # fraction of budget risked per trade (to stop)
    min_contracts: int = 1
    max_contracts: int = 5             # hard cap regardless of sizing math

    # --- Stops / targets ---
    risk_reward_ratio: float = 1.5     # TP distance = RR * SL distance
    sl_atr_mult: float = 2.0           # SL distance = mult * ATR

    # --- Guardrails ---
    max_trades_per_day: int = 4
    max_daily_loss_pct: float = 0.02   # halt day if realized+open PnL <= -2% of budget
    max_consecutive_losses: int = 6    # pause new entries after N losses in a row
    max_concurrent_positions: int = 1
    time_stop_minutes: int = 60        # force-close after N minutes (futures: end of day)
    max_data_staleness_s: int = 120    # fail closed if data is stale

    # --- Anomaly ---
    price_sigma: float = 3.0           # |z| of return that = price shock


def realized_pnl(side, entry, exit_px, point_value, qty):
    """Realized P&L for a closed position. side: 'LONG'/'SHORT'."""
    direction = 1 if side == 'LONG' else -1
    return direction * (float(exit_px) - float(entry)) * float(point_value) * int(qty)


class RiskEngine:
    """Stateful risk gate. One instance per trading session/day."""

    def __init__(self, config: RiskConfig):
        self.cfg = config
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0
        self._day = datetime.now(timezone.utc).date()
        self.halted = False
        self.halt_reason = None
        self.open_positions = 0
        self._last_data_ts = time.time()

    # ---- rollover ----
    def _rollover_if_new_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.consecutive_losses = 0
            self.halted = False
            self.halt_reason = None

    # ---- gates ----
    def can_enter(self) -> tuple[bool, str]:
        """Fail-closed: return (allowed, reason)."""
        self._rollover_if_new_day()
        if self.halted:
            return False, f"halted: {self.halt_reason}"
        if self.daily_trades >= self.cfg.max_trades_per_day:
            return False, "max trades/day reached"
        if self.consecutive_losses >= self.cfg.max_consecutive_losses:
            return False, "consecutive-loss brake"
        if self.open_positions >= self.cfg.max_concurrent_positions:
            return False, "max concurrent positions"
        if self.daily_pnl <= -self.cfg.risk_budget_usd * self.cfg.max_daily_loss_pct:
            return False, "daily loss halt"
        if self.data_is_stale():
            return False, "stale data"
        return True, "ok"

    def data_is_stale(self) -> bool:
        return (time.time() - self._last_data_ts) > self.cfg.max_data_staleness_s

    def touch_data(self):
        self._last_data_ts = time.time()

    def set_open_positions(self, n: int):
        """Seed open_positions from authoritative state (existing open positions)."""
        self.open_positions = int(n)

    # ---- sizing ----
    def position_size(self, stop_distance: float, point_value: float) -> int:
        """Contracts = risk_pct * budget / (stop_distance * point_value), capped."""
        if stop_distance <= 0:
            return 0
        risk_amount = self.cfg.risk_pct * self.cfg.risk_budget_usd
        contracts = int(risk_amount / (stop_distance * point_value))
        return max(self.cfg.min_contracts, min(contracts, self.cfg.max_contracts))

    def stop_target(self, entry: float, atr: float, side: int) -> tuple[float, float]:
        """side=+1 long, -1 short. Returns (stop, target)."""
        sl = self.cfg.sl_atr_mult * atr
        if side == 1:
            return entry - sl, entry + sl * self.cfg.risk_reward_ratio
        return entry + sl, entry - sl * self.cfg.risk_reward_ratio

    # ---- accounting ----
    def record_fill(self):
        self.daily_trades += 1
        self.open_positions += 1

    def record_close(self, pnl: float):
        self.open_positions = max(0, self.open_positions - 1)
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        # re-evaluate halt
        if self.daily_pnl <= -self.cfg.risk_budget_usd * self.cfg.max_daily_loss_pct:
            self.halted = True
            self.halt_reason = "daily loss halt"

    def emergency_halt(self, reason: str):
        self.halted = True
        self.halt_reason = reason

    def status(self) -> dict:
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "consecutive_losses": self.consecutive_losses,
            "open_positions": self.open_positions,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
        }
