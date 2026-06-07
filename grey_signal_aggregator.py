"""
Composite signal aggregator for GREY.

The aggregator combines module context into one interpretable view while
preserving module-level contributions, conflicts, and caution state.
"""

from __future__ import annotations

from typing import Any, Mapping

import grey_config


class GreySignalAggregator:
    """Aggregate GREY module outputs into an interpretable composite view."""

    DEFAULT_CONFIG = {
        "module_weights": {
            "REGIME": 1.20,
            "OPTIONS": 1.00,
            "KRONOS": 0.90,
            "VIX_REGIME": 1.30,
            "PCR": 0.95,
            "EXPIRY_CYCLE": 1.10,
            "OI_CHANGE": 1.00,
            "CALENDAR": 0.80,
            "GLOBAL": 0.70,
            "GLOBAL_RISK": 0.70,
            "INDIA_MACRO": 0.75,
            "SECTOR": 0.85,
            "DATA_QUALITY": 0.00,
        },
        "session_multipliers": {
            "PRE_OPEN": {
                "GLOBAL": 1.25,
                "GLOBAL_RISK": 1.25,
                "INDIA_MACRO": 1.10,
                "REGIME": 0.80,
            },
            "OPENING_DRIVE": {
                "REGIME": 1.15,
                "KRONOS": 0.70,
                "GLOBAL": 1.10,
                "GLOBAL_RISK": 1.10,
                "SECTOR": 0.85,
            },
            "EARLY_TREND": {
                "REGIME": 1.20,
                "OPTIONS": 1.10,
                "KRONOS": 1.10,
                "SECTOR": 1.00,
            },
            "MIDDAY": {
                "KRONOS": 1.20,
                "GLOBAL": 0.60,
                "GLOBAL_RISK": 0.60,
                "INDIA_MACRO": 0.75,
                "SECTOR": 1.05,
            },
            "PRE_EVENT": {
                "CALENDAR": 1.40,
                "KRONOS": 0.50,
                "OPTIONS": 0.85,
                "REGIME": 0.85,
            },
            "CLOSING_DRIVE": {
                "REGIME": 1.00,
                "OPTIONS": 1.15,
                "KRONOS": 1.00,
                "SECTOR": 1.00,
                "GLOBAL": 0.45,
                "GLOBAL_RISK": 0.45,
            },
        },
        "conflict_high_threshold": 0.50,
        "conflict_medium_threshold": 0.25,
        "confidence_conflict_penalty": 0.35,
        "confidence_medium_conflict_penalty": 0.15,
        "score_direction_threshold": 0.20,
        "max_top_drivers": 5,
        "default_confidence_cap": 1.00,
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        configured = getattr(grey_config, "GREY_SIGNAL_AGGREGATOR", {})
        self.config = self._deep_merge(
            self.DEFAULT_CONFIG,
            configured if isinstance(configured, Mapping) else {},
        )
        if config is not None:
            self.config = self._deep_merge(self.config, config)

    def aggregate(
        self,
        module_outputs: dict,
        session_state: str,
        active_modules: list | None = None,
    ) -> dict:
        """Aggregate module outputs into a GREY composite view."""
        outputs = module_outputs or {}
        active_set = set(active_modules) if active_modules is not None else None
        base_state = str(session_state).split("|", 1)[0]
        module_vector = {}
        weighted_score_sum = 0.0
        weighted_confidence_sum = 0.0
        total_weight = 0.0
        caution_flags = []
        confidence_cap = self.config["default_confidence_cap"]
        freeze_suggestion = False

        for module_id, output in outputs.items():
            normalized_id = str(module_id).upper()
            if active_set is not None and normalized_id not in {str(item).upper() for item in active_set}:
                continue
            if not isinstance(output, Mapping):
                continue

            if self._is_guard_output(output):
                confidence_cap = min(
                    confidence_cap,
                    self._to_float(output.get("recommended_confidence_cap")) or confidence_cap,
                )
                freeze_suggestion = freeze_suggestion or bool(output.get("freeze_suggestion"))
                caution_flags.extend(output.get("notes", []))
                module_vector[normalized_id] = self._guard_vector(output)
                continue

            contribution = self._module_contribution(normalized_id, output, base_state)
            module_vector[normalized_id] = contribution
            weighted_score_sum += contribution["weighted_score"]
            weighted_confidence_sum += contribution["confidence"] * contribution["effective_weight"]
            total_weight += contribution["effective_weight"]
            caution_flags.extend(output.get("caution_flags", []))

            module_cap = self._to_float(output.get("recommended_confidence_cap"))
            if module_cap is not None:
                confidence_cap = min(confidence_cap, self._clamp(module_cap, 0.0, 1.0))

            if bool(output.get("freeze_suggestion")):
                freeze_suggestion = True
                caution_flags.append(f"{normalized_id}_FREEZE_SUGGESTION")

            if self._calendar_freeze(output):
                freeze_suggestion = True
                caution_flags.append("CALENDAR_FREEZE_CONTRIBUTION")

        composite_score = 0.0 if total_weight == 0 else weighted_score_sum / total_weight
        conflict_state, conflict_penalty = self._conflict_state(module_vector)
        if total_weight == 0:
            confidence = 0.0
        else:
            confidence = weighted_confidence_sum / total_weight
            confidence = max(0.0, confidence - conflict_penalty)
        confidence = min(confidence, confidence_cap)
        if freeze_suggestion:
            confidence = 0.0

        direction_bias = self._direction_bias(composite_score)
        caution_state = self._caution_state(
            freeze_suggestion=freeze_suggestion,
            confidence_cap=confidence_cap,
            conflict_state=conflict_state,
            caution_flags=caution_flags,
        )

        return {
            "composite_score": round(composite_score, 3),
            "direction_bias": direction_bias,
            "confidence": round(confidence, 3),
            "top_drivers": self._top_drivers(module_vector),
            "conflict_state": conflict_state,
            "caution_state": caution_state,
            "module_vector": module_vector,
            "recommended_interpretation": self._recommended_interpretation(
                direction_bias=direction_bias,
                confidence=confidence,
                conflict_state=conflict_state,
                caution_state=caution_state,
            ),
        }

    def _module_contribution(
        self,
        module_id: str,
        output: Mapping[str, Any],
        session_state: str,
    ) -> dict:
        raw_score = self._score_from_output(output)
        confidence = self._confidence_from_output(output)
        base_weight = self._module_weight(module_id)
        session_multiplier = self._session_multiplier(session_state, module_id)
        effective_weight = base_weight * session_multiplier
        weighted_score = raw_score * confidence * effective_weight
        return {
            "module_id": module_id,
            "raw_score": round(raw_score, 3),
            "direction": self._direction_from_score(raw_score),
            "confidence": round(confidence, 3),
            "base_weight": round(base_weight, 3),
            "session_multiplier": round(session_multiplier, 3),
            "effective_weight": round(effective_weight, 3),
            "weighted_score": round(weighted_score, 3),
            "top_driver": self._top_driver(output),
        }

    def _score_from_output(self, output: Mapping[str, Any]) -> float:
        if output.get("score") is not None:
            return self._clamp(float(output["score"]) / 10.0, -1.0, 1.0)
        if output.get("composite_score") is not None:
            return self._clamp(self._to_float(output.get("composite_score")) or 0.0, -1.0, 1.0)

        for key in (
            "direction",
            "direction_bias",
            "global_risk_bias",
            "macro_bias",
            "sector_bias",
            "regime_label",
        ):
            if key in output:
                return self._score_from_label(output.get(key))
        return 0.0

    def _score_from_label(self, value: Any) -> float:
        text = str(value or "").upper()
        if text in ("BULL", "RISK_ON", "SUPPORTIVE", "BROAD_SUPPORTIVE", "TRENDING_UP"):
            return 0.75
        if text in ("BEAR", "RISK_OFF", "HEADWIND", "DETERIORATING", "TRENDING_DOWN"):
            return -0.75
        if "MILD_RISK_ON" in text or "MILD_SUPPORTIVE" in text:
            return 0.35
        if "MILD_RISK_OFF" in text or "MILD_HEADWIND" in text or "MILD_DETERIORATING" in text:
            return -0.35
        if text == "NARROW_SUPPORT":
            return 0.15
        if text == "VOLATILE" or text == "EVENT_RISK":
            return -0.20
        return 0.0

    def _confidence_from_output(self, output: Mapping[str, Any]) -> float:
        confidence = output.get("confidence", output.get("confidence_value", 0.0))
        return self._clamp(self._to_float(confidence) or 0.0, 0.0, 1.0)

    def _module_weight(self, module_id: str) -> float:
        weights = self.config["module_weights"]
        base_id = module_id.removesuffix("_MODULE")
        return float(weights.get(module_id, weights.get(base_id, 1.0)))

    def _session_multiplier(self, session_state: str, module_id: str) -> float:
        multipliers = self.config["session_multipliers"].get(session_state, {})
        return float(multipliers.get(module_id, 1.0))

    def _conflict_state(self, module_vector: Mapping[str, Any]) -> tuple[str, float]:
        bullish = 0.0
        bearish = 0.0
        for contribution in module_vector.values():
            if not isinstance(contribution, Mapping) or contribution.get("is_guard"):
                continue
            weighted_abs = abs(contribution.get("weighted_score", 0.0))
            if contribution.get("direction") == "BULL":
                bullish += weighted_abs
            elif contribution.get("direction") == "BEAR":
                bearish += weighted_abs

        if bullish == 0.0 or bearish == 0.0:
            return "ALIGNED_OR_NEUTRAL", 0.0

        conflict_ratio = min(bullish, bearish) / max(bullish, bearish)
        if conflict_ratio >= self.config["conflict_high_threshold"]:
            return "HIGH_CONFLICT", self.config["confidence_conflict_penalty"]
        if conflict_ratio >= self.config["conflict_medium_threshold"]:
            return "MEDIUM_CONFLICT", self.config["confidence_medium_conflict_penalty"]
        return "LOW_CONFLICT", 0.0

    def _top_drivers(self, module_vector: Mapping[str, Any]) -> list[dict]:
        drivers = []
        for module_id, contribution in module_vector.items():
            if not isinstance(contribution, Mapping) or contribution.get("is_guard"):
                continue
            drivers.append({
                "module_id": module_id,
                "direction": contribution["direction"],
                "weighted_score": contribution["weighted_score"],
                "top_driver": contribution["top_driver"],
            })
        drivers.sort(key=lambda item: abs(item["weighted_score"]), reverse=True)
        return drivers[: self.config["max_top_drivers"]]

    def _caution_state(
        self,
        *,
        freeze_suggestion: bool,
        confidence_cap: float,
        conflict_state: str,
        caution_flags: list,
    ) -> dict:
        unique_flags = sorted({str(flag) for flag in caution_flags if flag})
        if freeze_suggestion:
            level = "FREEZE"
        elif confidence_cap <= 0.40 or conflict_state == "HIGH_CONFLICT":
            level = "HIGH_CAUTION"
        elif confidence_cap < 1.0 or conflict_state in ("MEDIUM_CONFLICT", "LOW_CONFLICT") or unique_flags:
            level = "CAUTION"
        else:
            level = "NORMAL"
        return {
            "level": level,
            "freeze_suggestion": freeze_suggestion,
            "confidence_cap": round(confidence_cap, 3),
            "flags": unique_flags,
        }

    def _recommended_interpretation(
        self,
        *,
        direction_bias: str,
        confidence: float,
        conflict_state: str,
        caution_state: Mapping[str, Any],
    ) -> str:
        if caution_state["freeze_suggestion"]:
            return "Freeze GREY contribution; upstream guard or event risk requested no confidence contribution."
        if conflict_state == "HIGH_CONFLICT":
            return "Treat composite as contested; inspect module_vector and top_drivers before trusting the bias."
        if confidence < 0.35:
            return f"{direction_bias} bias is weak; use as context only."
        return f"{direction_bias} bias with disciplined confidence; review top_drivers for the why."

    def _guard_vector(self, output: Mapping[str, Any]) -> dict:
        return {
            "is_guard": True,
            "quality_state": output.get("quality_state", "UNKNOWN"),
            "recommended_confidence_cap": self._to_float(output.get("recommended_confidence_cap")),
            "freeze_suggestion": bool(output.get("freeze_suggestion")),
        }

    @staticmethod
    def _calendar_freeze(output: Mapping[str, Any]) -> bool:
        raw_inputs = output.get("raw_inputs", {})
        return isinstance(raw_inputs, Mapping) and bool(raw_inputs.get("freeze_contribution"))

    @staticmethod
    def _is_guard_output(output: Mapping[str, Any]) -> bool:
        return (
            "quality_state" in output
            and "recommended_confidence_cap" in output
            and "freeze_suggestion" in output
        )

    def _direction_bias(self, score: float) -> str:
        threshold = self.config["score_direction_threshold"]
        if score >= threshold:
            return "BULL"
        if score <= -threshold:
            return "BEAR"
        return "NEUTRAL"

    @staticmethod
    def _direction_from_score(score: float) -> str:
        if score > 0.10:
            return "BULL"
        if score < -0.10:
            return "BEAR"
        return "NEUTRAL"

    @staticmethod
    def _top_driver(output: Mapping[str, Any]) -> str:
        if output.get("top_driver"):
            return str(output["top_driver"])
        for key in (
            "regime_label",
            "iv_regime",
            "global_risk_bias",
            "macro_bias",
            "sector_bias",
            "quality_state",
        ):
            if output.get(key):
                return f"{key}={output[key]}"
        return "not_provided"

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


__all__ = ["GreySignalAggregator"]
