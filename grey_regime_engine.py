"""
Market regime classifier for GREY.

Classifies broad market regime using dynamic, volatility-adjusted thresholds
(ATR) rather than static percentage moves.
"""

from __future__ import annotations

from typing import Any


class GreyRegimeEngine:
    def __init__(self) -> None:
        self.module_id = "REGIME"
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
        - price_change_from_open: Absolute points moved from opening print
        - atr_14: 14-period Average True Range in points
        - volatility_ratio: Current VIX / 30-day median VIX, optional
        """
        data = market_data or {}
        price_change = self._to_float(data.get("price_change_from_open"))
        atr_14 = self._to_float(data.get("atr_14"))
        volatility_ratio = self._to_float(data.get("volatility_ratio")) or 1.0

        if price_change is None or atr_14 is None or atr_14 <= 0:
            return self._empty_packet("INSUFFICIENT_DATA", "Missing price or ATR data.")

        atr_move = price_change / atr_14
        raw_score = (atr_move / 1.5) * 10.0
        r_regime = max(-10.0, min(10.0, round(raw_score)))
        regime_state = self._determine_state(atr_move, volatility_ratio)

        move_magnitude = abs(atr_move)
        confidence = min(1.0, 0.30 + (move_magnitude * 0.50))
        if session_state == "OPENING_DRIVE":
            confidence *= 0.70

        return {
            "module_id": self.module_id,
            "score": r_regime,
            "direction": self._direction_from_score(r_regime),
            "confidence": round(confidence, 3),
            "status": "ACTIVE",
            "reason": f"Regime: {regime_state} (Move: {atr_move:.2f} ATR)",
            "session_state": session_state,
            "is_expiry_sensitive": is_expiry_sensitive,
            "raw_components": {
                "regime_state": regime_state,
                "atr_move": round(atr_move, 3),
                "atr_14": atr_14,
            },
        }

    def _determine_state(self, atr_move: float, vol_ratio: float) -> str:
        if vol_ratio > 1.25 and abs(atr_move) < 0.5:
            return "VOLATILE_CHOP"
        if atr_move >= 1.0:
            return "TRENDING_UP"
        if atr_move <= -1.0:
            return "TRENDING_DOWN"
        if atr_move > 0.5:
            return "DRIFTING_UP"
        if atr_move < -0.5:
            return "DRIFTING_DOWN"
        return "RANGE_BOUND"

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


__all__ = ["GreyRegimeEngine"]
