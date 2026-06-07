"""
Phase 1 runner for GREY market intelligence review.

GREY Phase 1 records market views, evaluates them 15 minutes later, and sends
one simple Telegram-style message per evaluated signal.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

import grey_config
from grey_data_quality_guard import GreyDataQualityGuard
from grey_expiry_cycle_module import GreyExpiryCycleModule
from grey_global_risk_module import GreyGlobalRiskModule
from grey_india_macro_module import GreyIndiaMacroModule
from grey_kronos_module import GreyKronosModule
from grey_oi_change_module import GreyOiChangeModule
from grey_options_microstructure import GreyOptionsMicrostructure
from grey_pcr_module import GreyPcrModule
from grey_regime_engine import GreyRegimeEngine
from grey_sector_rotation_module import GreySectorRotationModule
from grey_session_machine import GreySessionMachine
from grey_signal_aggregator import GreySignalAggregator
from grey_telegram_live_reporter import GreyTelegramLiveReporter
from grey_vix_regime_module import GreyVixRegimeModule
from market_calendar import MarketCalendar


class GreySignalStore:
    """JSONL store for GREY Phase 1 signals."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or getattr(
            grey_config,
            "GREY_PHASE1_SIGNAL_LOG_PATH",
            "journals/grey/phase1_signals.jsonl",
        ))

    def append_signal(self, signal: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(signal, default=str, sort_keys=True) + "\n")

    def load_signals(self) -> list[dict]:
        if not self.path.exists():
            return []
        signals = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    signals.append(json.loads(line))
        return signals

    def rewrite_signals(self, signals: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for signal in signals:
                handle.write(json.dumps(signal, default=str, sort_keys=True) + "\n")


class GreyTelegramNotifier:
    """Simple Telegram sender with dry-run fallback."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        bot_token: str | None = None,
        chat_id: str | None = None,
        prefix: str | None = None,
    ) -> None:
        self.enabled = (
            bool(getattr(grey_config, "GREY_TELEGRAM_ENABLED", False))
            if enabled is None
            else enabled
        )
        self.bot_token = bot_token or getattr(grey_config, "GREY_TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or getattr(grey_config, "GREY_TELEGRAM_CHAT_ID", "")
        self.prefix = prefix or getattr(grey_config, "GREY_TELEGRAM_PREFIX", "GREY:")
        self.sent_messages: list[str] = []

    def send(self, message: str) -> dict:
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


class GreyPhase1Engine:
    """Generate, store, evaluate, and report GREY Phase 1 signals."""

    def __init__(
        self,
        *,
        store: GreySignalStore | None = None,
        notifier: GreyTelegramNotifier | None = None,
        live_reporter: GreyTelegramLiveReporter | None = None,
        calendar: MarketCalendar | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store or GreySignalStore()
        self.notifier = notifier or GreyTelegramNotifier()
        self.live_reporter = live_reporter or GreyTelegramLiveReporter()
        self.calendar = calendar or MarketCalendar()
        self.now_provider = now_provider or datetime.now
        self.session_machine = GreySessionMachine()
        self.options = GreyOptionsMicrostructure()
        self.regime = GreyRegimeEngine()
        self.kronos = GreyKronosModule()
        self.vix_regime = GreyVixRegimeModule()
        self.pcr = GreyPcrModule()
        self.expiry_cycle = GreyExpiryCycleModule()
        self.oi_change = GreyOiChangeModule()
        self.global_risk = GreyGlobalRiskModule()
        self.india_macro = GreyIndiaMacroModule()
        self.sector = GreySectorRotationModule()
        self.data_quality = GreyDataQualityGuard()
        self.aggregator = GreySignalAggregator()
        self.evaluation_delay_minutes = int(getattr(
            grey_config,
            "GREY_PHASE1_EVALUATION_DELAY_MINUTES",
            15,
        ))
        self.live_report_frequency_seconds = int(getattr(
            grey_config,
            "GREY_TELEGRAM_LIVE_FREQUENCY_SECONDS",
            300,
        ))
        self._last_live_report_at: dict[str, datetime] = {}

    def run_cycle(
        self,
        market_data_by_symbol: Mapping[str, dict],
        dt: datetime | None = None,
    ) -> dict:
        """
        Run one unattended Phase 1 cycle.

        The cycle creates one signal per symbol during market hours, then
        evaluates any stored signals whose 15-minute window is due.
        """
        cycle_dt = dt or self.now_provider()
        created = []
        for symbol, market_data in market_data_by_symbol.items():
            result = self.run_once(symbol, market_data, cycle_dt)
            if result.get("created", True):
                created.append(result)
        evaluated = self.evaluate_due_signals(market_data_by_symbol, cycle_dt)
        return {
            "timestamp": cycle_dt.isoformat(),
            "created_count": len(created),
            "evaluated_count": len(evaluated),
            "created": created,
            "evaluated": evaluated,
        }

    def run_once(self, symbol: str, market_data: dict, dt: datetime | None = None) -> dict:
        """Generate and store one valid GREY market view."""
        signal_dt = dt or self.now_provider()
        if not self.is_market_hours(signal_dt):
            return {
                "created": False,
                "reason": "outside_market_hours",
                "timestamp": signal_dt.isoformat(),
                "symbol": symbol,
            }

        event_minutes = self.calendar.get_next_event_minutes(signal_dt)
        session_state = self.session_machine.get_current_state(
            signal_dt,
            is_expiry=bool(market_data.get("is_expiry", False)),
            event_minutes_away=event_minutes,
        )
        is_expiry_sensitive = self.session_machine.is_expiry_sensitive(
            signal_dt,
            bool(market_data.get("is_expiry", False)),
        )
        module_outputs = self._build_module_outputs(
            market_data=market_data,
            session_state=session_state,
            is_expiry_sensitive=is_expiry_sensitive,
            dt=signal_dt,
        )
        composite = self.aggregator.aggregate(module_outputs, session_state)
        signal = self._signal_record(
            symbol=symbol,
            dt=signal_dt,
            session_state=session_state,
            composite=composite,
            market_data=market_data,
        )
        self.store.append_signal(signal)
        signal["live_telegram"] = self._send_live_report(
            symbol=symbol,
            dt=signal_dt,
            composite=composite,
            market_data=market_data,
            session_state=session_state,
        )
        return signal

    def evaluate_due_signals(
        self,
        current_market_data_by_symbol: Mapping[str, dict],
        dt: datetime | None = None,
    ) -> list[dict]:
        """Evaluate due signals and send one Telegram message for each."""
        current_dt = dt or self.now_provider()
        signals = self.store.load_signals()
        evaluated = []

        for signal in signals:
            if signal.get("evaluation"):
                continue
            signal_dt = datetime.fromisoformat(signal["timestamp"])
            if current_dt - signal_dt < timedelta(minutes=self.evaluation_delay_minutes):
                continue

            symbol = signal["symbol"]
            current_market_data = current_market_data_by_symbol.get(symbol)
            if not current_market_data:
                continue

            evaluation = self.evaluate_signal(signal, current_market_data, current_dt)
            signal["evaluation"] = evaluation
            signal["telegram"] = self.notifier.send(
                self.format_telegram_message(signal, evaluation)
            )
            evaluated.append(signal)

        if evaluated:
            self.store.rewrite_signals(signals)
        return evaluated

    def evaluate_signal(
        self,
        signal: Mapping[str, Any],
        current_market_data: Mapping[str, Any],
        dt: datetime,
    ) -> dict:
        """Evaluate a stored signal against the 15-minute outcome."""
        entry_price = self._to_float(signal.get("entry_price"))
        current_price = self._to_float(current_market_data.get("price"))
        if entry_price is None or current_price is None or entry_price <= 0:
            actual_move = 0.0
            result = "UNKNOWN"
        else:
            actual_move = (current_price - entry_price) / entry_price
            result = self._result_label(signal.get("direction_bias"), actual_move)

        return {
            "evaluated_at": dt.isoformat(),
            "result": result,
            "actual_move": round(actual_move, 5),
            "current_price": current_price,
            "remark": self._remark(result, signal.get("caution_state", {})),
        }

    def format_telegram_message(
        self,
        signal: Mapping[str, Any],
        evaluation: Mapping[str, Any],
    ) -> str:
        """Build the Phase 1 Telegram message."""
        module_lines = []
        for module_id, vector in signal.get("module_vector", {}).items():
            if not isinstance(vector, Mapping) or vector.get("is_guard"):
                continue
            module_lines.append(
                f"- {module_id}: {vector.get('weighted_score', 0)} "
                f"({vector.get('direction', 'NEUTRAL')}, conf {vector.get('confidence', 0)})"
            )
        if not module_lines:
            module_lines.append("- No module scores available")

        return "\n".join([
            f"Signal time: {signal.get('timestamp')}",
            f"Symbol: {signal.get('symbol')}",
            f"Session: {signal.get('session_state')}",
            f"Direction: {signal.get('direction_bias')}",
            f"Confidence: {signal.get('confidence')}",
            f"Caution: {signal.get('caution_state', {}).get('level', 'UNKNOWN')}",
            "Module scores:",
            *module_lines,
            f"Total score: {signal.get('composite_score')}",
            f"15-min result: {evaluation.get('result')}",
            f"Actual move: {evaluation.get('actual_move')}",
            f"Remark: {evaluation.get('remark')}",
        ])

    def is_market_hours(self, dt: datetime) -> bool:
        """Return True when GREY should generate market views."""
        timings = grey_config.GREY_SESSION_TIMINGS
        start = self._combine(dt.date(), timings["PRE_OPEN_START"])
        close_key = self._close_time_key(dt.date())
        end = self._combine(dt.date(), timings[close_key])
        return start <= dt <= end

    def _send_live_report(
        self,
        *,
        symbol: str,
        dt: datetime,
        composite: Mapping[str, Any],
        market_data: Mapping[str, Any],
        session_state: str,
    ) -> dict:
        """Send one live Telegram report without risking the GREY loop."""
        try:
            if not getattr(self.live_reporter, "enabled", False):
                return {"sent": False, "skipped": True, "reason": "live telegram disabled"}

            last_sent_at = self._last_live_report_at.get(symbol)
            if last_sent_at is not None:
                elapsed_seconds = (dt - last_sent_at).total_seconds()
                if elapsed_seconds < self.live_report_frequency_seconds:
                    return {
                        "sent": False,
                        "skipped": True,
                        "reason": "live telegram frequency throttle",
                        "elapsed_seconds": int(elapsed_seconds),
                    }

            report_market_data = dict(market_data or {})
            report_market_data["symbol"] = symbol
            report_market_data["timestamp"] = report_market_data.get("timestamp", dt)
            report_market_data["session_state"] = session_state

            result = self.live_reporter.send_live_signal(dict(composite), report_market_data)
            if result.get("sent") or result.get("dry_run"):
                self._last_live_report_at[symbol] = dt
            return result
        except Exception as exc:
            return {
                "sent": False,
                "skipped": False,
                "error": f"live telegram failed safely: {exc}",
            }

    def _build_module_outputs(
        self,
        *,
        market_data: dict,
        session_state: str,
        is_expiry_sensitive: bool,
        dt: datetime,
    ) -> dict:
        outputs = {
            "OPTIONS": self.options.evaluate(market_data, session_state, is_expiry_sensitive),
            "REGIME": self.regime.evaluate(market_data, session_state, is_expiry_sensitive),
            "KRONOS": self.kronos.evaluate(
                ohlcv_df=market_data.get("ohlcv_df"),
                session_state=session_state,
            ),
            "VIX_REGIME": self.vix_regime.evaluate(market_data, session_state),
            "PCR": self.pcr.evaluate(market_data, session_state),
            "EXPIRY_CYCLE": self.expiry_cycle.evaluate(market_data, session_state),
            "OI_CHANGE": self.oi_change.evaluate(market_data, session_state),
            "GLOBAL": self.global_risk.evaluate(market_data, session_state),
            "INDIA_MACRO": self.india_macro.evaluate(market_data, session_state),
            "SECTOR": self.sector.evaluate(market_data, session_state),
        }
        guard_inputs = dict(market_data)
        guard_inputs["timestamp"] = guard_inputs.get("timestamp", dt)
        guard_inputs["session_state"] = session_state
        guard_inputs["module_outputs"] = outputs
        guard_inputs["implied_volatility"] = guard_inputs.get(
            "implied_volatility",
            guard_inputs.get("ivp"),
        )
        outputs["DATA_QUALITY"] = self.data_quality.evaluate(guard_inputs, dt)
        return outputs

    def _signal_record(
        self,
        *,
        symbol: str,
        dt: datetime,
        session_state: str,
        composite: Mapping[str, Any],
        market_data: Mapping[str, Any],
    ) -> dict:
        return {
            "timestamp": dt.isoformat(),
            "symbol": symbol,
            "session_state": session_state,
            "direction_bias": composite["direction_bias"],
            "confidence": composite["confidence"],
            "caution_state": composite["caution_state"],
            "module_vector": composite["module_vector"],
            "composite_score": composite["composite_score"],
            "entry_price": self._to_float(market_data.get("price")),
            "evaluation_due_at": (
                dt + timedelta(minutes=self.evaluation_delay_minutes)
            ).isoformat(),
        }

    def _close_time_key(self, current_date: date) -> str:
        extension_date = date.fromisoformat(
            grey_config.GREY_SESSION_TIMINGS["NSE_EXTENSION_DATE"]
        )
        if current_date >= extension_date:
            return "DERIVATIVES_CLOSE_EXTENDED"
        return "DERIVATIVES_CLOSE"

    @staticmethod
    def _combine(current_date: date, time_text: str) -> datetime:
        return datetime.combine(current_date, time.fromisoformat(time_text))

    @staticmethod
    def _result_label(direction_bias: Any, actual_move: float) -> str:
        direction = str(direction_bias or "NEUTRAL").upper()
        if direction == "BULL":
            return "CORRECT" if actual_move > 0 else "WRONG"
        if direction == "BEAR":
            return "CORRECT" if actual_move < 0 else "WRONG"
        return "NEUTRAL_REVIEW"

    @staticmethod
    def _remark(result: str, caution_state: Mapping[str, Any]) -> str:
        if caution_state.get("level") == "FREEZE":
            return "Frozen signal; review only."
        if result == "CORRECT":
            return "Signal matched the 15-minute move."
        if result == "WRONG":
            return "Signal did not match the 15-minute move."
        if result == "NEUTRAL_REVIEW":
            return "Neutral signal; movement noted for review."
        return "Outcome could not be evaluated from available data."

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


__all__ = ["GreyPhase1Engine", "GreySignalStore", "GreyTelegramNotifier"]
