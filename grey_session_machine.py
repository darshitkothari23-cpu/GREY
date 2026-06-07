"""
Session state machine for GREY market intelligence.

All absolute market timings are sourced from grey_config.GREY_SESSION_TIMINGS.
"""

from datetime import date, datetime, time, timedelta
from typing import Dict

import grey_config


class GreySessionMachine:
    """Resolve GREY session state and module weights for the current moment."""

    PRE_OPEN = "PRE_OPEN"
    OPENING_DRIVE = "OPENING_DRIVE"
    EARLY_TREND = "EARLY_TREND"
    MIDDAY = "MIDDAY"
    PRE_EVENT = "PRE_EVENT"
    EXPIRY_SENSITIVE = "EXPIRY_SENSITIVE"
    CLOSING_DRIVE = "CLOSING_DRIVE"
    POST_CLOSE = "POST_CLOSE"
    MARKET_CLOSED = "MARKET_CLOSED"

    SESSION_STATES = (
        PRE_OPEN,
        OPENING_DRIVE,
        EARLY_TREND,
        MIDDAY,
        PRE_EVENT,
        CLOSING_DRIVE,
        POST_CLOSE,
        MARKET_CLOSED,
    )

    SESSION_MODIFIERS = (
        EXPIRY_SENSITIVE,
    )

    BASE_SESSION_STATES = (
        PRE_OPEN,
        OPENING_DRIVE,
        EARLY_TREND,
        MIDDAY,
        PRE_EVENT,
        CLOSING_DRIVE,
        POST_CLOSE,
        MARKET_CLOSED,
    )

    EXPIRY_FLAG_SEPARATOR = "|"

    def __init__(
        self,
        timings: dict | None = None,
        *,
        opening_drive_minutes: int = 30,
        early_trend_minutes: int = 105,
        closing_drive_minutes: int = 45,
        post_close_minutes: int = 30,
        pre_event_window_minutes: int = 30,
    ) -> None:
        self.timings = timings or grey_config.GREY_SESSION_TIMINGS
        self.opening_drive = timedelta(minutes=opening_drive_minutes)
        self.early_trend = timedelta(minutes=early_trend_minutes)
        self.closing_drive = timedelta(minutes=closing_drive_minutes)
        self.post_close = timedelta(minutes=post_close_minutes)
        self.pre_event_window_minutes = pre_event_window_minutes

    def get_current_state(
        self,
        dt: datetime,
        is_expiry: bool,
        event_minutes_away: int | None,
    ) -> str:
        """Return the base session state for the supplied datetime."""
        return self._get_base_state(dt, event_minutes_away)

    def is_expiry_sensitive(self, dt: datetime, is_expiry: bool) -> bool:
        """Return whether expiry sensitivity should modify the base state."""
        if not is_expiry:
            return False

        base_state = self._get_base_state(dt, event_minutes_away=None)
        return base_state not in (self.MARKET_CLOSED, self.POST_CLOSE)

    def get_session_weights(self, state: str, active_modules: list) -> dict:
        """Return module weights adjusted for the supplied session state."""
        base_state, expiry_sensitive = self._split_expiry_flag(state)
        if base_state not in self.BASE_SESSION_STATES:
            raise ValueError(f"unknown session state: {state}")

        weights = {module_id: 1.0 for module_id in active_modules}

        for module_id, multiplier in self._state_multipliers(base_state).items():
            if module_id in weights:
                weights[module_id] *= multiplier

        if expiry_sensitive:
            for module_id, multiplier in self._expiry_multipliers().items():
                if module_id in weights:
                    weights[module_id] *= multiplier

        return weights

    def _get_base_state(
        self,
        dt: datetime,
        event_minutes_away: int | None,
    ) -> str:
        if self._calendar_event_is_active(event_minutes_away):
            return self.PRE_EVENT

        pre_open_start = self._combine(dt.date(), self._configured_time("PRE_OPEN_START"))
        market_open = self._combine(dt.date(), self._configured_time("MARKET_OPEN"))
        close_time_key = self._close_time_key(dt.date())
        derivatives_close = self._combine(dt.date(), self._configured_time(close_time_key))
        opening_drive_end = market_open + self.opening_drive
        early_trend_end = market_open + self.early_trend
        closing_drive_start = derivatives_close - self.closing_drive
        post_close_end = derivatives_close + self.post_close

        if pre_open_start <= dt < market_open:
            return self.PRE_OPEN
        if market_open <= dt < opening_drive_end:
            return self.OPENING_DRIVE
        if opening_drive_end <= dt < early_trend_end:
            return self.EARLY_TREND
        if closing_drive_start <= dt < derivatives_close:
            return self.CLOSING_DRIVE
        if early_trend_end <= dt < closing_drive_start:
            return self.MIDDAY
        if derivatives_close <= dt < post_close_end:
            return self.POST_CLOSE
        return self.MARKET_CLOSED

    def _close_time_key(self, current_date: date) -> str:
        extension_date = date.fromisoformat(self._timing_value("NSE_EXTENSION_DATE"))
        if current_date >= extension_date:
            return "DERIVATIVES_CLOSE_EXTENDED"
        return "DERIVATIVES_CLOSE"

    def _configured_time(self, key: str) -> time:
        return time.fromisoformat(self._timing_value(key))

    def _timing_value(self, key: str) -> str:
        if hasattr(grey_config, key):
            return getattr(grey_config, key)
        return self.timings[key]

    @staticmethod
    def _combine(current_date: date, current_time: time) -> datetime:
        return datetime.combine(current_date, current_time)

    def _calendar_event_is_active(self, event_minutes_away: int | None) -> bool:
        if event_minutes_away is None:
            return False
        return 0 <= event_minutes_away <= self.pre_event_window_minutes

    def _with_expiry_flag(self, base_state: str) -> str:
        return (
            f"{base_state}{self.EXPIRY_FLAG_SEPARATOR}{self.EXPIRY_SENSITIVE}"
        )

    def _split_expiry_flag(self, state: str) -> tuple[str, bool]:
        parts = state.split(self.EXPIRY_FLAG_SEPARATOR)
        if len(parts) == 1:
            return state, False
        if len(parts) == 2 and parts[1] == self.EXPIRY_SENSITIVE:
            return parts[0], True
        raise ValueError(f"invalid session state flag format: {state}")

    def _state_multipliers(self, state: str) -> Dict[str, float]:
        multipliers = {
            self.PRE_OPEN: {
                "OVERNIGHT": 1.25,
                "CALENDAR": 1.20,
                "VOLUME": 0.80,
            },
            self.OPENING_DRIVE: {
                "REGIME": 1.20,
                "VOLUME": 1.25,
                "VOLATILITY": 1.15,
            },
            self.EARLY_TREND: {
                "REGIME": 1.25,
                "OPTIONS": 1.10,
            },
            self.MIDDAY: {
                "LIQUIDITY": 1.15,
                "VOLUME": 0.90,
            },
            self.PRE_EVENT: {
                "CALENDAR": 1.50,
                "VOLATILITY": 1.25,
                "REGIME": 0.85,
            },
            self.CLOSING_DRIVE: {
                "VOLUME": 1.30,
                "OPTIONS": 1.20,
                "VOLATILITY": 1.15,
            },
            self.POST_CLOSE: {
                "OVERNIGHT": 1.20,
                "REGIME": 0.80,
            },
            self.MARKET_CLOSED: {
                "OVERNIGHT": 1.30,
                "CALENDAR": 1.15,
                "VOLUME": 0.50,
                "LIQUIDITY": 0.50,
            },
        }
        return multipliers.get(state, {})

    @staticmethod
    def _expiry_multipliers() -> Dict[str, float]:
        return {
            "OPTIONS": 1.40,
            "VOLATILITY": 1.25,
            "LIQUIDITY": 1.15,
        }


__all__ = ["GreySessionMachine"]
