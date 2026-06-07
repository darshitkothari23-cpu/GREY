"""
Sector leadership and breadth context module for GREY.

The module interprets sector participation for Indian index context. It does
not fetch data or make live-market action decisions.
"""

from __future__ import annotations

from typing import Any, Mapping

import grey_config


class GreySectorRotationModule:
    """Evaluate sector leadership, rotation, and breadth context."""

    DEFAULT_CONFIG = {
        "positive_threshold": 0.004,
        "negative_threshold": -0.004,
        "strong_positive_threshold": 0.010,
        "strong_negative_threshold": -0.010,
        "breadth_strong_threshold": 0.60,
        "breadth_weak_threshold": 0.40,
        "narrow_leadership_threshold": 0.35,
        "weights": {
            "banking": 0.35,
            "it": 0.20,
            "energy": 0.20,
            "defensive": 0.10,
            "breadth": 0.15,
        },
        "session_confidence_multipliers": {
            "PRE_OPEN": 0.65,
            "OPENING_DRIVE": 0.70,
            "EARLY_TREND": 0.90,
            "MIDDAY": 0.85,
            "PRE_EVENT": 0.70,
            "CLOSING_DRIVE": 0.90,
            "POST_CLOSE": 0.65,
            "MARKET_CLOSED": 0.55,
        },
        "confidence_floor": 0.15,
        "confidence_cap": 0.90,
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        configured = getattr(grey_config, "GREY_SECTOR_ROTATION_MODULE", {})
        self.config = self._deep_merge(
            self.DEFAULT_CONFIG,
            configured if isinstance(configured, Mapping) else {},
        )
        if config is not None:
            self.config = self._deep_merge(self.config, config)

    def evaluate(self, market_data: dict, session_state: str) -> dict:
        """Return interpretable sector leadership and breadth context."""
        data = market_data or {}
        base_state = str(session_state).split("|", 1)[0]
        banking_score, banking_signal = self._sector_signal(
            data,
            ("private_banks_return_pct", "banking_return_pct", "bank_nifty_return_pct"),
            "BANKING",
        )
        it_score, it_signal = self._sector_signal(
            data,
            ("it_return_pct", "nifty_it_return_pct"),
            "IT",
        )
        energy_score, energy_signal = self._sector_signal(
            data,
            ("energy_return_pct", "oil_gas_return_pct", "nifty_energy_return_pct"),
            "ENERGY",
        )
        defensive_score, defensive_signal = self._defensive_signal(data)
        breadth_score, breadth_state = self._breadth_state(data)
        leadership_state = self._leadership_state(
            banking_score=banking_score,
            it_score=it_score,
            energy_score=energy_score,
            defensive_score=defensive_score,
            breadth_state=breadth_state,
        )
        combined_score = self._combined_score(
            banking_score=banking_score,
            it_score=it_score,
            energy_score=energy_score,
            defensive_score=defensive_score,
            breadth_score=breadth_score,
            leadership_state=leadership_state,
        )
        sector_bias = self._sector_bias(combined_score, breadth_state, leadership_state)
        confidence = self._confidence(
            data=data,
            combined_score=combined_score,
            base_state=base_state,
        )

        return {
            "sector_bias": sector_bias,
            "leadership_state": leadership_state,
            "breadth_state": breadth_state,
            "banking_signal": banking_signal,
            "it_signal": it_signal,
            "energy_signal": energy_signal,
            "defensive_signal": defensive_signal,
            "confidence": confidence,
            "caution_flags": self._caution_flags(
                base_state=base_state,
                leadership_state=leadership_state,
                breadth_state=breadth_state,
                banking_signal=banking_signal,
            ),
            "session_state": base_state,
            "raw_components": {
                "banking_score": banking_score,
                "it_score": it_score,
                "energy_score": energy_score,
                "defensive_score": defensive_score,
                "breadth_score": breadth_score,
                "combined_score": combined_score,
            },
        }

    def _sector_signal(
        self,
        data: Mapping[str, Any],
        keys: tuple[str, ...],
        label_prefix: str,
    ) -> tuple[float, str]:
        move = self._first_float(data, keys)
        score, label = self._score_return(move)
        return score, f"{label_prefix}_{label}"

    def _defensive_signal(self, data: Mapping[str, Any]) -> tuple[float, str]:
        move = self._first_float(
            data,
            ("defensive_return_pct", "fmcg_pharma_return_pct", "fmcg_return_pct", "pharma_return_pct"),
        )
        score, label = self._score_return(move)
        return score, f"DEFENSIVE_{label}"

    def _breadth_state(self, data: Mapping[str, Any]) -> tuple[float, str]:
        breadth = self._first_float(
            data,
            ("sector_breadth", "advance_decline_ratio", "breadth_ratio", "sectors_positive_ratio"),
        )
        if breadth is None:
            return 0.0, "UNKNOWN"

        normalized = self._clamp_unit(breadth)
        if normalized >= self.config["breadth_strong_threshold"]:
            return 0.75, "BROAD"
        if normalized <= self.config["breadth_weak_threshold"]:
            return -0.75, "WEAK"
        return 0.0, "MIXED"

    def _leadership_state(
        self,
        *,
        banking_score: float,
        it_score: float,
        energy_score: float,
        defensive_score: float,
        breadth_state: str,
    ) -> str:
        scores = {
            "BANKING": banking_score,
            "IT": it_score,
            "ENERGY": energy_score,
            "DEFENSIVE": defensive_score,
        }
        positive_leaders = [
            sector for sector, score in scores.items()
            if score >= self.config["narrow_leadership_threshold"]
        ]
        negative_leaders = [
            sector for sector, score in scores.items()
            if score <= -self.config["narrow_leadership_threshold"]
        ]

        if breadth_state == "WEAK" and len(positive_leaders) == 1:
            return f"NARROW_{positive_leaders[0]}_LED"
        if breadth_state == "BROAD" and len(positive_leaders) >= 2:
            return "BROAD_LEADERSHIP"
        if len(negative_leaders) >= 2:
            return "BROAD_SECTOR_PRESSURE"
        if positive_leaders:
            return f"{positive_leaders[0]}_LEADERSHIP"
        if negative_leaders:
            return f"{negative_leaders[0]}_DRAG"
        return "MIXED"

    def _combined_score(
        self,
        *,
        banking_score: float,
        it_score: float,
        energy_score: float,
        defensive_score: float,
        breadth_score: float,
        leadership_state: str,
    ) -> float:
        weights = self.config["weights"]
        score = (
            banking_score * weights["banking"]
            + it_score * weights["it"]
            + energy_score * weights["energy"]
            + defensive_score * weights["defensive"]
            + breadth_score * weights["breadth"]
        )
        if leadership_state.startswith("NARROW_"):
            score -= 0.25
        return self._clamp(score, -1.0, 1.0)

    def _sector_bias(
        self,
        combined_score: float,
        breadth_state: str,
        leadership_state: str,
    ) -> str:
        if leadership_state.startswith("NARROW_") and breadth_state == "WEAK":
            return "NARROW_SUPPORT"
        if combined_score >= 0.35:
            return "BROAD_SUPPORTIVE" if breadth_state == "BROAD" else "SUPPORTIVE"
        if combined_score <= -0.35:
            return "DETERIORATING"
        if combined_score > 0.10:
            return "MILD_SUPPORTIVE"
        if combined_score < -0.10:
            return "MILD_DETERIORATING"
        return "NEUTRAL"

    def _score_return(self, value: float | None) -> tuple[float, str]:
        if value is None:
            return 0.0, "UNKNOWN"
        if value >= self.config["strong_positive_threshold"]:
            return 1.0, "STRONG_UP"
        if value >= self.config["positive_threshold"]:
            return 0.55, "UP"
        if value <= self.config["strong_negative_threshold"]:
            return -1.0, "STRONG_DOWN"
        if value <= self.config["negative_threshold"]:
            return -0.55, "DOWN"
        return 0.0, "NEUTRAL"

    def _confidence(
        self,
        *,
        data: Mapping[str, Any],
        combined_score: float,
        base_state: str,
    ) -> float:
        observed_inputs = sum(
            self._first_float(data, keys) is not None
            for keys in (
                ("private_banks_return_pct", "banking_return_pct", "bank_nifty_return_pct"),
                ("it_return_pct", "nifty_it_return_pct"),
                ("energy_return_pct", "oil_gas_return_pct", "nifty_energy_return_pct"),
                ("defensive_return_pct", "fmcg_pharma_return_pct", "fmcg_return_pct", "pharma_return_pct"),
                ("sector_breadth", "advance_decline_ratio", "breadth_ratio", "sectors_positive_ratio"),
            )
        )
        coverage = min(1.0, observed_inputs / 4.0)
        signal_strength = min(1.0, abs(combined_score))
        confidence = (0.35 + 0.65 * signal_strength) * coverage
        confidence *= self.config["session_confidence_multipliers"].get(base_state, 0.80)
        return self._clamp(
            confidence,
            self.config["confidence_floor"],
            self.config["confidence_cap"],
        )

    @staticmethod
    def _caution_flags(
        *,
        base_state: str,
        leadership_state: str,
        breadth_state: str,
        banking_signal: str,
    ) -> list[str]:
        flags = []
        if base_state == "OPENING_DRIVE":
            flags.append("OPENING_DRIVE_TENTATIVE")
        if breadth_state == "WEAK":
            flags.append("WEAK_BREADTH")
        if leadership_state.startswith("NARROW_"):
            flags.append("NARROW_LEADERSHIP")
        if banking_signal in ("BANKING_DOWN", "BANKING_STRONG_DOWN"):
            flags.append("BANKING_DRAG")
        if breadth_state == "UNKNOWN":
            flags.append("BREADTH_INPUT_MISSING")
        return flags

    @staticmethod
    def _first_float(data: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = GreySectorRotationModule._to_float(data.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))

    @staticmethod
    def _clamp_unit(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @classmethod
    def _deep_merge(
        cls,
        base: Mapping[str, Any],
        override: Mapping[str, Any],
    ) -> dict:
        merged = dict(base)
        for key, value in override.items():
            if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
                merged[key] = cls._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged


__all__ = ["GreySectorRotationModule"]
