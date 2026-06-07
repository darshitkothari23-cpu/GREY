"""
End-of-day reporting module for GREY.

The report builder turns tracker and aggregator outputs into concise,
operator-friendly summaries for dashboards or markdown export.
"""

from __future__ import annotations

from typing import Any, Mapping


class GreyDailyReport:
    """Build readable end-of-day GREY reports from evaluation outputs."""

    def build_report(
        self,
        day_summary: dict,
        tracker_output: dict,
        aggregate_snapshots: list | None = None,
    ) -> dict:
        """Return a concise report dictionary for dashboard/report use."""
        summary = day_summary or tracker_output.get("daily_summary", {}) or {}
        tracker = tracker_output or {}
        snapshots = aggregate_snapshots or []
        return {
            "headline_summary": self._headline_summary(summary, tracker, snapshots),
            "market_day_type": self._market_day_type(summary, tracker, snapshots),
            "key_time_blocks": self._key_time_blocks(tracker),
            "best_early_warnings": self._best_early_warnings(tracker),
            "false_confidence_events": self._false_confidence_events(tracker),
            "best_modules": self._best_modules(tracker),
            "worst_modules": self._worst_modules(tracker),
            "report_notes": self._report_notes(summary, tracker, snapshots),
        }

    def _headline_summary(
        self,
        day_summary: Mapping[str, Any],
        tracker_output: Mapping[str, Any],
        aggregate_snapshots: list,
    ) -> str:
        direction = day_summary.get("realized_direction", "UNKNOWN")
        move_pct = day_summary.get("realized_move_pct")
        false_count = day_summary.get(
            "false_confidence_count",
            len(tracker_output.get("false_confidence_flags", [])),
        )
        late_count = day_summary.get(
            "late_signal_count",
            len(tracker_output.get("late_signal_flags", [])),
        )
        best_module = self._module_name(day_summary.get("best_module"))

        move_text = "unknown move size" if move_pct is None else f"{round(move_pct * 100, 2)}% move"
        if best_module:
            helper_text = f"{best_module} was the most useful module by score"
        else:
            helper_text = "no single module stood out"

        return (
            f"Market finished {direction} with {move_text}. "
            f"{helper_text}. "
            f"False-confidence events: {false_count}; late confirmations: {late_count}."
        )

    def _market_day_type(
        self,
        day_summary: Mapping[str, Any],
        tracker_output: Mapping[str, Any],
        aggregate_snapshots: list,
    ) -> str:
        false_count = day_summary.get(
            "false_confidence_count",
            len(tracker_output.get("false_confidence_flags", [])),
        )
        late_count = day_summary.get(
            "late_signal_count",
            len(tracker_output.get("late_signal_flags", [])),
        )
        direction = day_summary.get("realized_direction", "NEUTRAL")
        conflict_count = sum(
            str(snapshot.get("conflict_state", "")) in ("MEDIUM_CONFLICT", "HIGH_CONFLICT")
            for snapshot in aggregate_snapshots
            if isinstance(snapshot, Mapping)
        )
        caution_count = sum(
            str(snapshot.get("caution_state", {}).get("level", "")) in ("CAUTION", "HIGH_CAUTION", "FREEZE")
            for snapshot in aggregate_snapshots
            if isinstance(snapshot, Mapping)
        )

        if false_count:
            return "FALSE_CONFIDENCE_DAY"
        if conflict_count:
            return "CONTESTED_SIGNAL_DAY"
        if late_count:
            return "LATE_CONFIRMATION_DAY"
        if caution_count:
            return "CAUTION_HEAVY_DAY"
        if direction in ("BULL", "BEAR"):
            return f"{direction}_DIRECTIONAL_DAY"
        return "MIXED_OR_QUIET_DAY"

    def _key_time_blocks(self, tracker_output: Mapping[str, Any]) -> list[dict]:
        blocks = []
        for phase, analysis in tracker_output.get("time_block_analysis", {}).items():
            if not isinstance(analysis, Mapping):
                continue
            blocks.append({
                "session_state": phase,
                "summary": self._phase_summary(phase, analysis),
                "average_score": round(float(analysis.get("average_score", 0.0)), 3),
                "early_count": int(analysis.get("early_count", 0)),
                "late_count": int(analysis.get("late_count", 0)),
                "wrong_count": int(analysis.get("wrong_count", 0)),
            })
        blocks.sort(
            key=lambda item: (
                item["early_count"],
                -item["wrong_count"],
                item["average_score"],
            ),
            reverse=True,
        )
        return blocks

    def _best_early_warnings(self, tracker_output: Mapping[str, Any]) -> list[dict]:
        warnings = []
        for module_id, data in tracker_output.get("module_earliness", {}).items():
            if not isinstance(data, Mapping):
                continue
            early_count = int(data.get("early_count", 0))
            if early_count <= 0:
                continue
            warnings.append({
                "module_id": module_id,
                "early_count": early_count,
                "average_minutes_before_move": round(
                    float(data.get("average_minutes_before_move", 0.0)),
                    1,
                ),
                "summary": (
                    f"{module_id} gave {early_count} early warning(s), "
                    f"averaging {round(float(data.get('average_minutes_before_move', 0.0)), 1)} minutes before the move."
                ),
            })
        warnings.sort(
            key=lambda item: (item["early_count"], item["average_minutes_before_move"]),
            reverse=True,
        )
        return warnings

    def _false_confidence_events(self, tracker_output: Mapping[str, Any]) -> list[dict]:
        events = []
        for event in tracker_output.get("false_confidence_flags", []):
            if not isinstance(event, Mapping):
                continue
            events.append({
                "module_id": event.get("module_id", "UNKNOWN"),
                "dt": event.get("dt"),
                "session_state": event.get("session_state", "UNKNOWN"),
                "confidence": event.get("confidence", 0.0),
                "summary": (
                    f"{event.get('module_id', 'UNKNOWN')} had high confidence in "
                    f"{event.get('module_direction', 'UNKNOWN')} while the realized move was "
                    f"{event.get('realized_direction', 'UNKNOWN')}."
                ),
            })
        return events

    def _best_modules(self, tracker_output: Mapping[str, Any]) -> list[dict]:
        modules = []
        for module_id, data in tracker_output.get("module_accuracy", {}).items():
            if not isinstance(data, Mapping):
                continue
            if float(data.get("average_score", 0.0)) <= 0:
                continue
            modules.append(self._module_report_row(module_id, data))
        modules.sort(key=lambda item: item["average_score"], reverse=True)
        return modules

    def _worst_modules(self, tracker_output: Mapping[str, Any]) -> list[dict]:
        modules = []
        for module_id, data in tracker_output.get("module_accuracy", {}).items():
            if not isinstance(data, Mapping):
                continue
            if float(data.get("average_score", 0.0)) >= 0:
                continue
            modules.append(self._module_report_row(module_id, data))
        modules.sort(key=lambda item: item["average_score"])
        return modules

    def _report_notes(
        self,
        day_summary: Mapping[str, Any],
        tracker_output: Mapping[str, Any],
        aggregate_snapshots: list,
    ) -> list[str]:
        notes = [
            "This report separates early warnings from late confirmations.",
            "Module usefulness is based on recorded timing versus later realized movement, not hindsight narration.",
        ]
        if tracker_output.get("false_confidence_flags"):
            notes.append("False-confidence events should be reviewed before increasing module weight.")
        if tracker_output.get("late_signal_flags"):
            notes.append("Late confirmations were counted separately and should not be treated as early calls.")
        if not aggregate_snapshots:
            notes.append("No aggregate snapshots were supplied; market-day type used tracker data only.")
        if not day_summary:
            notes.append("Day summary was missing or empty; report used tracker fallbacks where possible.")
        return notes

    @staticmethod
    def _phase_summary(phase: str, analysis: Mapping[str, Any]) -> str:
        early = int(analysis.get("early_count", 0))
        late = int(analysis.get("late_count", 0))
        wrong = int(analysis.get("wrong_count", 0))
        if early:
            return f"{phase} provided {early} early warning(s)."
        if wrong:
            return f"{phase} had {wrong} wrong signal(s)."
        if late:
            return f"{phase} mostly confirmed late."
        return f"{phase} was mixed or low-signal."

    @staticmethod
    def _module_report_row(module_id: str, data: Mapping[str, Any]) -> dict:
        average_score = round(float(data.get("average_score", 0.0)), 3)
        correct_count = int(data.get("correct_count", 0))
        wrong_count = int(data.get("wrong_count", 0))
        return {
            "module_id": module_id,
            "average_score": average_score,
            "correct_count": correct_count,
            "wrong_count": wrong_count,
            "confidence_quality": data.get("confidence_quality", "UNKNOWN"),
            "summary": (
                f"{module_id}: score {average_score}, "
                f"{correct_count} useful signal(s), {wrong_count} wrong signal(s)."
            ),
        }

    @staticmethod
    def _module_name(value: Any) -> str | None:
        if isinstance(value, Mapping):
            return value.get("module_id")
        return None


__all__ = ["GreyDailyReport"]
