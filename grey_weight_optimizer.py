"""Learn GREY module weights from shadow-mode efficacy data.

This optimizer is intended for Week 5, after roughly 20 trading days of
shadow-mode reports and module scores have been collected.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


class LogisticWeightOptimizer:
    """Fit simple logistic weights for module correctness prediction."""

    def __init__(
        self,
        *,
        output_path: str | Path = "learned_module_weights.json",
        learning_rate: float = 0.05,
        iterations: int = 800,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize optimizer settings.

        Args:
            output_path: Where learned weights should be saved.
            learning_rate: Gradient descent step size.
            iterations: Number of gradient descent passes.
            logger: Optional logger for training diagnostics.
        """
        self.output_path = Path(output_path)
        self.learning_rate = float(learning_rate)
        self.iterations = int(iterations)
        self.logger = logger or logging.getLogger(__name__)

    def optimize(
        self,
        efficacy_reports: Sequence[Mapping[str, Any]],
        module_scores: Sequence[Mapping[str, Any]],
    ) -> dict:
        """Learn module weights and save them to learned_module_weights.json.

        Args:
            efficacy_reports: Daily or signal-level records containing
                was_correct, result, directional_outcome, or range_outcome.
            module_scores: Matching module-score dictionaries for each report.

        Returns:
            Dictionary containing learned weights and training metadata.
        """
        try:
            rows = self._training_rows(efficacy_reports, module_scores)
            if not rows:
                result = {"learned_weights": {}, "samples": 0, "status": "NO_DATA"}
                self._save(result)
                return result

            modules = sorted({module for _, scores in rows for module in scores})
            weights = {module: 0.0 for module in modules}
            bias = 0.0

            for _ in range(max(1, self.iterations)):
                grad = {module: 0.0 for module in modules}
                bias_grad = 0.0
                for label, scores in rows:
                    z = bias + sum(weights[module] * float(scores.get(module, 0.0)) for module in modules)
                    prediction = self._sigmoid(z)
                    error = prediction - label
                    bias_grad += error
                    for module in modules:
                        grad[module] += error * float(scores.get(module, 0.0))

                sample_count = float(len(rows))
                bias -= self.learning_rate * (bias_grad / sample_count)
                for module in modules:
                    weights[module] -= self.learning_rate * (grad[module] / sample_count)

            normalized = self._normalize_weights(weights)
            result = {
                "learned_weights": normalized,
                "raw_coefficients": {module: round(value, 6) for module, value in weights.items()},
                "bias": round(bias, 6),
                "samples": len(rows),
                "status": "OK",
            }
            self._save(result)
            self.logger.info("Learned module weights from %s samples: %s", len(rows), normalized)
            return result
        except Exception as exc:
            self.logger.warning("Weight optimization failed safely: %s", exc)
            result = {"learned_weights": {}, "samples": 0, "status": "ERROR", "error": str(exc)}
            self._save(result)
            return result

    def _training_rows(
        self,
        efficacy_reports: Sequence[Mapping[str, Any]],
        module_scores: Sequence[Mapping[str, Any]],
    ) -> list[tuple[float, dict[str, float]]]:
        """Build label and feature rows from reports and score dictionaries."""
        rows: list[tuple[float, dict[str, float]]] = []
        for report, scores in zip(efficacy_reports, module_scores):
            label = self._label_from_report(report)
            if label is None or not isinstance(scores, Mapping):
                continue
            parsed_scores = {
                str(module).upper(): self._score_to_float(score)
                for module, score in scores.items()
            }
            parsed_scores = {module: score for module, score in parsed_scores.items() if score is not None}
            if parsed_scores:
                rows.append((label, parsed_scores))
        return rows

    @staticmethod
    def _label_from_report(report: Mapping[str, Any]) -> float | None:
        """Extract a binary correctness label from an efficacy record."""
        if "was_correct" in report:
            return 1.0 if bool(report.get("was_correct")) else 0.0
        for key in ("range_outcome", "directional_outcome", "result"):
            value = str(report.get(key, "")).upper()
            if value in {"CORRECT", "CORRECT_RANGE", "ALIGNED"}:
                return 1.0
            if value in {"WRONG", "WRONG_RANGE"}:
                return 0.0
        return None

    @staticmethod
    def _score_to_float(value: Any) -> float | None:
        """Convert module score packets or raw scores into a float feature."""
        if isinstance(value, Mapping):
            for key in ("weighted_score", "score", "raw_score", "confidence"):
                if key in value:
                    return LogisticWeightOptimizer._score_to_float(value.get(key))
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sigmoid(value: float) -> float:
        """Return numerically stable sigmoid."""
        value = max(-50.0, min(50.0, value))
        return 1.0 / (1.0 + math.exp(-value))

    @staticmethod
    def _normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
        """Convert raw coefficients into positive aggregator-style weights."""
        positives = {module: max(0.0, value) for module, value in weights.items()}
        total = sum(positives.values())
        if total <= 0:
            return {module: 1.0 for module in weights}
        scale = len(positives) / total
        return {module: round(value * scale, 4) for module, value in positives.items()}

    def _save(self, result: Mapping[str, Any]) -> None:
        """Persist optimizer output safely."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


__all__ = ["LogisticWeightOptimizer"]
