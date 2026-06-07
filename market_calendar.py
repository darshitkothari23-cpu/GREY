"""
Lightweight market event calendar helper for GREY.

This module only exposes scheduled event lookup helpers. It performs no
network calls and does not contain market-session state logic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import grey_config


class MarketCalendar:
    """Deterministic local event calendar for GREY PRE_EVENT checks."""

    DEFAULT_EVENT_DATA_FILE = Path(__file__).resolve().parent / "data" / "grey_event_calendar.json"
    DEFAULT_PRE_EVENT_LOOKAHEAD_MINUTES = 30

    def __init__(
        self,
        events: Iterable[dict] | None = None,
        event_data_file: str | Path | None = None,
    ) -> None:
        self.event_data_file = Path(event_data_file or self._config_value(
            "GREY_EVENT_CALENDAR_PATH",
            self.DEFAULT_EVENT_DATA_FILE,
        ))
        self._configured_events = list(events) if events is not None else None

    def get_next_event_minutes(self, dt: datetime) -> int | None:
        """Return minutes until the next configured event, or None."""
        current_dt = self._normalize_dt(dt)
        upcoming_minutes = []

        for event in self.get_todays_events(current_dt):
            event_dt = self._event_datetime(event, current_dt)
            if event_dt is None:
                continue

            minutes_away = int((event_dt - current_dt).total_seconds() / 60)
            if minutes_away >= 0:
                upcoming_minutes.append(minutes_away)

        if not upcoming_minutes:
            return None
        return min(upcoming_minutes)

    def has_pre_event(self, dt: datetime, lookahead_minutes: int) -> bool:
        """Return True when an event falls within the lookahead window."""
        next_event_minutes = self.get_next_event_minutes(dt)
        if next_event_minutes is None:
            return False
        return 0 <= next_event_minutes <= lookahead_minutes

    def get_todays_events(self, dt: datetime) -> list:
        """Return configured events scheduled for dt's calendar date."""
        current_dt = self._normalize_dt(dt)
        todays_events = []

        for event in self._load_events():
            event_dt = self._event_datetime(event, current_dt)
            if event_dt is None:
                continue
            if event_dt.date() == current_dt.date():
                todays_events.append(self._normalize_event(event, event_dt))

        return todays_events

    def default_pre_event_lookahead_minutes(self) -> int:
        """Return configured pre-event lookahead minutes for session integration."""
        return int(self._config_value(
            "GREY_PRE_EVENT_LOOKAHEAD_MINUTES",
            self.DEFAULT_PRE_EVENT_LOOKAHEAD_MINUTES,
        ))

    def _load_events(self) -> list[dict]:
        if self._configured_events is not None:
            return [event for event in self._configured_events if isinstance(event, dict)]

        if not self.event_data_file.exists():
            return []

        with self.event_data_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        events = payload.get("events", [])
        if not isinstance(events, list):
            return []
        return [event for event in events if isinstance(event, dict)]

    def _event_datetime(self, event: dict, reference_dt: datetime) -> datetime | None:
        value = event.get("event_time", event.get("scheduled_at"))
        if not value:
            return None

        parsed = self._parse_event_datetime(value, reference_dt)
        if parsed is None:
            return None
        return self._normalize_dt(parsed)

    def _parse_event_datetime(
        self,
        value: Any,
        reference_dt: datetime,
    ) -> datetime | None:
        try:
            text_value = str(value)
            if "T" in text_value or "+" in text_value or text_value.endswith("Z"):
                return datetime.fromisoformat(text_value.replace("Z", "+00:00"))

            parsed_time = datetime.strptime(text_value, "%H:%M").time()
            return datetime.combine(reference_dt.date(), parsed_time)
        except (TypeError, ValueError):
            return None

    def _normalize_event(self, event: dict, event_dt: datetime) -> dict:
        return {
            "name": event.get("name", ""),
            "event_time": event_dt.isoformat(),
            "category": event.get("category", event.get("region", "")),
            "priority": event.get("priority", event.get("impact", "")),
        }

    @staticmethod
    def _normalize_dt(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _config_value(name: str, default: Any) -> Any:
        return getattr(grey_config, name, default)


__all__ = ["MarketCalendar"]
