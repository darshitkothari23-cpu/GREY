"""
Options microstructure evaluator for GREY.

Uses Volume-Weighted Open Interest Skew (S_oi) and Implied Volatility
Percentile (IVP) to generate a bounded -10 to +10 directional score.
"""

from __future__ import annotations

from typing import Any


class GreyOptionsMicrostructure:
    """Evaluate long-premium attractiveness from option microstructure inputs."""

    def __init__(self) -> None:
        self.module_id = "OPTIONS"
        self.stale_after_seconds = 120

    def evaluate(
        self,
        market_data: dict,
        session_state: str,
        is_expiry_sensitive: bool = False,
    ) -> dict:
        """
        Return the standardized GREY score packet.

        Expected market_data keys:
        - put_wall_weight: Sum of PE Volume * OI within 5% of spot
        - call_wall_weight: Sum of CE Volume * OI within 5% of spot
        - ivp: Rolling 30-day Implied Volatility Percentile, 0.0 to 1.0
        """
        data = market_data or {}
        put_weight = self._to_float(data.get("put_wall_weight")) or 0.0
        call_weight = self._to_float(data.get("call_wall_weight")) or 0.0
        ivp = self._to_float(data.get("ivp"))

        total_weight = put_weight + call_weight
        if total_weight <= 0 or ivp is None:
            return self._empty_packet(
                "INSUFFICIENT_DATA",
                "Missing or zero-weight chain data.",
            )

        ivp = max(0.0, min(1.0, ivp))
        s_oi = (put_weight - call_weight) / total_weight
        raw_score = s_oi * 10.0 * (1.0 - abs(ivp - 0.5))
        r_options = max(-10.0, min(10.0, round(raw_score)))

        skew_magnitude = abs(s_oi)
        confidence = min(1.0, 0.40 + (skew_magnitude * 0.60))
        if is_expiry_sensitive:
            confidence *= 0.85

        return {
            "module_id": self.module_id,
            "score": r_options,
            "direction": self._direction_from_score(r_options),
            "confidence": round(confidence, 3),
            "status": "ACTIVE",
            "reason": f"S_oi at {s_oi:.2f}, IVP at {ivp:.2f}",
            "session_state": session_state,
            "is_expiry_sensitive": is_expiry_sensitive,
            "raw_components": {
                "s_oi": round(s_oi, 3),
                "ivp": round(ivp, 3),
                "put_weight": put_weight,
                "call_weight": call_weight,
            },
        }

    def _direction_from_score(self, score: float) -> str:
        if score >= 3.0:
            return "BULL"
        if score <= -3.0:
            return "BEAR"
        return "NEUTRAL"

    def _empty_packet(self, status: str, reason: str) -> dict:
        return {
            "module_id": self.module_id,
            "score": 0.0,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "status": status,
            "reason": reason,
            "raw_components": {},
        }

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


__all__ = ["GreyOptionsMicrostructure"]
