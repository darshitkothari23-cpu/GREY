"""
Global and overnight risk context module for GREY.

The module interprets overseas cues as context for Indian index markets. It
does not fetch data or make live-market action decisions.
"""

from __future__ import annotations

from typing import Any, Mapping

import grey_config


class GreyGlobalRiskModule:
    """Evaluate overnight and global risk sentiment from supplied market data."""

    DEFAULT_CONFIG = {
        "positive_threshold": 0.003,
        "negative_threshold": -0.003,
        "strong_positive_threshold": 0.008,
        "strong_negative_threshold": -0.008,
        "volatility_risk_on_threshold": -0.03,
        "volatility_risk_off_threshold": 0.05,
        "weights": {
            "gift_nifty": 0.40,
            "asia": 0.25,
            "us_futures": 0.25,
            "volatility_proxy": 0.10,
        },
        "session_importance": {
            "PRE_OPEN": 1.00,
            "OPENING_DRIVE": 0.95,
            "EARLY_TREND": 0.80,
            "MIDDAY": 0.45,
            "PRE_EVENT": 0.55,
            "CLOSING_DRIVE": 0.30,
            "POST_CLOSE": 0.40,
            "MARKET_CLOSED": 0.70,
        },
        "confidence_floor": 0.15,
        "confidence_cap": 0.95,
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        configured = getattr(grey_config, "GREY_GLOBAL_RISK_MODULE", {})
        self.config = self._deep_merge(
            self.DEFAULT_CONFIG,
            configured if isinstance(configured, Mapping) else {},
        )
        if config is not None:
            self.config = self._deep_merge(self.config, config)

    def evaluate(self, market_data: dict, session_state: str) -> dict:
        """Return interpretable global and overnight context signals."""
        data = market_data or {}
        base_state = str(session_state).split("|", 1)[0]
        gift_score, gift_signal = self._gift_nifty_signal(data)
        asia_score, asia_signal = self._basket_signal(
            data,
            keys=("asia_return_pct", "asia_market_tone", "nikkei_return_pct", "hang_seng_return_pct"),
        )
        us_score, us_signal = self._basket_signal(
            data,
            keys=("us_futures_return_pct", "spx_futures_return_pct", "nasdaq_futures_return_pct"),
        )
        volatility_score, volatility_signal = self._volatility_proxy_signal(data)
        session_importance = self._session_importance(base_state)
        combined_score = self._combined_score(
            gift_score=gift_score,
            asia_score=asia_score,
            us_score=us_score,
            volatility_score=volatility_score,
        )
        effective_score = combined_score * session_importance
        global_risk_bias = self._bias_label(effective_score)
        confidence = self._confidence(
            data=data,
            combined_score=combined_score,
            session_importance=session_importance,
            base_state=base_state,
        )

        return {
            "global_risk_bias": global_risk_bias,
            "overnight_context": self._overnight_context(
                global_risk_bias,
                session_importance,
            ),
            "gift_nifty_signal": gift_signal,
            "asia_signal": asia_signal,
            "us_futures_signal": us_signal,
            "volatility_proxy_signal": volatility_signal,
            "confidence": confidence,
            "caution_flags": self._caution_flags(
                base_state=base_state,
                global_risk_bias=global_risk_bias,
                volatility_signal=volatility_signal,
                session_importance=session_importance,
            ),
            "session_state": base_state,
            "raw_components": {
                "gift_nifty_score": gift_score,
                "asia_score": asia_score,
                "us_futures_score": us_score,
                "volatility_proxy_score": volatility_score,
                "combined_score": combined_score,
                "session_importance": session_importance,
                "effective_score": effective_score,
            },
        }

    def _gift_nifty_signal(self, data: Mapping[str, Any]) -> tuple[float, str]:
        value = self._first_float(
            data,
            (
                "gift_nifty_return_pct",
                "gift_nifty_gap_pct",
                "gift_nifty_change_pct",
            ),
        )
        score, label = self._score_return(value)
        return score, f"GIFT_NIFTY_{label}"

    def _basket_signal(
        self,
        data: Mapping[str, Any],
        keys: tuple[str, ...],
    ) -> tuple[float, str]:
        values = [
            self._to_float(data.get(key))
            for key in keys
            if self._to_float(data.get(key)) is not None
        ]
        if not values:
            return 0.0, "UNKNOWN"

        average_value = sum(values) / len(values)
        return self._score_return(average_value)

    def _volatility_proxy_signal(self, data: Mapping[str, Any]) -> tuple[float, str]:
        value = self._first_float(
            data,
            (
                "volatility_proxy_change_pct",
                "vix_change_pct",
                "india_vix_change_pct",
                "us_vix_change_pct",
            ),
        )
        if value is None:
            return 0.0, "UNKNOWN"

        if value >= self.config["volatility_risk_off_threshold"]:
            return -1.0, "RISK_OFF"
        if value <= self.config["volatility_risk_on_threshold"]:
            return 0.7, "RISK_ON"
        return 0.0, "NEUTRAL"

    def _score_return(self, value: float | None) -> tuple[float, str]:
        if value is None:
            return 0.0, "UNKNOWN"

        if value >= self.config["strong_positive_threshold"]:
            return 1.0, "STRONG_RISK_ON"
        if value >= self.config["positive_threshold"]:
            return 0.6, "RISK_ON"
        if value <= self.config["strong_negative_threshold"]:
            return -1.0, "STRONG_RISK_OFF"
        if value <= self.config["negative_threshold"]:
            return -0.6, "RISK_OFF"
        return 0.0, "NEUTRAL"

    def _combined_score(
        self,
        *,
        gift_score: float,
        asia_score: float,
        us_score: float,
        volatility_score: float,
    ) -> float:
        weights = self.config["weights"]
        return (
            gift_score * weights["gift_nifty"]
            + asia_score * weights["asia"]
            + us_score * weights["us_futures"]
            + volatility_score * weights["volatility_proxy"]
        )

    def _bias_label(self, score: float) -> str:
        if score >= 0.45:
            return "RISK_ON"
        if score <= -0.45:
            return "RISK_OFF"
        if score > 0.10:
            return "MILD_RISK_ON"
        if score < -0.10:
            return "MILD_RISK_OFF"
        return "NEUTRAL"

    def _overnight_context(
        self,
        global_risk_bias: str,
        session_importance: float,
    ) -> str:
        if session_importance <= 0.45:
            return f"{global_risk_bias}_LOW_INTRADAY_WEIGHT"
        return f"{global_risk_bias}_CONTEXT"

    def _confidence(
        self,
        *,
        data: Mapping[str, Any],
        combined_score: float,
        session_importance: float,
        base_state: str,
    ) -> float:
        observed_inputs = sum(
            self._first_float(data, keys) is not None
            for keys in (
                ("gift_nifty_return_pct", "gift_nifty_gap_pct", "gift_nifty_change_pct"),
                ("asia_return_pct", "asia_market_tone", "nikkei_return_pct", "hang_seng_return_pct"),
                ("us_futures_return_pct", "spx_futures_return_pct", "nasdaq_futures_return_pct"),
                ("volatility_proxy_change_pct", "vix_change_pct", "india_vix_change_pct", "us_vix_change_pct"),
            )
        )
        coverage = min(1.0, observed_inputs / 3.0)
        signal_strength = min(1.0, abs(combined_score))
        confidence = (0.35 + 0.65 * signal_strength) * coverage * session_importance
        if base_state in ("MIDDAY", "CLOSING_DRIVE"):
            confidence *= 0.85
        return self._clamp(
            confidence,
            self.config["confidence_floor"],
            self.config["confidence_cap"],
        )

    def _caution_flags(
        self,
        *,
        base_state: str,
        global_risk_bias: str,
        volatility_signal: str,
        session_importance: float,
    ) -> list[str]:
        flags = []
        if session_importance <= 0.45:
            flags.append("GLOBAL_CUES_DE_EMPHASIZED")
        if base_state in ("PRE_OPEN", "OPENING_DRIVE"):
            flags.append("OVERNIGHT_CONTEXT_ACTIVE")
        if global_risk_bias in ("RISK_OFF", "MILD_RISK_OFF"):
            flags.append("GLOBAL_RISK_OFF")
        if volatility_signal == "RISK_OFF":
            flags.append("VOLATILITY_PROXY_RISK_OFF")
        return flags

    def _session_importance(self, session_state: str) -> float:
        return float(self.config["session_importance"].get(session_state, 0.50))

    @staticmethod
    def _first_float(data: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = GreyGlobalRiskModule._to_float(data.get(key))
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


__all__ = ["GreyGlobalRiskModule"]
