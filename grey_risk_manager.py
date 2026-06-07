"""Risk controls for GREY short-premium research signals.

The manager is intentionally conservative. It does not place orders; it only
decides whether a signal is eligible for recommendation and how large a paper
or shadow-mode position would be.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Mapping


class GreyRiskManager:
    """Apply daily loss gates, position sizing, and short-premium stops."""

    def __init__(
        self,
        account_size: float,
        max_daily_loss_pct: float = 0.02,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize risk limits.

        Args:
            account_size: Trading account size in rupees.
            max_daily_loss_pct: Maximum daily drawdown before signals are blocked.
            logger: Optional logger for risk decisions.
        """
        self.account_size = max(0.0, float(account_size or 0.0))
        self.max_daily_loss_pct = max(0.0, float(max_daily_loss_pct or 0.0))
        self.logger = logger or logging.getLogger(__name__)
        self.trade_date = date.today()
        self.realized_daily_pnl = 0.0

    def should_trade(self, signal: Mapping[str, Any] | None) -> bool:
        """Return True when the daily loss limit still allows recommendations.

        Args:
            signal: The signal being reviewed. It is logged for audit context.

        Returns:
            True when current daily loss is below the configured limit.
        """
        self._rollover_if_needed()
        daily_loss = self.current_daily_loss
        max_loss = self.max_daily_loss_amount
        allowed = daily_loss < max_loss if max_loss > 0 else True
        self.logger.info(
            "Risk should_trade allowed=%s daily_loss=%.2f max_loss=%.2f confidence=%s",
            allowed,
            daily_loss,
            max_loss,
            (signal or {}).get("confidence") if isinstance(signal, Mapping) else None,
        )
        return allowed

    def position_size(self, signal_confidence: float, vix_level: float) -> float:
        """Return lots allowed by confidence, account size, and VIX scaling.

        Args:
            signal_confidence: Signal confidence from 0.0 to 1.0.
            vix_level: Current India VIX. Higher VIX reduces lot size.

        Returns:
            Scaled lot count rounded to two decimals.
        """
        confidence = self._clamp_unit(signal_confidence)
        if confidence < 0.60:
            base_lots = 1
        elif confidence <= 0.75:
            base_lots = 2
        else:
            base_lots = 3

        account_units = max(1, int(self.account_size // 100_000)) if self.account_size else 1
        safe_vix = max(1.0, float(vix_level or 20.0))
        vix_scaled_lots = base_lots * account_units * (20.0 / safe_vix)
        lots = round(max(0.01, vix_scaled_lots), 2)
        self.logger.info(
            "Risk position_size confidence=%.3f vix=%.2f base_lots=%s account_units=%s lots=%.2f",
            confidence,
            safe_vix,
            base_lots,
            account_units,
            lots,
        )
        return lots

    def stop_loss_for_iron_condor(self, sold_premium: float, time_in_trade_minutes: int | float) -> float:
        """Return time-weighted short-premium stop price.

        Args:
            sold_premium: Premium collected for the sold option structure.
            time_in_trade_minutes: Minutes elapsed since entry.

        Returns:
            Premium at which to exit. Example: 100 exits at 150, 175, or 200.
        """
        premium = max(0.0, float(sold_premium or 0.0))
        minutes = max(0.0, float(time_in_trade_minutes or 0.0))
        stop_loss_pct = self.stop_loss_pct_for_minutes(minutes)
        stop_price = round(premium * (1.0 + stop_loss_pct), 2)
        self.logger.info(
            "Risk stop_loss_for_iron_condor sold_premium=%.2f minutes=%.1f stop_pct=%.2f stop_price=%.2f",
            premium,
            minutes,
            stop_loss_pct,
            stop_price,
        )
        return stop_price

    @staticmethod
    def stop_loss_pct_for_minutes(time_in_trade_minutes: int | float) -> float:
        """Return 0.50, 0.75, or 1.00 stop percentage by time in trade."""
        minutes = max(0.0, float(time_in_trade_minutes or 0.0))
        if minutes < 30:
            return 0.50
        if minutes < 120:
            return 0.75
        return 1.00

    def record_trade_result(self, pnl: float) -> None:
        """Add a realized trade result to daily PnL tracking.

        Args:
            pnl: Positive profit or negative loss in rupees.

        Returns:
            None. The daily state is updated in memory.
        """
        self._rollover_if_needed()
        parsed = float(pnl or 0.0)
        self.realized_daily_pnl += parsed
        self.logger.info(
            "Risk record_trade_result pnl=%.2f realized_daily_pnl=%.2f current_daily_loss=%.2f",
            parsed,
            self.realized_daily_pnl,
            self.current_daily_loss,
        )

    @property
    def max_daily_loss_amount(self) -> float:
        """Return the rupee amount allowed for today's max loss."""
        return self.account_size * self.max_daily_loss_pct

    @property
    def current_daily_loss(self) -> float:
        """Return current daily loss as a positive rupee amount."""
        return max(0.0, -self.realized_daily_pnl)

    def _rollover_if_needed(self) -> None:
        """Reset daily PnL when the calendar date changes."""
        today = date.today()
        if today != self.trade_date:
            self.logger.info(
                "Risk daily rollover previous_date=%s previous_pnl=%.2f",
                self.trade_date,
                self.realized_daily_pnl,
            )
            self.trade_date = today
            self.realized_daily_pnl = 0.0

    @staticmethod
    def _clamp_unit(value: Any) -> float:
        """Clamp any numeric value into 0.0 to 1.0."""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, numeric))


__all__ = ["GreyRiskManager"]
