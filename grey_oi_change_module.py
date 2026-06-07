"""
Open-interest change module for GREY.

This module reads call/put OI change fields from market_data and converts them
into an interpretable option-chain momentum packet.
"""

from __future__ import annotations

from typing import Any


class GreyOiChangeModule:
    """Evaluate call/put OI buildup and unwinding context."""

    def __init__(self) -> None:
        # This identifier is used by GREY's aggregator and module vector.
        self.module_id = "OI_CHANGE"

    def evaluate(self, market_data: dict, session_state: str | None = None) -> dict:
        """Return a standard GREY packet for intraday OI change."""
        try:
            # Keep the input safe even if None is passed by a caller.
            data = market_data or {}

            # Read required total call OI change percent.
            call_change = self._to_float(data.get("call_oi_change_pct"))

            # Read required total put OI change percent.
            put_change = self._to_float(data.get("put_oi_change_pct"))

            # Read optional ATM call OI change.
            atm_call_change = self._to_float(data.get("atm_call_oi_change"))

            # Read optional ATM put OI change.
            atm_put_change = self._to_float(data.get("atm_put_oi_change"))

            # Missing total OI changes means the module cannot evaluate safely.
            if call_change is None or put_change is None:
                return self._empty_packet("INSUFFICIENT_DATA", "Missing call/put OI change data.", session_state)

            # Blend ATM OI into the effective signal when optional ATM data exists.
            effective_call = self._blend_with_atm(call_change, atm_call_change)
            effective_put = self._blend_with_atm(put_change, atm_put_change)

            # Classify each side as building, unwinding, or neutral.
            call_state = self._side_state("CALL", effective_call)
            put_state = self._side_state("PUT", effective_put)

            # Combine both sides into the requested OI momentum score.
            score, oi_momentum, dominant_side, caution_flags = self._combined_signal(call_state, put_state)

            # Confidence rises as the absolute effective OI move becomes larger.
            move_strength = max(abs(effective_call), abs(effective_put))
            confidence = min(0.90, 0.40 + min(move_strength / 40.0, 0.50))

            # Conflicted OI should be treated with lighter confidence.
            if "OI_CONFLICT" in caution_flags:
                confidence *= 0.65

            # Return the standard GREY packet plus OI-specific fields.
            return {
                "module_id": self.module_id,
                "score": float(score),
                "direction": self._direction_from_score(score),
                "confidence": round(confidence, 3),
                "status": "ACTIVE",
                "reason": oi_momentum,
                "raw_components": {
                    "call_oi_change_pct": call_change,
                    "put_oi_change_pct": put_change,
                    "atm_call_oi_change": atm_call_change,
                    "atm_put_oi_change": atm_put_change,
                    "effective_call_oi_change_pct": round(effective_call, 3),
                    "effective_put_oi_change_pct": round(effective_put, 3),
                    "call_state": call_state,
                    "put_state": put_state,
                },
                "oi_momentum": oi_momentum,
                "dominant_side": dominant_side,
                "caution_flags": caution_flags,
                "session_state": session_state,
                "top_driver": oi_momentum,
            }
        except Exception as exc:
            # GREY modules must never crash the aggregator loop.
            return self._empty_packet("UNAVAILABLE", f"OI change module failed safely: {exc}", session_state)

    @staticmethod
    def _blend_with_atm(overall_change: float, atm_change: float | None) -> float:
        """Give optional ATM data a 40 percent extra influence."""
        if atm_change is None:
            return overall_change
        return (overall_change + 0.40 * atm_change) / 1.40

    @staticmethod
    def _side_state(side: str, change_pct: float) -> str:
        """Classify one option side as building, unwinding, or neutral."""
        if change_pct > 10.0:
            return f"{side}_BUILDUP"
        if change_pct < -10.0:
            return f"{side}_UNWIND"
        return f"{side}_NEUTRAL"

    @staticmethod
    def _combined_signal(call_state: str, put_state: str) -> tuple[float, str, str, list[str]]:
        """Combine call and put OI states into the requested score logic."""
        put_building = put_state == "PUT_BUILDUP"
        put_unwinding = put_state == "PUT_UNWIND"
        call_building = call_state == "CALL_BUILDUP"
        call_unwinding = call_state == "CALL_UNWIND"

        if put_building and call_unwinding:
            return 7.0, "STRONG_BULL_PUT_BUILD_CALL_UNWIND", "MIXED", []
        if call_building and put_unwinding:
            return -7.0, "STRONG_BEAR_CALL_BUILD_PUT_UNWIND", "MIXED", []
        if put_building and not call_building:
            return -3.0, "MILD_BEAR_PUT_BUILDUP", "PUT_BUILDUP", []
        if call_building and not put_building:
            return -3.0, "MILD_BEAR_CALL_BUILDUP", "CALL_BUILDUP", []
        if put_unwinding and not call_unwinding:
            return 3.0, "MILD_BULL_PUT_UNWIND", "PUT_UNWIND", []
        if call_unwinding and not put_unwinding:
            return 3.0, "MILD_BULL_CALL_UNWIND", "CALL_UNWIND", []
        if call_state != "CALL_NEUTRAL" or put_state != "PUT_NEUTRAL":
            return 0.0, "MIXED_OI_SIGNALS", "MIXED", ["OI_CONFLICT"]
        return 0.0, "NEUTRAL_OI_CHANGE", "MIXED", []

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
            "oi_momentum": "UNKNOWN",
            "dominant_side": "MIXED",
            "caution_flags": [],
            "session_state": session_state,
            "top_driver": "oi_change_unavailable",
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


__all__ = ["GreyOiChangeModule"]
