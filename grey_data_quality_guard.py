"""
Data quality and market plumbing guard for GREY.

The guard produces confidence caps and freeze suggestions from input quality
checks. It is designed for replay, paper, and review workflows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

import grey_config


class GreyDataQualityGuard:
    """Detect stale, missing, noisy, contradictory, or unreliable inputs."""

    DEFAULT_CONFIG = {
        "required_inputs": (
            "price",
            "timestamp",
            "session_state",
        ),
        "important_inputs": (
            "volume",
            "spread_pct",
            "implied_volatility",
            "module_outputs",
        ),
        "max_stale_seconds": 120,
        "max_jump_pct": 0.03,
        "max_spread_pct": 0.05,
        "min_liquidity_score": 0.35,
        "contradiction_confidence_threshold": 0.65,
        "confidence_caps": {
            "GOOD": 1.00,
            "DEGRADED": 0.70,
            "POOR": 0.40,
            "UNUSABLE": 0.00,
        },
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        configured = getattr(grey_config, "GREY_DATA_QUALITY_GUARD", {})
        self.config = self._deep_merge(
            self.DEFAULT_CONFIG,
            configured if isinstance(configured, Mapping) else {},
        )
        if config is not None:
            self.config = self._deep_merge(self.config, config)

    def evaluate(self, data_inputs: dict, dt=None) -> dict:
        """Return interpretable quality flags and confidence guardrails."""
        inputs = data_inputs or {}
        current_dt = self._parse_dt(dt) if dt is not None else self._now()
        missing_data_flags = self._missing_data_flags(inputs)
        stale_data_flags = self._stale_data_flags(inputs, current_dt)
        noisy_value_flags = self._noisy_value_flags(inputs)
        contradiction_flags = self._contradiction_flags(inputs)
        market_plumbing_flags = self._market_plumbing_flags(inputs)
        quality_state = self._quality_state(
            missing_data_flags=missing_data_flags,
            stale_data_flags=stale_data_flags,
            noisy_value_flags=noisy_value_flags,
            contradiction_flags=contradiction_flags,
            market_plumbing_flags=market_plumbing_flags,
        )
        freeze_suggestion = quality_state == "UNUSABLE" or bool(
            stale_data_flags and market_plumbing_flags
        )

        notes = self._notes(
            quality_state=quality_state,
            missing_data_flags=missing_data_flags,
            stale_data_flags=stale_data_flags,
            noisy_value_flags=noisy_value_flags,
            contradiction_flags=contradiction_flags,
            market_plumbing_flags=market_plumbing_flags,
            freeze_suggestion=freeze_suggestion,
        )

        return {
            "quality_state": quality_state,
            "stale_data_flags": stale_data_flags,
            "missing_data_flags": missing_data_flags,
            "contradiction_flags": contradiction_flags,
            "market_plumbing_flags": market_plumbing_flags,
            "recommended_confidence_cap": self.config["confidence_caps"][quality_state],
            "freeze_suggestion": freeze_suggestion,
            "notes": notes,
            "noisy_value_flags": noisy_value_flags,
        }

    def _missing_data_flags(self, inputs: Mapping[str, Any]) -> list[str]:
        flags = []
        for key in self.config["required_inputs"]:
            if self._is_missing(inputs.get(key)):
                flags.append(f"MISSING_REQUIRED_{key.upper()}")
        for key in self.config["important_inputs"]:
            if self._is_missing(inputs.get(key)):
                flags.append(f"MISSING_IMPORTANT_{key.upper()}")
        return flags

    def _stale_data_flags(
        self,
        inputs: Mapping[str, Any],
        current_dt: datetime,
    ) -> list[str]:
        flags = []
        timestamp = self._parse_dt(inputs.get("timestamp"))
        if timestamp is None:
            return flags

        age_seconds = (current_dt - timestamp).total_seconds()
        if age_seconds < 0:
            flags.append("TIMESTAMP_FROM_FUTURE")
        elif age_seconds > self.config["max_stale_seconds"]:
            flags.append(f"STALE_PRIMARY_FEED_{int(age_seconds)}S")

        module_outputs = inputs.get("module_outputs", {})
        if isinstance(module_outputs, Mapping):
            for module_id, output in module_outputs.items():
                if not isinstance(output, Mapping):
                    continue
                updated_at = self._parse_dt(output.get("updated_at"))
                stale_after = self._to_float(output.get("stale_after_seconds"))
                if updated_at is None or stale_after is None:
                    continue
                module_age = (current_dt - updated_at).total_seconds()
                if module_age > stale_after:
                    flags.append(f"STALE_MODULE_{str(module_id).upper()}")
        return flags

    def _noisy_value_flags(self, inputs: Mapping[str, Any]) -> list[str]:
        flags = []
        price = self._to_float(inputs.get("price"))
        previous_price = self._to_float(inputs.get("previous_price"))
        if price is not None and price <= 0:
            flags.append("BROKEN_PRICE")
        if price is not None and previous_price is not None and previous_price > 0:
            jump_pct = abs((price - previous_price) / previous_price)
            if jump_pct > self.config["max_jump_pct"]:
                flags.append("ABNORMAL_PRICE_JUMP")

        for key in ("implied_volatility", "iv_percentile", "spread_pct", "volume"):
            value = self._to_float(inputs.get(key))
            if value is None:
                continue
            if key in ("implied_volatility", "volume") and value < 0:
                flags.append(f"BROKEN_{key.upper()}")
            if key == "iv_percentile" and not 0 <= value <= 100:
                flags.append("BROKEN_IV_PERCENTILE")
            if key == "spread_pct" and value < 0:
                flags.append("BROKEN_SPREAD")
        return flags

    def _contradiction_flags(self, inputs: Mapping[str, Any]) -> list[str]:
        module_outputs = inputs.get("module_outputs", {})
        if not isinstance(module_outputs, Mapping):
            return []

        bullish = []
        bearish = []
        for module_id, output in module_outputs.items():
            if not isinstance(output, Mapping):
                continue
            confidence = self._module_confidence(output)
            if confidence < self.config["contradiction_confidence_threshold"]:
                continue
            direction = self._direction_from_output(output)
            if direction == "BULL":
                bullish.append(str(module_id))
            elif direction == "BEAR":
                bearish.append(str(module_id))

        if bullish and bearish:
            return [
                "HIGH_CONFIDENCE_MODULE_CONTRADICTION",
                f"BULLISH={','.join(sorted(bullish))}",
                f"BEARISH={','.join(sorted(bearish))}",
            ]
        return []

    def _market_plumbing_flags(self, inputs: Mapping[str, Any]) -> list[str]:
        flags = []
        spread_pct = self._to_float(inputs.get("spread_pct"))
        if spread_pct is not None and spread_pct > self.config["max_spread_pct"]:
            flags.append("WIDE_SPREAD")

        liquidity_score = self._to_float(inputs.get("liquidity_score"))
        if liquidity_score is not None and liquidity_score < self.config["min_liquidity_score"]:
            flags.append("THIN_LIQUIDITY")

        bid = self._to_float(inputs.get("bid"))
        ask = self._to_float(inputs.get("ask"))
        if bid is not None and ask is not None:
            if bid < 0 or ask <= 0 or ask < bid:
                flags.append("BROKEN_BID_ASK")
        if inputs.get("feed_status") in ("DOWN", "DEGRADED"):
            flags.append(f"FEED_{inputs['feed_status']}")
        return flags

    def _quality_state(
        self,
        *,
        missing_data_flags: list[str],
        stale_data_flags: list[str],
        noisy_value_flags: list[str],
        contradiction_flags: list[str],
        market_plumbing_flags: list[str],
    ) -> str:
        required_missing = [
            flag for flag in missing_data_flags if flag.startswith("MISSING_REQUIRED_")
        ]
        broken_flags = [
            flag for flag in noisy_value_flags + market_plumbing_flags
            if flag.startswith("BROKEN_")
        ]
        if required_missing or broken_flags:
            return "UNUSABLE"
        if stale_data_flags or len(market_plumbing_flags) >= 2:
            return "POOR"
        if missing_data_flags or noisy_value_flags or contradiction_flags or market_plumbing_flags:
            return "DEGRADED"
        return "GOOD"

    @staticmethod
    def _notes(
        *,
        quality_state: str,
        missing_data_flags: list[str],
        stale_data_flags: list[str],
        noisy_value_flags: list[str],
        contradiction_flags: list[str],
        market_plumbing_flags: list[str],
        freeze_suggestion: bool,
    ) -> list[str]:
        notes = [f"quality_state={quality_state}"]
        if missing_data_flags:
            notes.append("missing inputs detected")
        if stale_data_flags:
            notes.append("stale timestamps detected")
        if noisy_value_flags:
            notes.append("abnormal or broken values detected")
        if contradiction_flags:
            notes.append("cross-module contradiction detected")
        if market_plumbing_flags:
            notes.append("market plumbing quality is doubtful")
        if freeze_suggestion:
            notes.append("freeze suggested until data quality recovers")
        return notes

    def _direction_from_output(self, output: Mapping[str, Any]) -> str:
        for key in (
            "direction",
            "direction_bias",
            "global_risk_bias",
            "macro_bias",
            "sector_bias",
            "regime_label",
        ):
            if key in output:
                return self._direction_from_value(output.get(key))
        return "NEUTRAL"

    @staticmethod
    def _direction_from_value(value: Any) -> str:
        text = str(value or "").upper()
        if text in ("BULL", "RISK_ON", "SUPPORTIVE", "BROAD_SUPPORTIVE", "TRENDING_UP"):
            return "BULL"
        if text in ("BEAR", "RISK_OFF", "HEADWIND", "DETERIORATING", "TRENDING_DOWN"):
            return "BEAR"
        if "MILD_RISK_ON" in text or "MILD_SUPPORTIVE" in text:
            return "BULL"
        if "MILD_RISK_OFF" in text or "MILD_HEADWIND" in text or "MILD_DETERIORATING" in text:
            return "BEAR"
        return "NEUTRAL"

    @staticmethod
    def _module_confidence(output: Mapping[str, Any]) -> float:
        value = output.get("confidence", output.get("confidence_value", 0.0))
        return GreyDataQualityGuard._clamp_unit(GreyDataQualityGuard._to_float(value) or 0.0)

    @staticmethod
    def _is_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, (str, list, tuple, dict, set)) and not value:
            return True
        return False

    @staticmethod
    def _parse_dt(value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return GreyDataQualityGuard._as_naive_dt(value)
        try:
            text_value = str(value)
            if text_value.endswith("Z"):
                text_value = f"{text_value[:-1]}+00:00"
            return GreyDataQualityGuard._as_naive_dt(datetime.fromisoformat(text_value))
        except ValueError:
            return None

    @staticmethod
    def _as_naive_dt(value: datetime) -> datetime:
        return datetime(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
        )

    @staticmethod
    def _now() -> datetime:
        return GreyDataQualityGuard._as_naive_dt(datetime.now())

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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


__all__ = ["GreyDataQualityGuard"]
