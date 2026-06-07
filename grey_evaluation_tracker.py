"""
Intraday evaluation tracker for GREY.

The tracker evaluates module usefulness from replay or paper-tracking data.
It only produces offline evaluation summaries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

import grey_config


class GreyEvaluationTracker:
    """Track GREY module timing, usefulness, and confidence quality."""

    DEFAULT_CONFIG = {
        "move_threshold": 0.004,
        "early_warning_minutes": 30,
        "late_confirmation_minutes": 5,
        "high_confidence_threshold": 0.70,
        "correct_score": 1.0,
        "early_bonus": 0.50,
        "late_penalty": -0.35,
        "wrong_penalty": -1.0,
        "neutral_penalty": -0.10,
        "session_phases": (
            "PRE_EVENT",
            "OPENING_DRIVE",
            "EARLY_TREND",
            "MIDDAY",
            "CLOSING_DRIVE",
        ),
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        configured = getattr(grey_config, "GREY_EVALUATION_TRACKER", {})
        self.config = self._deep_merge(
            self.DEFAULT_CONFIG,
            configured if isinstance(configured, Mapping) else {},
        )
        if config is not None:
            self.config = self._deep_merge(self.config, config)
        self.snapshots: list[dict] = []

    def record_snapshot(
        self,
        dt,
        market_snapshot: dict,
        module_outputs: dict,
        composite_view: dict,
    ) -> None:
        """Record one intraday GREY observation for later evaluation."""
        normalized_dt = self._parse_dt(dt)
        self.snapshots.append({
            "dt": normalized_dt,
            "market_snapshot": dict(market_snapshot or {}),
            "module_outputs": dict(module_outputs or {}),
            "composite_view": dict(composite_view or {}),
            "session_state": self._session_state(
                market_snapshot or {},
                composite_view or {},
                module_outputs or {},
            ),
        })
        self.snapshots.sort(key=lambda snapshot: snapshot["dt"])

    def finalize_day(self, day_data: dict) -> dict:
        """Return dashboard-friendly daily evaluation outputs."""
        snapshots = list(day_data.get("snapshots", self.snapshots))
        realized_outcomes = day_data.get("realized_outcomes", {})
        timing = self.score_prediction_timing(snapshots, realized_outcomes)
        return {
            "daily_summary": self._daily_summary(snapshots, realized_outcomes, timing),
            "time_block_analysis": timing["time_block_analysis"],
            "module_accuracy": timing["module_accuracy"],
            "module_earliness": timing["module_earliness"],
            "false_confidence_flags": timing["false_confidence_flags"],
            "late_signal_flags": timing["late_signal_flags"],
            "best_module_by_phase": timing["best_module_by_phase"],
            "worst_module_by_phase": timing["worst_module_by_phase"],
        }

    def score_prediction_timing(
        self,
        snapshots: list,
        realized_outcomes: dict,
    ) -> dict:
        """Score whether module signals were early, useful, late, or wrong."""
        normalized_snapshots = sorted(
            (self._normalize_snapshot(snapshot) for snapshot in snapshots),
            key=lambda snapshot: snapshot["dt"],
        )
        move_direction = self._realized_direction(realized_outcomes)
        move_start = self._move_start_dt(realized_outcomes, normalized_snapshots)
        module_scores: dict[str, list[dict]] = {}
        phase_scores: dict[str, dict[str, list[dict]]] = {}
        false_confidence_flags = []
        late_signal_flags = []

        for snapshot in normalized_snapshots:
            phase = snapshot["session_state"]
            minutes_before_move = self._minutes_before(snapshot["dt"], move_start)
            for module_id, output in snapshot["module_outputs"].items():
                module_direction = self._module_direction(output)
                confidence = self._module_confidence(output)
                grade = self._timing_grade(
                    module_direction=module_direction,
                    move_direction=move_direction,
                    minutes_before_move=minutes_before_move,
                )
                score = self._grade_score(grade)
                record = {
                    "dt": snapshot["dt"].isoformat(),
                    "session_state": phase,
                    "module_direction": module_direction,
                    "confidence": confidence,
                    "timing_grade": grade,
                    "score": score,
                    "minutes_before_move": minutes_before_move,
                }
                module_scores.setdefault(module_id, []).append(record)
                phase_scores.setdefault(phase, {}).setdefault(module_id, []).append(record)

                if grade == "WRONG" and confidence >= self.config["high_confidence_threshold"]:
                    false_confidence_flags.append({
                        "module_id": module_id,
                        "dt": snapshot["dt"].isoformat(),
                        "session_state": phase,
                        "confidence": confidence,
                        "module_direction": module_direction,
                        "realized_direction": move_direction,
                    })
                if grade == "LATE":
                    late_signal_flags.append({
                        "module_id": module_id,
                        "dt": snapshot["dt"].isoformat(),
                        "session_state": phase,
                        "minutes_before_move": minutes_before_move,
                    })

        return {
            "time_block_analysis": self._time_block_analysis(phase_scores),
            "module_accuracy": self._module_accuracy(module_scores),
            "module_earliness": self._module_earliness(module_scores),
            "false_confidence_flags": false_confidence_flags,
            "late_signal_flags": late_signal_flags,
            "best_module_by_phase": self._module_by_phase(phase_scores, best=True),
            "worst_module_by_phase": self._module_by_phase(phase_scores, best=False),
        }

    def _daily_summary(
        self,
        snapshots: list[dict],
        realized_outcomes: dict,
        timing: dict,
    ) -> dict:
        module_accuracy = timing["module_accuracy"]
        best_module = self._ranked_module(module_accuracy, best=True)
        worst_module = self._ranked_module(module_accuracy, best=False)
        return {
            "snapshot_count": len(snapshots),
            "realized_direction": self._realized_direction(realized_outcomes),
            "realized_move_pct": self._to_float(realized_outcomes.get("move_pct")),
            "best_module": best_module,
            "worst_module": worst_module,
            "false_confidence_count": len(timing["false_confidence_flags"]),
            "late_signal_count": len(timing["late_signal_flags"]),
        }

    def _time_block_analysis(self, phase_scores: dict) -> dict:
        analysis = {}
        for phase, modules in phase_scores.items():
            records = [
                record for module_records in modules.values()
                for record in module_records
            ]
            analysis[phase] = {
                "snapshot_signal_count": len(records),
                "average_score": self._average(record["score"] for record in records),
                "early_count": sum(record["timing_grade"] == "EARLY" for record in records),
                "late_count": sum(record["timing_grade"] == "LATE" for record in records),
                "wrong_count": sum(record["timing_grade"] == "WRONG" for record in records),
            }
        return analysis

    def _module_accuracy(self, module_scores: dict) -> dict:
        accuracy = {}
        for module_id, records in module_scores.items():
            directional_records = [
                record for record in records
                if record["timing_grade"] != "NEUTRAL"
            ]
            correct_records = [
                record for record in records
                if record["timing_grade"] in ("EARLY", "USEFUL", "LATE")
            ]
            accuracy[module_id] = {
                "average_score": self._average(record["score"] for record in records),
                "correct_count": len(correct_records),
                "wrong_count": sum(record["timing_grade"] == "WRONG" for record in records),
                "evaluated_count": len(directional_records),
                "confidence_quality": self._confidence_quality(records),
            }
        return accuracy

    def _module_earliness(self, module_scores: dict) -> dict:
        earliness = {}
        for module_id, records in module_scores.items():
            early_records = [
                record for record in records
                if record["timing_grade"] == "EARLY"
            ]
            earliness[module_id] = {
                "early_count": len(early_records),
                "average_minutes_before_move": self._average(
                    record["minutes_before_move"] for record in early_records
                    if record["minutes_before_move"] is not None
                ),
            }
        return earliness

    def _module_by_phase(self, phase_scores: dict, *, best: bool) -> dict:
        result = {}
        for phase, modules in phase_scores.items():
            phase_module_scores = {
                module_id: self._average(record["score"] for record in records)
                for module_id, records in modules.items()
            }
            result[phase] = self._ranked_module(phase_module_scores, best=best)
        return result

    def _confidence_quality(self, records: list[dict]) -> str:
        high_confidence_wrong = any(
            record["timing_grade"] == "WRONG"
            and record["confidence"] >= self.config["high_confidence_threshold"]
            for record in records
        )
        if high_confidence_wrong:
            return "OVERCONFIDENT_WRONG"
        if any(record["timing_grade"] == "EARLY" for record in records):
            return "EARLY_USEFUL"
        if any(record["timing_grade"] == "LATE" for record in records):
            return "LATE_CONFIRMATION"
        return "MIXED_OR_INSUFFICIENT"

    def _timing_grade(
        self,
        *,
        module_direction: str,
        move_direction: str,
        minutes_before_move: int | None,
    ) -> str:
        if move_direction == "NEUTRAL" or module_direction == "NEUTRAL":
            return "NEUTRAL"
        if module_direction != move_direction:
            return "WRONG"
        if minutes_before_move is None:
            return "USEFUL"
        if minutes_before_move >= self.config["early_warning_minutes"]:
            return "EARLY"
        if minutes_before_move >= self.config["late_confirmation_minutes"]:
            return "USEFUL"
        return "LATE"

    def _grade_score(self, grade: str) -> float:
        if grade == "EARLY":
            return self.config["correct_score"] + self.config["early_bonus"]
        if grade == "USEFUL":
            return self.config["correct_score"]
        if grade == "LATE":
            return self.config["correct_score"] + self.config["late_penalty"]
        if grade == "WRONG":
            return self.config["wrong_penalty"]
        return self.config["neutral_penalty"]

    def _normalize_snapshot(self, snapshot: dict) -> dict:
        return {
            "dt": self._parse_dt(snapshot["dt"]),
            "market_snapshot": dict(snapshot.get("market_snapshot", {})),
            "module_outputs": dict(snapshot.get("module_outputs", {})),
            "composite_view": dict(snapshot.get("composite_view", {})),
            "session_state": snapshot.get("session_state")
            or self._session_state(
                snapshot.get("market_snapshot", {}),
                snapshot.get("composite_view", {}),
                snapshot.get("module_outputs", {}),
            ),
        }

    def _module_direction(self, output: Mapping[str, Any]) -> str:
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

    def _direction_from_value(self, value: Any) -> str:
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
        return GreyEvaluationTracker._clamp_unit(GreyEvaluationTracker._to_float(value) or 0.0)

    def _session_state(
        self,
        market_snapshot: Mapping[str, Any],
        composite_view: Mapping[str, Any],
        module_outputs: Mapping[str, Any],
    ) -> str:
        if composite_view.get("session_state"):
            return str(composite_view["session_state"]).split("|", 1)[0]
        if market_snapshot.get("session_state"):
            return str(market_snapshot["session_state"]).split("|", 1)[0]
        for output in module_outputs.values():
            if isinstance(output, Mapping) and output.get("session_state"):
                return str(output["session_state"]).split("|", 1)[0]
        return "UNKNOWN"

    def _realized_direction(self, realized_outcomes: Mapping[str, Any]) -> str:
        direction = str(realized_outcomes.get("direction", "")).upper()
        if direction in ("BULL", "BEAR", "NEUTRAL"):
            return direction

        move_pct = self._to_float(realized_outcomes.get("move_pct"))
        if move_pct is None:
            return "NEUTRAL"
        if move_pct >= self.config["move_threshold"]:
            return "BULL"
        if move_pct <= -self.config["move_threshold"]:
            return "BEAR"
        return "NEUTRAL"

    def _move_start_dt(
        self,
        realized_outcomes: Mapping[str, Any],
        snapshots: list[dict],
    ) -> datetime | None:
        if realized_outcomes.get("move_start_dt"):
            return self._parse_dt(realized_outcomes["move_start_dt"])
        if snapshots:
            return snapshots[-1]["dt"]
        return None

    @staticmethod
    def _minutes_before(snapshot_dt: datetime, move_start: datetime | None) -> int | None:
        if move_start is None:
            return None
        return int((move_start - snapshot_dt).total_seconds() / 60)

    @staticmethod
    def _parse_dt(value) -> datetime:
        if isinstance(value, datetime):
            return GreyEvaluationTracker._as_naive_dt(value)
        text_value = str(value)
        if text_value.endswith("Z"):
            text_value = f"{text_value[:-1]}+00:00"
        return GreyEvaluationTracker._as_naive_dt(datetime.fromisoformat(text_value))

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
    def _average(values) -> float:
        materialized = list(values)
        if not materialized:
            return 0.0
        return sum(materialized) / len(materialized)

    @staticmethod
    def _ranked_module(scores: dict, *, best: bool):
        if not scores:
            return None
        if all(isinstance(value, Mapping) for value in scores.values()):
            key = lambda item: item[1].get("average_score", 0.0)
        else:
            key = lambda item: item[1]
        module_id, score = sorted(scores.items(), key=key, reverse=best)[0]
        return {"module_id": module_id, "score": score}

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


__all__ = ["GreyEvaluationTracker"]
