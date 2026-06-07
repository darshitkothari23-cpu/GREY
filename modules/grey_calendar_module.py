"""
GREY calendar risk-gate module.

The module gates confidence around known events. It does not predict the
direction of unannounced events.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from modules.grey_module_base import GreyModuleBase


class GreyCalendarModule(GreyModuleBase):
    """Risk-gate signal for scheduled market events."""

    MODULE_ID = "CALENDAR"
    SIGNAL_TYPE = "RISK_GATE"
    STALE_AFTER_SECONDS = 3600
    EVENT_IMPACTS = frozenset(("HIGH", "MEDIUM", "LOW"))
    DEFAULT_EVENT_DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "grey_event_calendar.json"

    def __init__(
        self,
        event_data_file: str | Path | None = None,
        *,
        now: datetime | None = None,
        explicit_surprise: str | None = None,
        source_quality_weight: float = 1.0,
    ) -> None:
        super().__init__(
            module_id=self.MODULE_ID,
            stale_after_seconds=self.STALE_AFTER_SECONDS,
            source_quality_weight=source_quality_weight,
        )
        self.event_data_file = Path(event_data_file or self.DEFAULT_EVENT_DATA_FILE)
        self.now = now
        self.explicit_surprise = explicit_surprise

    def compute(self) -> dict:
        now = self._current_time()
        events = self._load_events()
        nearest_event = self._nearest_event(now, events)

        if nearest_event is None:
            return self._output(
                score=0.0,
                raw_inputs={
                    "event_count": len(events),
                    "matched_event": None,
                    "freeze_contribution": False,
                },
                top_driver="no_event_2h",
            )

        event, minutes_away = nearest_event
        impact = self._normalize_impact(event.get("impact"))
        surprise = self._normalize_surprise(self.explicit_surprise)
        score = 0.0
        freeze_contribution = False
        top_driver = "no_event_2h"

        if minutes_away < 0 and surprise is not None:
            score = 4.0 if surprise == "POSITIVE" else -4.0
            top_driver = f"post_release_{surprise.lower()}_surprise"
        elif minutes_away >= 0:
            if impact == "HIGH" and minutes_away <= 15:
                score = 0.0
                freeze_contribution = True
                top_driver = "high_impact_within_15m"
            elif impact == "HIGH" and minutes_away <= 60:
                score = -5.0
                top_driver = "high_impact_within_60m"
            elif impact == "MEDIUM" and minutes_away <= 30:
                score = -2.0
                top_driver = "medium_impact_within_30m"

        return self._output(
            score=score,
            raw_inputs={
                "event_count": len(events),
                "matched_event": event,
                "minutes_away": minutes_away,
                "impact": impact,
                "explicit_surprise": surprise,
                "freeze_contribution": freeze_contribution,
            },
            top_driver=top_driver,
        )

    def _output(
        self,
        *,
        score: float,
        raw_inputs: Mapping[str, Any],
        top_driver: str,
    ) -> dict:
        return self.build_output(
            score=score,
            direction="NEUTRAL",
            signal_type=self.SIGNAL_TYPE,
            elapsed_seconds=0,
            raw_inputs=raw_inputs,
            top_driver=top_driver,
        )

    def _load_events(self) -> list[dict]:
        if not self.event_data_file.exists():
            return []

        with self.event_data_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        events = payload.get("events", [])
        if not isinstance(events, list):
            raise ValueError("grey event calendar must contain an events list")
        return [event for event in events if isinstance(event, dict)]

    def _nearest_event(
        self,
        now: datetime,
        events: list[dict],
    ) -> tuple[dict, int] | None:
        candidates: list[tuple[dict, int]] = []
        for event in events:
            scheduled_at = self._parse_scheduled_at(event.get("scheduled_at"))
            if scheduled_at is None:
                continue

            minutes_away = int((scheduled_at - now).total_seconds() / 60)
            if -120 <= minutes_away <= 120:
                candidates.append((event, minutes_away))

        if not candidates:
            return None
        return min(candidates, key=lambda candidate: abs(candidate[1]))

    def _current_time(self) -> datetime:
        current = self.now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current

    @staticmethod
    def _parse_scheduled_at(value: Any) -> datetime | None:
        if not value:
            return None

        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _normalize_impact(self, value: Any) -> str:
        impact = str(value or "LOW").upper()
        if impact not in self.EVENT_IMPACTS:
            raise ValueError(f"invalid event impact: {value}")
        return impact

    @staticmethod
    def _normalize_surprise(value: str | None) -> str | None:
        if value is None:
            return None

        surprise = value.upper()
        if surprise not in ("POSITIVE", "NEGATIVE"):
            raise ValueError("explicit_surprise must be POSITIVE or NEGATIVE")
        return surprise


__all__ = ["GreyCalendarModule"]
