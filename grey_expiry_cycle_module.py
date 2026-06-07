"""
Expiry cycle module for GREY.

This module scores where the market is in the weekly/monthly options expiry
cycle using only fields passed in market_data.
"""

from __future__ import annotations

from typing import Any


class GreyExpiryCycleModule:
    """Evaluate theta and expiry-cycle context for NSE index options."""

    def __init__(self) -> None:
        # This identifier is used by GREY's aggregator and module vector.
        self.module_id = "EXPIRY_CYCLE"

    def evaluate(self, market_data: dict, session_state: str | None = None) -> dict:
        """Return a standard GREY packet for the current expiry-cycle phase."""
        try:
            # Keep the input safe even if None is passed by a caller.
            data = market_data or {}

            # Read days to next weekly expiry.
            days_to_expiry = self._to_int(data.get("days_to_expiry"))

            # Read whether this is the monthly expiry week/day context.
            is_monthly_expiry = bool(data.get("is_monthly_expiry", False))

            # Read current weekday where Monday is 0 and Sunday is 6.
            current_weekday = self._to_int(data.get("current_weekday"))

            # Missing days_to_expiry means the module cannot evaluate safely.
            if days_to_expiry is None:
                return self._empty_packet("INSUFFICIENT_DATA", "Missing days_to_expiry.", session_state)

            # Classify expiry phase using the requested score rules.
            score, expiry_phase = self._classify_expiry(days_to_expiry)

            # Build flags and apply monthly-expiry caution when needed.
            caution_flags = []
            if is_monthly_expiry and days_to_expiry <= 2:
                score *= 0.5
                caution_flags.append("MONTHLY_EXPIRY_EXTRA_CAUTION")

            # Add the week-start positioning flag when requested by the rules.
            if current_weekday == 0 and days_to_expiry > 3:
                caution_flags.append("WEEK_START_POSITIONING")

            # Translate the final score into a simple theta quality label.
            theta_quality = self._theta_quality(score)

            # Confidence rises when the expiry-cycle score is clearer.
            confidence = min(0.85, 0.40 + abs(score) / 20.0)

            # Return the standard GREY packet plus expiry-specific fields.
            return {
                "module_id": self.module_id,
                "score": round(float(score), 3),
                "direction": self._direction_from_score(score),
                "confidence": round(confidence, 3),
                "status": "ACTIVE",
                "reason": expiry_phase,
                "raw_components": {
                    "days_to_expiry": days_to_expiry,
                    "is_monthly_expiry": is_monthly_expiry,
                    "current_weekday": current_weekday,
                },
                "expiry_phase": expiry_phase,
                "theta_quality": theta_quality,
                "caution_flags": caution_flags,
                "session_state": session_state,
                "top_driver": expiry_phase,
            }
        except Exception as exc:
            # GREY modules must never crash the aggregator loop.
            return self._empty_packet("UNAVAILABLE", f"Expiry cycle module failed safely: {exc}", session_state)

    @staticmethod
    def _classify_expiry(days_to_expiry: int) -> tuple[float, str]:
        """Map days-to-expiry into the requested score and phase label."""
        if days_to_expiry <= 0:
            return -8.0, "EXPIRY_DAY_HIGH_GAMMA_RISK"
        if days_to_expiry == 1:
            return -4.0, "PRE_EXPIRY_CAUTION"
        if days_to_expiry == 2:
            return 6.0, "THETA_ACCELERATING"
        if days_to_expiry == 3:
            return 8.0, "THETA_SWEET_SPOT"
        if days_to_expiry == 4:
            return 5.0, "GOOD_SELLING_WINDOW"
        return 2.0, "EARLY_THETA_SLOW"

    @staticmethod
    def _theta_quality(score: float) -> str:
        """Translate score into the requested theta quality label."""
        if score >= 7.0:
            return "EXCELLENT"
        if score >= 5.0:
            return "GOOD"
        if score >= 2.0:
            return "MODERATE"
        if score > -6.0:
            return "POOR"
        return "AVOID"

    def _empty_packet(self, status: str, reason: str, session_state: str | None) -> dict:
        """Return a neutral packet for missing data or safe failure."""
        return {
            "module_id": self.module_id,
            "score": 0.0,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "status": status,
            "reason": reason,
            "raw_components": {},
            "expiry_phase": "UNKNOWN",
            "theta_quality": "AVOID",
            "caution_flags": [],
            "session_state": session_state,
            "top_driver": "expiry_unavailable",
        }

    @staticmethod
    def _direction_from_score(score: float) -> str:
        """Convert the numeric score into GREY's simple direction label."""
        if score >= 3.0:
            return "BULL"
        if score <= -3.0:
            return "BEAR"
        return "NEUTRAL"

    @staticmethod
    def _to_int(value: Any) -> int | None:
        """Safely convert input values to int."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


__all__ = ["GreyExpiryCycleModule"]
