"""
India VIX regime module for GREY.

This module scores whether the current India VIX zone is attractive or risky
for NSE index option premium selling context.
"""

from __future__ import annotations

from typing import Any


class GreyVixRegimeModule:
    """Evaluate India VIX regime using only values passed in market_data."""

    def __init__(self) -> None:
        # This identifier is used by GREY's aggregator and module vector.
        self.module_id = "VIX_REGIME"

    def evaluate(self, market_data: dict, session_state: str | None = None) -> dict:
        """Return a standard GREY packet for the current India VIX regime."""
        try:
            # Keep the input safe even if None is passed by a caller.
            data = market_data or {}

            # Read the current India VIX value.
            india_vix = self._to_float(data.get("india_vix"))

            # Read yesterday's VIX close for spike/collapse detection.
            prev_close = self._to_float(data.get("india_vix_prev_close"))

            # Read the optional 5-day average for transparency in raw_components.
            vix_5day_avg = self._to_float(data.get("india_vix_5day_avg"))

            # Missing current VIX means the module cannot evaluate safely.
            if india_vix is None:
                return self._empty_packet("INSUFFICIENT_DATA", "Missing india_vix.", session_state)

            # Classify the VIX band using the user's requested rules.
            score, label, confidence_cap, freeze_suggestion = self._classify_vix(india_vix)

            # Build caution flags from the daily VIX change.
            caution_flags, vix_change_pct = self._vix_change_flags(india_vix, prev_close)

            # A frozen VIX state should not add confidence to GREY.
            confidence = 0.0 if freeze_suggestion else min(confidence_cap, 0.45 + abs(score) / 20.0)

            # Return the standard GREY packet plus VIX-specific fields.
            return {
                "module_id": self.module_id,
                "score": float(score),
                "direction": self._direction_from_score(score),
                "confidence": round(confidence, 3),
                "status": "ACTIVE",
                "reason": label,
                "raw_components": {
                    "india_vix": india_vix,
                    "india_vix_prev_close": prev_close,
                    "india_vix_5day_avg": vix_5day_avg,
                    "vix_change_pct": vix_change_pct,
                },
                "vix_regime": label,
                "recommended_confidence_cap": confidence_cap,
                "freeze_suggestion": freeze_suggestion,
                "caution_flags": caution_flags,
                "session_state": session_state,
                "top_driver": label,
            }
        except Exception as exc:
            # GREY modules must never crash the aggregator loop.
            return self._empty_packet("UNAVAILABLE", f"VIX module failed safely: {exc}", session_state)

    @staticmethod
    def _classify_vix(india_vix: float) -> tuple[float, str, float, bool]:
        """Map India VIX into the requested score, label, cap, and freeze flag."""
        if india_vix < 11.0:
            return -5.0, "PREMIUM_TOO_CHEAP", 0.40, False
        if india_vix < 13.0:
            return -2.0, "LOW_VOL_CAUTION", 0.70, False
        if india_vix < 16.0:
            return 8.0, "SWEET_SPOT_FOR_SELLING", 1.00, False
        if india_vix < 20.0:
            return 5.0, "ELEVATED_PREMIUM_GOOD", 0.85, False
        if india_vix <= 25.0:
            return -3.0, "HIGH_VOL_CAUTION", 0.60, False
        return -10.0, "DANGER_FREEZE", 0.00, True

    @staticmethod
    def _vix_change_flags(india_vix: float, prev_close: float | None) -> tuple[list[str], float | None]:
        """Return caution flags when VIX moves more than 10 percent in one day."""
        if prev_close is None or prev_close <= 0:
            return [], None
        change_pct = (india_vix - prev_close) / prev_close
        if change_pct > 0.10:
            return ["VIX_SPIKE"], round(change_pct, 4)
        if change_pct < -0.10:
            return ["VIX_COLLAPSE_WATCH"], round(change_pct, 4)
        return [], round(change_pct, 4)

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
            "vix_regime": "UNKNOWN",
            "recommended_confidence_cap": 0.0,
            "freeze_suggestion": False,
            "caution_flags": [],
            "session_state": session_state,
            "top_driver": "vix_unavailable",
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
    def _to_float(value: Any) -> float | None:
        """Safely convert input values to float."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


__all__ = ["GreyVixRegimeModule"]
