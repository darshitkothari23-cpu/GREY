"""
India-specific macro context module for GREY.

The module interprets USDINR, crude, and liquidity/rates inputs as cautious
context. It does not fetch data or make live-market action decisions.
"""

from __future__ import annotations

from typing import Any, Mapping

import grey_config


class GreyIndiaMacroModule:
    """Evaluate India-specific macro context for NIFTY and BANKNIFTY."""

    DEFAULT_CONFIG = {
        "usdinr_positive_threshold": 0.0025,
        "usdinr_negative_threshold": -0.0025,
        "usdinr_stress_threshold": 0.0060,
        "crude_positive_threshold": -0.0100,
        "crude_negative_threshold": 0.0100,
        "crude_stress_threshold": 0.0250,
        "liquidity_easing_threshold": -0.0020,
        "liquidity_tightening_threshold": 0.0020,
        "rate_easing_threshold": -0.03,
        "rate_tightening_threshold": 0.03,
        "weights": {
            "usdinr": 0.35,
            "crude": 0.30,
            "rate_liquidity": 0.35,
        },
        "session_confidence_multipliers": {
            "PRE_OPEN": 0.85,
            "OPENING_DRIVE": 0.70,
            "EARLY_TREND": 0.85,
            "MIDDAY": 0.75,
            "PRE_EVENT": 0.60,
            "CLOSING_DRIVE": 0.70,
            "POST_CLOSE": 0.65,
            "MARKET_CLOSED": 0.70,
        },
        "confidence_floor": 0.15,
        "confidence_cap": 0.90,
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        configured = getattr(grey_config, "GREY_INDIA_MACRO_MODULE", {})
        self.config = self._deep_merge(
            self.DEFAULT_CONFIG,
            configured if isinstance(configured, Mapping) else {},
        )
        if config is not None:
            self.config = self._deep_merge(self.config, config)

    def evaluate(self, market_data: dict, session_state: str) -> dict:
        """Return interpretable India macro context from supplied inputs."""
        data = market_data or {}
        base_state = str(session_state).split("|", 1)[0]
        usdinr_score, usdinr_signal = self._usdinr_signal(data)
        crude_score, crude_signal = self._crude_signal(data)
        rate_liquidity_score, rate_liquidity_signal = self._rate_liquidity_signal(data)
        liquidity_state = self._liquidity_state(rate_liquidity_signal)
        combined_score = self._combined_score(
            usdinr_score=usdinr_score,
            crude_score=crude_score,
            rate_liquidity_score=rate_liquidity_score,
        )
        macro_bias = self._macro_bias(combined_score)
        confidence = self._confidence(
            data=data,
            combined_score=combined_score,
            base_state=base_state,
        )

        return {
            "macro_bias": macro_bias,
            "liquidity_state": liquidity_state,
            "usdinr_signal": usdinr_signal,
            "crude_signal": crude_signal,
            "rate_liquidity_signal": rate_liquidity_signal,
            "confidence": confidence,
            "caution_flags": self._caution_flags(
                base_state=base_state,
                usdinr_signal=usdinr_signal,
                crude_signal=crude_signal,
                rate_liquidity_signal=rate_liquidity_signal,
            ),
            "session_state": base_state,
            "raw_components": {
                "usdinr_score": usdinr_score,
                "crude_score": crude_score,
                "rate_liquidity_score": rate_liquidity_score,
                "combined_score": combined_score,
            },
        }

    def _usdinr_signal(self, data: Mapping[str, Any]) -> tuple[float, str]:
        move = self._first_float(
            data,
            ("usdinr_change_pct", "usdinr_move_pct", "usd_inr_change_pct"),
        )
        if move is None:
            return 0.0, "UNKNOWN"

        if move >= self.config["usdinr_stress_threshold"]:
            return -1.0, "INR_STRESS"
        if move >= self.config["usdinr_positive_threshold"]:
            return -0.45, "INR_WEAKENING"
        if move <= self.config["usdinr_negative_threshold"]:
            return 0.35, "INR_STRENGTHENING"
        return 0.0, "NEUTRAL"

    def _crude_signal(self, data: Mapping[str, Any]) -> tuple[float, str]:
        move = self._first_float(
            data,
            ("brent_change_pct", "crude_change_pct", "oil_change_pct"),
        )
        if move is None:
            return 0.0, "UNKNOWN"

        if move >= self.config["crude_stress_threshold"]:
            return -0.90, "CRUDE_STRESS"
        if move >= self.config["crude_negative_threshold"]:
            return -0.45, "CRUDE_HEADWIND"
        if move <= self.config["crude_positive_threshold"]:
            return 0.35, "CRUDE_TAILWIND"
        return 0.0, "NEUTRAL"

    def _rate_liquidity_signal(self, data: Mapping[str, Any]) -> tuple[float, str]:
        liquidity = self._first_float(
            data,
            ("liquidity_change_pct", "system_liquidity_change_pct", "banking_liquidity_change_pct"),
        )
        rate_move = self._first_float(
            data,
            ("rate_change_bps", "yield_change_bps", "overnight_rate_change_bps"),
        )

        scores = []
        labels = []

        if liquidity is not None:
            if liquidity >= self.config["liquidity_tightening_threshold"]:
                scores.append(-0.55)
                labels.append("LIQUIDITY_TIGHTENING")
            elif liquidity <= self.config["liquidity_easing_threshold"]:
                scores.append(0.45)
                labels.append("LIQUIDITY_EASING")
            else:
                scores.append(0.0)
                labels.append("LIQUIDITY_NEUTRAL")

        if rate_move is not None:
            if rate_move >= self.config["rate_tightening_threshold"]:
                scores.append(-0.45)
                labels.append("RATES_FIRMING")
            elif rate_move <= self.config["rate_easing_threshold"]:
                scores.append(0.35)
                labels.append("RATES_EASING")
            else:
                scores.append(0.0)
                labels.append("RATES_NEUTRAL")

        if not scores:
            return 0.0, "UNKNOWN"

        score = sum(scores) / len(scores)
        if any(label in ("LIQUIDITY_TIGHTENING", "RATES_FIRMING") for label in labels):
            return score, "TIGHTENING_BIAS"
        if any(label in ("LIQUIDITY_EASING", "RATES_EASING") for label in labels):
            return score, "EASING_BIAS"
        return score, "NEUTRAL"

    def _liquidity_state(self, rate_liquidity_signal: str) -> str:
        if rate_liquidity_signal == "TIGHTENING_BIAS":
            return "TIGHT"
        if rate_liquidity_signal == "EASING_BIAS":
            return "EASY"
        if rate_liquidity_signal == "UNKNOWN":
            return "UNKNOWN"
        return "NEUTRAL"

    def _combined_score(
        self,
        *,
        usdinr_score: float,
        crude_score: float,
        rate_liquidity_score: float,
    ) -> float:
        weights = self.config["weights"]
        return (
            usdinr_score * weights["usdinr"]
            + crude_score * weights["crude"]
            + rate_liquidity_score * weights["rate_liquidity"]
        )

    @staticmethod
    def _macro_bias(score: float) -> str:
        if score >= 0.35:
            return "SUPPORTIVE"
        if score <= -0.35:
            return "HEADWIND"
        if score > 0.10:
            return "MILD_SUPPORTIVE"
        if score < -0.10:
            return "MILD_HEADWIND"
        return "NEUTRAL"

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
                ("usdinr_change_pct", "usdinr_move_pct", "usd_inr_change_pct"),
                ("brent_change_pct", "crude_change_pct", "oil_change_pct"),
                ("liquidity_change_pct", "system_liquidity_change_pct", "banking_liquidity_change_pct"),
                ("rate_change_bps", "yield_change_bps", "overnight_rate_change_bps"),
            )
        )
        coverage = min(1.0, observed_inputs / 3.0)
        signal_strength = min(1.0, abs(combined_score))
        confidence = (0.35 + 0.65 * signal_strength) * coverage
        confidence *= self.config["session_confidence_multipliers"].get(base_state, 0.75)
        return self._clamp(
            confidence,
            self.config["confidence_floor"],
            self.config["confidence_cap"],
        )

    @staticmethod
    def _caution_flags(
        *,
        base_state: str,
        usdinr_signal: str,
        crude_signal: str,
        rate_liquidity_signal: str,
    ) -> list[str]:
        flags = []
        if base_state in ("PRE_EVENT", "OPENING_DRIVE"):
            flags.append(f"SESSION_{base_state}_MACRO_CAUTION")
        if usdinr_signal == "INR_STRESS":
            flags.append("INR_STRESS")
        if crude_signal == "CRUDE_STRESS":
            flags.append("CRUDE_STRESS")
        if rate_liquidity_signal == "TIGHTENING_BIAS":
            flags.append("LIQUIDITY_TIGHTENING")
        if all(
            signal == "UNKNOWN"
            for signal in (usdinr_signal, crude_signal, rate_liquidity_signal)
        ):
            flags.append("MACRO_INPUTS_MISSING")
        return flags

    @staticmethod
    def _first_float(data: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = GreyIndiaMacroModule._to_float(data.get(key))
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


__all__ = ["GreyIndiaMacroModule"]
