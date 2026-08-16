"""Risk engine — the guardrails. Fail-closed, never guess.

Incorporates the proven patterns from the odte-spy-bot:
- Risk BUDGET (trading sleeve), not full NetLiq — a huge paper account would
  otherwise make %-based sizing inert (always hit max contracts).
- Daily-loss halt, consecutive-loss brake, time stop, anomaly/staleness guard.

PERSISTENCE (execution-hardening Phase 1):
- Pass a `hardening.risk_ledger.RiskLedger` to survive restarts. Every
  record_fill / record_close / emergency_halt / set_open_positions persists
  the accounting to DynamoDB RISK#<date>/<scope>.
- `RiskEngine.load(config, ledger)` loads persisted state (or a fresh-zero
  day when absent) and RAISES RiskStateUnavailable on an unreadable state —
  the caller must HALT new entries (fail-closed).
- A save failure sets `_persist_error`, which blocks all subsequent entries
  for the rest of the run (fail-closed) rather than silently continuing on
  an unpatchable ledger.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import time

from hardening.risk_ledger import RiskStateUnavailable


@dataclass
class RiskConfig:
    # --- Sizing ---
    risk_budget_usd: float = 100_000   # trading sleeve, NOT full account NetLiq
    risk_pct: float = 0.02             # fraction of budget risked per trade (to stop)
    min_contracts: int = 1
    max_contracts: int = 5             # hard cap regardless of sizing math

    # --- Volatility overlay (1/realized-vol position scaling — HARD cap) ---
    # Co-equal with the protective stop: cap each position's expected DAILY
    # dollar-volatility at vol_target_pct * budget, so size scales as 1/realized
    # vol and every position carries equal (bounded) volatility risk. Default
    # 2% = SAME as risk_pct, so the two layers agree (a tighter vol budget than
    # the stop budget would wrongly reject instruments the stop-based sizing
    # already admits, e.g. MNQ on the $50k index sleeve).
    vol_scale_enabled: bool = True
    vol_target_pct: float = 0.02       # target daily $-vol per position (fraction of budget)

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


def realized_vol_daily(close, n=20):
    """Daily realized volatility = std of pct returns over `n` bars (a fraction,
    e.g. 0.01 = 1%/day). Duck-typed on a pandas Series — no numpy/pandas import.
    Returns 0.0 when there are fewer than `n` returns."""
    if close is None or len(close) < n + 1:
        return 0.0
    rets = close.pct_change().dropna()
    if len(rets) < n:
        return 0.0
    return float(rets.tail(n).std())


class RiskEngine:
    """Stateful risk gate. One instance per trading session/day.

    With a ledger attached, state is persisted to DynamoDB so a crash or
    re-run does NOT reset the daily-loss cap / consecutive-loss brake to zero.
    """

    def __init__(self, config: RiskConfig, ledger=None):
        self.cfg = config
        self._ledger = ledger               # hardening.risk_ledger.RiskLedger or None
        self._persist_error = False         # save failed -> block new entries (fail-closed)
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0
        self._day = datetime.now(timezone.utc).date()
        self.halted = False
        self.halt_reason = None
        self.open_positions = 0
        self._last_data_ts = time.time()

    # ---- persistence ----
    @classmethod
    def load(cls, config: RiskConfig, ledger):
        """Build an engine and load persisted accounting for today (UTC).

        Raises RiskStateUnavailable if the ledger is unreadable — callers MUST
        HALT new entries. A clean "absent" item yields a fresh-zero day.
        """
        e = cls(config, ledger=ledger)
        state = ledger.load(e._day.isoformat())
        e.apply_state(state)
        return e

    def apply_state(self, state: dict):
        """Restore accounting from a persisted dict (empty dict -> fresh day)."""
        self.daily_pnl = float(state.get('daily_pnl', 0.0))
        self.daily_trades = int(state.get('daily_trades', 0))
        self.consecutive_losses = int(state.get('consecutive_losses', 0))
        self.halted = bool(state.get('halted', False))
        self.halt_reason = state.get('halt_reason') or None
        self.open_positions = int(state.get('open_positions', 0))

    def to_state(self) -> dict:
        return {
            'daily_pnl': round(self.daily_pnl, 2),
            'daily_trades': self.daily_trades,
            'consecutive_losses': self.consecutive_losses,
            'halted': self.halted,
            'halt_reason': self.halt_reason,
            'open_positions': self.open_positions,
        }

    def _persist(self):
        """Persist current accounting. A failure sets _persist_error (fail-closed)."""
        if self._ledger is None:
            return
        try:
            self._ledger.save(self._day.isoformat(), self.to_state())
        except RiskStateUnavailable as e:
            self._persist_error = True
            print(f"[risk] persist failed — blocking new entries (fail-closed): {e}")

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
            self._persist_error = False
            self._persist()

    # ---- gates ----
    def can_enter(self) -> tuple[bool, str]:
        """Fail-closed: return (allowed, reason)."""
        self._rollover_if_new_day()
        if self._persist_error:
            return False, "risk state persistence failure"
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
        self._persist()

    # ---- sizing ----
    def position_size(self, stop_distance: float, point_value: float,
                      realized_vol: float = None, price: float = None) -> int:
        """Contracts = min(stop-based, vol-based), clamped.

        stop-based: risk_pct * budget / (stop_distance * point_value).

        vol-based (HARD overlay, co-equal with the stop): cap so the position's
        expected DAILY dollar-volatility (qty * realized_vol * price *
        point_value) does not exceed vol_target_pct * budget. This is
        1/realized-vol scaling — each position carries equal (bounded)
        volatility risk. The overlay NEVER increases qty; if even one contract
        exceeds the vol budget, reject (return 0).

        Fail-closed: if the stop is so wide that even one contract would exceed
        the risk budget, return 0 (reject) — never force >= min_contracts.
        """
        if stop_distance <= 0:
            return 0
        risk_amount = self.cfg.risk_pct * self.cfg.risk_budget_usd
        contracts = int(risk_amount / (stop_distance * point_value))
        if contracts < self.cfg.min_contracts:
            return 0   # stop too wide for budget — reject rather than over-risk
        contracts = min(contracts, self.cfg.max_contracts)
        if (self.cfg.vol_scale_enabled and realized_vol and realized_vol > 0
                and price and price > 0 and point_value > 0):
            vol_budget = self.cfg.vol_target_pct * self.cfg.risk_budget_usd
            per_contract_dollar_vol = realized_vol * price * point_value
            if per_contract_dollar_vol > 0:
                contracts = min(contracts, int(vol_budget / per_contract_dollar_vol))
            if contracts < self.cfg.min_contracts:
                return 0   # even one contract exceeds the vol budget — reject
        return contracts

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
        self._persist()

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
        self._persist()

    def emergency_halt(self, reason: str):
        self.halted = True
        self.halt_reason = reason
        self._persist()

    def status(self) -> dict:
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "consecutive_losses": self.consecutive_losses,
            "open_positions": self.open_positions,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
        }
