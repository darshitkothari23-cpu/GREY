"""Approximate Greeks-aware strike selection foundation for GREY."""

from __future__ import annotations

import logging
from typing import Any


class GreeksAwareStrikeSelector:
    """Recommend rough 16-delta Iron Condor strikes without live option Greeks."""

    def __init__(self, *, strike_step: int = 50, logger: logging.Logger | None = None) -> None:
        """Initialize selector settings."""
        self.strike_step = max(1, int(strike_step))
        self.logger = logger or logging.getLogger(__name__)

    def recommend_iron_condor_strikes(
        self,
        spot_price: float,
        iv_atm: float,
        days_to_expiry: int | float,
        target_delta: int | float = 16,
    ) -> dict:
        """Return approximate OTM call/put strikes and rough theta estimate.

        Args:
            spot_price: Current NIFTY spot.
            iv_atm: ATM implied volatility as decimal or percent.
            days_to_expiry: Days remaining to expiry.
            target_delta: Target short-option delta, usually 16.

        Returns:
            Dict with call strike, put strike, deltas, and theta estimate.
        """
        spot = max(1.0, float(spot_price or 1.0))
        target = max(1.0, min(50.0, float(target_delta or 16.0))) / 100.0
        iv_decimal = self._iv_decimal(iv_atm)
        days = max(1.0, float(days_to_expiry or 1.0))

        otm_pct = max(0.02, min(0.03, target / 0.4))
        call_strike = self._round_to_step(spot * (1.0 + otm_pct))
        put_strike = self._round_to_step(spot * (1.0 - otm_pct))
        theta_per_day = round(max(50.0, spot * iv_decimal * target / days), 2)

        result = {
            "call_strike": call_strike,
            "put_strike": put_strike,
            "call_delta": round(target, 2),
            "put_delta": round(-target, 2),
            "theta_per_day_rupees": theta_per_day,
            "theta_per_day": theta_per_day,
        }
        self.logger.info("Greeks strike recommendation: %s", result)
        return result

    def _round_to_step(self, value: float) -> int:
        """Round a strike to the nearest configured strike step."""
        return int(round(float(value) / self.strike_step) * self.strike_step)

    @staticmethod
    def _iv_decimal(value: Any) -> float:
        """Normalize IV supplied as 0.14 or 14 into a decimal."""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.14
        return numeric / 100.0 if numeric > 1.0 else max(0.01, numeric)


__all__ = ["GreeksAwareStrikeSelector"]
