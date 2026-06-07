"""
Put-Call Ratio module for GREY.

This module reads PCR values from market_data and converts them into a simple
contrarian sentiment packet for GREY review.
"""

from __future__ import annotations

from typing import Any


class GreyPcrModule:
    """Evaluate Put-Call Ratio sentiment using no external API calls."""

    def __init__(self) -> None:
        # This identifier is used by GREY's aggregator and module vector.
        self.module_id = "PCR"

    def evaluate(self, market_data: dict, session_state: str | None = None) -> dict:
        """Return a standard GREY packet for the current PCR regime."""
        try:
            # Keep the input safe even if None is passed by a caller.
            data = market_data or {}

            # Read the required PCR by open interest.
            pcr_oi = self._to_float(data.get("pcr_oi"))

            # Read optional PCR by volume for transparency.
            pcr_volume = self._to_float(data.get("pcr_volume"))

            # Read optional PCR 5-day average for trend flags.
            pcr_5day_avg = self._to_float(data.get("pcr_5day_avg"))

            # Missing PCR OI means the module cannot evaluate safely.
            if pcr_oi is None:
                return self._empty_packet("INSUFFICIENT_DATA", "Missing pcr_oi.", session_state)

            # Classify PCR using the requested contrarian score rules.
            score, pcr_regime, sentiment_label = self._classify_pcr(pcr_oi)

            # Build trend flags when a 5-day average is supplied.
            caution_flags = self._trend_flags(pcr_oi, pcr_5day_avg)

            # Confidence rises as the PCR regime gets more extreme.
            confidence = min(0.90, 0.45 + abs(score) / 20.0)

            # Return the standard GREY packet plus PCR-specific fields.
            return {
                "module_id": self.module_id,
                "score": float(score),
                "direction": self._direction_from_score(score),
                "confidence": round(confidence, 3),
                "status": "ACTIVE",
                "reason": pcr_regime,
                "raw_components": {
                    "pcr_oi": pcr_oi,
                    "pcr_volume": pcr_volume,
                    "pcr_5day_avg": pcr_5day_avg,
                },
                "pcr_regime": pcr_regime,
                "sentiment_label": sentiment_label,
                "caution_flags": caution_flags,
                "session_state": session_state,
                "top_driver": pcr_regime,
            }
        except Exception as exc:
            # GREY modules must never crash the aggregator loop.
            return self._empty_packet("UNAVAILABLE", f"PCR module failed safely: {exc}", session_state)

    @staticmethod
    def _classify_pcr(pcr_oi: float) -> tuple[float, str, str]:
        """Map PCR into score, regime, and plain-English sentiment label."""
        if pcr_oi > 1.5:
            return 7.0, "EXTREME_FEAR_CONTRARIAN_BULL", "EXTREME_FEAR"
        if pcr_oi >= 1.2:
            return 3.0, "BEARISH_SENTIMENT_MILD_BULL_CONTRARIAN", "BEARISH_SENTIMENT"
        if pcr_oi >= 0.9:
            return 0.0, "BALANCED_IRON_CONDOR_FRIENDLY", "BALANCED"
        if pcr_oi >= 0.7:
            return -3.0, "MILD_BULLISH_SENTIMENT_MILD_BEAR_CONTRARIAN", "MILD_BULLISH_SENTIMENT"
        return -7.0, "EXTREME_GREED_CONTRARIAN_BEAR", "EXTREME_GREED"

    @staticmethod
    def _trend_flags(pcr_oi: float, pcr_5day_avg: float | None) -> list[str]:
        """Return PCR trend flags when current PCR is 15 percent away from average."""
        if pcr_5day_avg is None or pcr_5day_avg <= 0:
            return []
        if pcr_oi > pcr_5day_avg * 1.15:
            return ["PCR_RISING"]
        if pcr_oi < pcr_5day_avg * 0.85:
            return ["PCR_FALLING"]
        return []

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
            "pcr_regime": "UNKNOWN",
            "sentiment_label": "UNKNOWN",
            "caution_flags": [],
            "session_state": session_state,
            "top_driver": "pcr_unavailable",
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


__all__ = ["GreyPcrModule"]
