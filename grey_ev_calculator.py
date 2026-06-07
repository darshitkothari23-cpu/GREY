"""Expected value calculator for GREY short-premium validation."""

from __future__ import annotations

import logging
import os
from typing import Any


class GreyEVCalculator:
    """Calculate expected value after realistic trading costs."""

    def __init__(
        self,
        *,
        slippage_rupees: float | None = None,
        brokerage_rupees: float | None = None,
        stt_rupees: float | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize fixed per-trade cost assumptions."""
        self.slippage_rupees = self._env_float("GREY_SLIPPAGE_PER_TRADE", slippage_rupees, 200.0)
        self.brokerage_rupees = self._env_float("GREY_BROKERAGE_PER_TRADE", brokerage_rupees, 80.0)
        self.stt_rupees = self._env_float("GREY_STT_PER_TRADE", stt_rupees, 30.0)
        self.logger = logger or logging.getLogger(__name__)

    @property
    def total_costs_rupees(self) -> float:
        """Return total assumed costs per trade."""
        return self.slippage_rupees + self.brokerage_rupees + self.stt_rupees

    def calculate_ev(self, win_pct: float, avg_profit_rupees: float, avg_loss_rupees: float) -> float:
        """Return EV after costs.

        Args:
            win_pct: Win probability from 0.0 to 1.0.
            avg_profit_rupees: Average gross profit on winning trades.
            avg_loss_rupees: Average gross loss on losing trades.

        Returns:
            Expected rupees per trade after slippage, brokerage, and STT.
        """
        return self.calculate_ev_with_slippage(
            win_pct,
            avg_profit_rupees,
            avg_loss_rupees,
            slippage_additional=0.0,
        )

    def calculate_ev_with_slippage(
        self,
        win_pct: float,
        profit: float,
        loss: float,
        slippage_additional: float = 0.0,
    ) -> float:
        """Return EV with optional additional slippage stress testing."""
        win_probability = self._clamp_unit(win_pct)
        total_costs = self.total_costs_rupees + max(0.0, float(slippage_additional or 0.0))
        profit_after_costs = float(profit or 0.0) - total_costs
        loss_after_costs = float(loss or 0.0) + total_costs
        ev = (win_probability * profit_after_costs) - ((1.0 - win_probability) * loss_after_costs)
        rounded = round(ev, 2)
        self.logger.info(
            "EV calculation win_pct=%.3f profit=%.2f loss=%.2f costs=%.2f ev=%.2f",
            win_probability,
            float(profit or 0.0),
            float(loss or 0.0),
            total_costs,
            rounded,
        )
        return rounded

    @staticmethod
    def _clamp_unit(value: Any) -> float:
        """Clamp a numeric value into 0.0 to 1.0."""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _env_float(name: str, explicit: float | None, default: float) -> float:
        """Read a float from explicit value, env, or default."""
        if explicit is not None:
            return float(explicit)
        try:
            return float(os.getenv(name, str(default)) or default)
        except (TypeError, ValueError):
            return default


__all__ = ["GreyEVCalculator"]
