"""
Base contract for GREY market intelligence modules.

Modules provide intelligence signals only. They must not depend on execution,
broker, or position-management components.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from math import exp
from typing import Any, Dict, Mapping


class GreyModuleBase(ABC):
    """Abstract base class shared by all GREY intelligence modules."""

    REQUIRED_OUTPUT_FIELDS = (
        "module_id",
        "score",
        "direction",
        "signal_type",
        "confidence",
        "confidence_value",
        "freshness",
        "raw_inputs",
        "top_driver",
        "updated_at",
        "stale_after_seconds",
        "status",
    )

    DIRECTION_VALUES = frozenset(("BULL", "BEAR", "NEUTRAL", "MIXED"))
    STATUS_VALUES = frozenset(("ACTIVE", "STALE", "UNAVAILABLE", "FROZEN"))
    SIGNAL_TYPE_VALUES = frozenset(("DIRECTIONAL", "RISK_GATE", "CONFIDENCE_GATE"))

    MIN_SCORE = -10.0
    MAX_SCORE = 10.0

    def __init__(
        self,
        module_id: str,
        stale_after_seconds: float,
        source_quality_weight: float = 1.0,
    ) -> None:
        if not module_id:
            raise ValueError("module_id is required")
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be greater than zero")

        self.module_id = module_id
        self.stale_after_seconds = float(stale_after_seconds)
        self.source_quality_weight = self._clamp_unit(source_quality_weight)

    @abstractmethod
    def compute(self) -> dict:
        """Return a GREY module output packet."""

    def run(self) -> dict:
        """
        Execute the module without allowing exceptions to escape.

        Aggregators should call this method instead of calling compute()
        directly so a module failure becomes an UNAVAILABLE packet.
        """
        try:
            output = self.compute()
            self.validate_output(output)
            return output
        except Exception as exc:
            return self.unavailable_output(error=exc)

    def validate_output(self, output: dict) -> bool:
        """
        Validate and normalize a GREY module output packet.

        Raises:
            ValueError: If the packet violates the output contract.
        """
        if not isinstance(output, dict):
            raise ValueError("output must be a dict")

        missing_fields = [
            field for field in self.REQUIRED_OUTPUT_FIELDS if field not in output
        ]
        if missing_fields:
            raise ValueError(f"output missing required fields: {missing_fields}")

        output["score"] = self.clamp_score(output["score"])
        output["freshness"] = self._validate_unit_interval(
            output["freshness"], "freshness"
        )
        output["confidence_value"] = self._validate_unit_interval(
            output["confidence_value"], "confidence_value"
        )

        if output["confidence"] != output["confidence_value"]:
            raise ValueError("confidence must match confidence_value")

        if output["direction"] not in self.DIRECTION_VALUES:
            raise ValueError(f"invalid direction: {output['direction']}")
        if output["status"] not in self.STATUS_VALUES:
            raise ValueError(f"invalid status: {output['status']}")
        if output["signal_type"] not in self.SIGNAL_TYPE_VALUES:
            raise ValueError(f"invalid signal_type: {output['signal_type']}")

        if not isinstance(output["raw_inputs"], Mapping):
            raise ValueError("raw_inputs must be a mapping")
        if output["stale_after_seconds"] <= 0:
            raise ValueError("stale_after_seconds must be greater than zero")

        return True

    def build_output(
        self,
        *,
        score: float,
        direction: str,
        signal_type: str,
        elapsed_seconds: float,
        raw_inputs: Mapping[str, Any],
        top_driver: str,
        agreement_factor: float = 1.0,
        status: str = "ACTIVE",
        updated_at: str | None = None,
    ) -> dict:
        """Build a valid GREY output packet from common module values."""
        freshness = self.compute_freshness(elapsed_seconds, self.stale_after_seconds)
        confidence_value = self.compute_confidence(
            freshness=freshness,
            source_quality_weight=self.source_quality_weight,
            agreement_factor=agreement_factor,
        )
        output = {
            "module_id": self.module_id,
            "score": self.clamp_score(score),
            "direction": direction,
            "signal_type": signal_type,
            "confidence": confidence_value,
            "confidence_value": confidence_value,
            "freshness": freshness,
            "raw_inputs": dict(raw_inputs),
            "top_driver": top_driver,
            "updated_at": updated_at or self.utcnow_iso(),
            "stale_after_seconds": self.stale_after_seconds,
            "status": status,
        }
        self.validate_output(output)
        return output

    def unavailable_output(self, error: Exception | None = None) -> dict:
        """Return a safe UNAVAILABLE packet for failed module computation."""
        raw_inputs: Dict[str, Any] = {}
        if error is not None:
            raw_inputs["error"] = str(error)

        return {
            "module_id": self.module_id,
            "score": 0.0,
            "direction": "NEUTRAL",
            "signal_type": "CONFIDENCE_GATE",
            "confidence": 0.0,
            "confidence_value": 0.0,
            "freshness": 0.0,
            "raw_inputs": raw_inputs,
            "top_driver": "unavailable",
            "updated_at": self.utcnow_iso(),
            "stale_after_seconds": self.stale_after_seconds,
            "status": "UNAVAILABLE",
        }

    @classmethod
    def clamp_score(cls, score: float) -> float:
        """Clamp score to the GREY contract range of -10.0 to 10.0."""
        numeric_score = float(score)
        return max(cls.MIN_SCORE, min(cls.MAX_SCORE, numeric_score))

    @staticmethod
    def compute_freshness(elapsed_seconds: float, stale_after_seconds: float) -> float:
        """Compute freshness using exp(-elapsed / (stale_after / 3.0))."""
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be greater than zero")

        elapsed = max(0.0, float(elapsed_seconds))
        denominator = float(stale_after_seconds) / 3.0
        return GreyModuleBase._clamp_unit(exp(-(elapsed / denominator)))

    @staticmethod
    def compute_confidence(
        *,
        freshness: float,
        source_quality_weight: float,
        agreement_factor: float,
    ) -> float:
        """Compute confidence from freshness, source quality, and agreement."""
        return GreyModuleBase._clamp_unit(
            float(freshness)
            * GreyModuleBase._clamp_unit(source_quality_weight)
            * GreyModuleBase._clamp_unit(agreement_factor)
        )

    @staticmethod
    def utcnow_iso() -> str:
        """Return a timezone-aware UTC ISO timestamp."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clamp_unit(value: float) -> float:
        numeric_value = float(value)
        return max(0.0, min(1.0, numeric_value))

    @staticmethod
    def _validate_unit_interval(value: float, field_name: str) -> float:
        numeric_value = float(value)
        if not 0.0 <= numeric_value <= 1.0:
            raise ValueError(f"{field_name} must be between 0.0 and 1.0")
        return numeric_value


__all__ = ["GreyModuleBase"]
