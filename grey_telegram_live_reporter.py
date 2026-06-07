"""
Live Telegram reporter for GREY 5-minute module-score updates.

This reporter sends live context after each GREY signal generation. The
existing 15-minute evaluation Telegram message remains separate.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Mapping

import grey_config


class GreyTelegramLiveReporter:
    """Format and send real-time GREY module-score Telegram messages."""

    SEPARATOR = "━━━━━━━━━━━━━━━━━━━━━"

    def __init__(
        self,
        enabled: bool | None = None,
        bot_token: str | None = None,
        chat_id: str | None = None,
        prefix: str | None = None,
    ) -> None:
        # Live Telegram can be enabled independently from evaluation Telegram.
        self.enabled = (
            bool(getattr(grey_config, "GREY_TELEGRAM_LIVE_ENABLED", False))
            if enabled is None
            else bool(enabled)
        )

        # Reuse the same Telegram credentials by default.
        self.bot_token = bot_token or getattr(grey_config, "GREY_TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or getattr(grey_config, "GREY_TELEGRAM_CHAT_ID", "")

        # Prefix is kept configurable for future operator formatting changes.
        self.prefix = prefix if prefix is not None else ""

        # Store dry-run or sent messages for local testing.
        self.sent_messages: list[str] = []

    def send_live_signal(self, composite_signal: dict, market_data: dict) -> dict:
        """Format and send one live GREY module-score update."""
        try:
            message = self._format_message(composite_signal, market_data)
            return self._send(message)
        except Exception as exc:
            # Formatting failure should not crash GREY.
            fallback = self._fallback_message(exc, market_data)
            return self._send(fallback)

    def _format_message(self, composite: Mapping[str, Any], market_data: Mapping[str, Any]) -> str:
        """Build the requested live Telegram message."""
        try:
            # Read header values with graceful fallbacks.
            timestamp = self._format_time(market_data.get("timestamp"))
            symbol = str(market_data.get("symbol") or "NIFTY")
            price = self._format_price(market_data.get("price"))
            session_state = str(market_data.get("session_state") or "?")

            # Build module score lines and skip guard modules.
            module_vector = composite.get("module_vector", {})
            module_lines = self._format_module_lines(module_vector)

            # Read composite values.
            composite_score = self._display_score(composite.get("composite_score"))
            direction = str(composite.get("direction_bias") or "NEUTRAL").upper()
            confidence = self._clamp_unit(composite.get("confidence"))
            conflict = str(composite.get("conflict_state") or "UNKNOWN")

            # Build verdict and caution sections.
            verdict = self._verdict_from_signal(direction, confidence, conflict)
            caution = self._caution_text(composite.get("caution_state", {}))

            # Assemble final plain-text message.
            lines = [
                f"🔵 GREY | {timestamp} | {symbol} {price} | Session: {session_state}",
                "",
                "MODULE SCORES:",
                *module_lines,
                "",
                self.SEPARATOR,
                f"COMPOSITE: {self._signed(composite_score)}",
                f"DIRECTION: {direction}",
                f"CONFIDENCE: {confidence:.2f} ({confidence:.0%})",
                f"CONFLICT: {conflict}",
                self.SEPARATOR,
                "",
                f"⚡ VERDICT: {verdict['headline']}",
            ]
            for detail in verdict["details"]:
                lines.append(f"   • {detail}")
            if caution:
                lines.extend(["", caution])
            return "\n".join(lines)
        except Exception as exc:
            # Return a fallback text if formatting itself fails.
            return self._fallback_message(exc, market_data)

    def _format_module_lines(self, module_vector: Any) -> list[str]:
        """Format all non-guard module rows."""
        if not isinstance(module_vector, Mapping) or not module_vector:
            return ["└─ No module scores available"]

        lines = []
        items = [
            (module_id, module_output)
            for module_id, module_output in module_vector.items()
            if isinstance(module_output, Mapping) and not module_output.get("is_guard")
        ]
        if not items:
            return ["└─ No module scores available"]

        for index, (module_id, module_output) in enumerate(items):
            branch = "└─" if index == len(items) - 1 else "├─"
            lines.append(self._format_module_line(module_id, module_output, branch))
        return lines

    def _format_module_line(self, module_id: str, module_output: Mapping[str, Any], branch: str = "├─") -> str:
        """Format one module row."""
        display_name = self._display_module_id(module_id)
        score = self._module_score(module_output)
        direction = str(module_output.get("direction") or "NEUTRAL").upper()
        confidence = self._clamp_unit(module_output.get("confidence"))
        emoji = self._confidence_emoji(confidence)
        return f"{branch} {display_name:<12} {self._signed(score):>5} ({direction}) {emoji} {confidence:.0%}"

    def _verdict_from_signal(self, direction: str, confidence: float, conflict: str) -> dict:
        """Return verdict headline and action details from composite signal."""
        direction = str(direction or "NEUTRAL").upper()
        confidence = self._clamp_unit(confidence)
        conflict = str(conflict or "").upper()

        if direction == "BULL" and confidence >= 0.65:
            headline = "Strong Bullish"
            details = [
                "Put selling: Ideal",
                "Call selling: Less attractive",
                "Wait: Avoid chasing extended moves",
            ]
        elif direction == "BULL" and confidence >= 0.50:
            headline = "Mildly Bullish"
            details = [
                "Put selling: More attractive",
                "Call selling: Cautious",
                "Wait: Pullback for better entry",
            ]
        elif direction == "BULL":
            headline = "Weak Bullish"
            details = [
                "Put selling: Wait for confirmation",
                "Call selling: Avoid aggressive positioning",
                "Wait: Confirmation needed",
            ]
        elif direction == "BEAR" and confidence >= 0.65:
            headline = "Strong Bearish"
            details = [
                "Call selling: Ideal",
                "Put selling: Risky",
                "Wait: Avoid selling puts into weakness",
            ]
        elif direction == "BEAR" and confidence >= 0.50:
            headline = "Mildly Bearish"
            details = [
                "Call selling: More attractive",
                "Put selling: Avoid",
                "Wait: Bounce for better entry",
            ]
        elif direction == "BEAR":
            headline = "Weak Bearish"
            details = [
                "Call selling: Wait for confirmation",
                "Put selling: Avoid aggressive positioning",
                "Wait: Confirmation needed",
            ]
        else:
            headline = "No Clear Direction"
            details = [
                "Iron Condor: More suitable",
                "Directional selling: Risky",
                "Wait: Let modules align",
            ]

        if conflict == "HIGH_CONFLICT":
            details.append("⚠️ Modules disagreeing sharply — low confidence signal")

        return {"headline": headline, "details": details}

    def _caution_text(self, caution_state: Any) -> str:
        """Format caution or freeze text from caution_state."""
        if not isinstance(caution_state, Mapping):
            return ""

        if bool(caution_state.get("freeze_suggestion")) or str(caution_state.get("level", "")).upper() == "FREEZE":
            return "🛑 FREEZE: Signal confidence set to 0. Skip trading this cycle."

        flags = caution_state.get("flags", [])
        if not flags:
            return ""

        readable_flags = [self._humanize_flag(flag) for flag in flags if flag]
        if not readable_flags:
            return ""
        return f"⚠️ CAUTION: {', '.join(readable_flags)}"

    def _send(self, message: str) -> dict:
        """Send message to Telegram or dry-run when disabled/missing credentials."""
        try:
            full_message = f"{self.prefix} {message}".strip()
            if not self.enabled:
                self.sent_messages.append(full_message)
                return {"sent": False, "dry_run": True, "message": full_message}
            if not self.bot_token or not self.chat_id:
                self.sent_messages.append(full_message)
                return {
                    "sent": False,
                    "dry_run": True,
                    "message": full_message,
                    "reason": "telegram credentials missing",
                }

            encoded = urllib.parse.urlencode({
                "chat_id": self.chat_id,
                "text": full_message,
            }).encode("utf-8")
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            with urllib.request.urlopen(url, data=encoded, timeout=10) as response:
                response.read()
            self.sent_messages.append(full_message)
            return {"sent": True, "dry_run": False, "message": full_message}
        except Exception as exc:
            # Telegram failure should never stop GREY live operation.
            return {"sent": False, "dry_run": False, "message": message, "error": str(exc)}

    def _fallback_message(self, exc: Exception, market_data: Mapping[str, Any]) -> str:
        """Build safe fallback text when formatting fails."""
        symbol = str((market_data or {}).get("symbol") or "NIFTY")
        timestamp = self._format_time((market_data or {}).get("timestamp"))
        return f"🔵 GREY | {timestamp} | {symbol} | Live report formatting failed safely: {exc}"

    @staticmethod
    def _module_score(module_output: Mapping[str, Any]) -> float:
        """Return module score on -10 to +10 scale."""
        if module_output.get("score") is not None:
            return GreyTelegramLiveReporter._display_score(module_output.get("score"))
        raw = GreyTelegramLiveReporter._to_float(module_output.get("raw_score"))
        if raw is None:
            return 0.0
        if -1.0 <= raw <= 1.0:
            return raw * 10.0
        return raw

    @staticmethod
    def _display_score(value: Any) -> float:
        """Display internal -1/+1 scores as -10/+10 scores."""
        parsed = GreyTelegramLiveReporter._to_float(value)
        if parsed is None:
            return 0.0
        if -1.0 <= parsed <= 1.0:
            return parsed * 10.0
        return parsed

    @staticmethod
    def _display_module_id(module_id: Any) -> str:
        """Shorten verbose module IDs for Telegram readability."""
        text = str(module_id or "UNKNOWN").upper()
        aliases = {
            "VIX_REGIME": "VIX",
            "EXPIRY_CYCLE": "EXPIRY",
            "GLOBAL_RISK": "GLOBAL",
        }
        return aliases.get(text, text)

    @staticmethod
    def _confidence_emoji(confidence: float) -> str:
        """Return confidence indicator emoji."""
        confidence = GreyTelegramLiveReporter._clamp_unit(confidence)
        if confidence >= 0.70:
            return "✅"
        if confidence >= 0.50:
            return "⚠️"
        return "❌"

    @staticmethod
    def _format_time(value: Any) -> str:
        """Format timestamp as HH:MM AM/PM."""
        dt = GreyTelegramLiveReporter._parse_dt(value)
        if dt is None:
            text = str(value or "?").strip()
            return text if text else "?"
        return dt.strftime("%I:%M %p").lstrip("0")

    @staticmethod
    def _format_price(value: Any) -> str:
        """Format NIFTY price with commas."""
        numeric = GreyTelegramLiveReporter._to_float(value)
        if numeric is None:
            return "?"
        return f"{numeric:,.0f}"

    @staticmethod
    def _humanize_flag(value: Any) -> str:
        """Convert internal caution flag into readable text."""
        text = str(value or "").replace("_", " ").strip()
        return text.title() if text else ""

    @staticmethod
    def _signed(value: float) -> str:
        """Format score with explicit sign and one decimal place."""
        return f"{float(value):+.1f}"

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        """Parse common timestamp values."""
        if isinstance(value, datetime):
            return value
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if len(text) <= 5 and ":" in text:
                return datetime.strptime(text, "%H:%M")
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            return datetime.fromisoformat(text).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely parse float values."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp_unit(value: Any) -> float:
        """Clamp confidence into 0.0 to 1.0."""
        parsed = GreyTelegramLiveReporter._to_float(value)
        if parsed is None:
            return 0.0
        return max(0.0, min(1.0, parsed))


__all__ = ["GreyTelegramLiveReporter"]
