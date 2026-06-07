"""
GREY 2.0 enhanced Phase 1 engine.

Run with:
    python grey_enhanced_phase1_engine.py

Default mode is a safe one-cycle dummy run. Set GREY2_LOOP=True and provide
real data inputs to run every five minutes during market hours.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Mapping

from grey_microstructure_analyzer import GreyMicrostructureAnalyzer
from grey_gemini_reasoning_engine import GreyGeminiReasoningEngine
from grey_options_flow_monitor import GreyOptionsFlowMonitor
from grey_phase1_engine import GreyPhase1Engine
from grey_reasoning_engine import GreyReasoningEngine
from grey_risk_manager import GreyRiskManager
from grey_signal_aggregator import GreySignalAggregator

try:
    from grey_live_data_provider import GreyLiveDataProvider
except Exception:
    GreyLiveDataProvider = None


class GreyEnhancedPhase1Engine:
    """Combine Phase 1 technical GREY with AI, flow, depth, and risk controls."""

    ENHANCED_AGGREGATOR_CONFIG = {
        "module_weights": {
            "NEWS": 0.40,
            "SENTIMENT": 0.65,
            "REASONING": 0.60,
            "GEMINI": 0.60,
            "OPTIONS_FLOW": 0.95,
            "MICROSTRUCTURE": 0.75,
        },
        "session_multipliers": {
            "OPENING_DRIVE": {
                "NEWS": 0.90,
                "SENTIMENT": 0.80,
                "OPTIONS_FLOW": 1.15,
                "MICROSTRUCTURE": 1.20,
                "REASONING": 0.80,
                "GEMINI": 0.80,
            },
            "EARLY_TREND": {
                "OPTIONS_FLOW": 1.10,
                "MICROSTRUCTURE": 1.05,
                "SENTIMENT": 0.95,
            },
            "MIDDAY": {
                "NEWS": 1.00,
                "SENTIMENT": 0.80,
                "OPTIONS_FLOW": 0.95,
                "MICROSTRUCTURE": 0.85,
            },
            "PRE_EVENT": {
                "NEWS": 1.15,
                "SENTIMENT": 0.70,
                "REASONING": 1.00,
                "GEMINI": 1.00,
                "OPTIONS_FLOW": 0.80,
            },
            "CLOSING_DRIVE": {
                "OPTIONS_FLOW": 1.15,
                "MICROSTRUCTURE": 1.10,
                "NEWS": 0.80,
            },
        },
    }

    def __init__(
        self,
        *,
        dummy_mode: bool | None = None,
        journal_path: str | Path | None = None,
        data_provider: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        env_dummy = os.getenv("GREY2_DUMMY_MODE", "True").strip().lower() == "true"
        self.dummy_mode = env_dummy if dummy_mode is None else dummy_mode
        self.journal_path = Path(journal_path or "journals/grey/enhanced_signals.jsonl")
        self.logger = logger or self._configure_logger()
        self.data_provider = data_provider

        self.phase1 = GreyPhase1Engine()
        self.disable_news = self._env_bool("GREY_DISABLE_NEWS", True)
        self.disable_sentiment = self._env_bool("GREY_DISABLE_SENTIMENT", True)
        self.news = None if self.disable_news else self._optional_news_aggregator()
        self.sentiment = None if self.disable_sentiment else self._optional_sentiment_engine()
        self.reasoning = GreyReasoningEngine(dummy_mode=self.dummy_mode, logger=self.logger)
        self.use_gemini = self._env_bool("GREY_GEMINI_ENABLED", False)
        self.ab_test_mode = self._env_bool("GREY_PARALLEL_AB_TEST", self._env_bool("GREY_A_B_TEST_MODE", False))
        self.risk_manager_enabled = self._env_bool("GREY_RISK_MANAGER_ENABLED", True)
        self.risk_manager = (
            GreyRiskManager(
                account_size=float(os.getenv("GREY_ACCOUNT_SIZE", "100000") or "100000"),
                max_daily_loss_pct=float(os.getenv("GREY_RISK_MAX_DAILY_LOSS_PCT", "0.02") or "0.02"),
                logger=self.logger,
            )
            if self.risk_manager_enabled
            else None
        )
        self.gemini_engine = (
            GreyGeminiReasoningEngine(logger=self.logger)
            if self.use_gemini
            else None
        )
        self._gemini_cycle_count = 0
        self.options_flow = GreyOptionsFlowMonitor(dummy_mode=self.dummy_mode, logger=self.logger)
        self.microstructure = GreyMicrostructureAnalyzer(dummy_mode=self.dummy_mode, logger=self.logger)
        self.aggregator = GreySignalAggregator(config=self.ENHANCED_AGGREGATOR_CONFIG)
        self._cycle_count = 0
        self._last_heartbeat_at: datetime | None = None
        self.heartbeat_frequency_seconds = int(os.getenv("GREY_HEARTBEAT_FREQUENCY_SECONDS", "1800") or "1800")

    def run_once(
        self,
        *,
        symbol: str = "NIFTY",
        market_data: dict | None = None,
        option_rows: list[dict] | None = None,
        news_items: list[dict] | None = None,
        social_items: list[dict] | None = None,
        dt: datetime | None = None,
    ) -> dict:
        """Run one enhanced intelligence cycle and store the result."""
        cycle_dt = dt or datetime.now()
        self._cycle_count += 1
        data = market_data or self._load_market_data(symbol)
        data.setdefault("symbol", symbol)
        data.setdefault("timestamp", cycle_dt.isoformat())

        session_state, is_expiry_sensitive = self._session_context(data, cycle_dt)
        technical_outputs = self.phase1._build_module_outputs(
            market_data=data,
            session_state=session_state,
            is_expiry_sensitive=is_expiry_sensitive,
            dt=cycle_dt,
        )
        technical_outputs = self._sanitize_unavailable_module_caps(technical_outputs)
        technical_composite = self.phase1.aggregator.aggregate(technical_outputs, session_state)

        collected_news = self._collect_news(news_items)
        sentiment = self._analyze_sentiment(collected_news, social_items)
        options_flow = self.options_flow.analyze(
            option_rows=option_rows,
            spot_price=self._to_float(data.get("price")),
            timestamp=cycle_dt,
        )
        microstructure = self.microstructure.analyze(data)

        pre_reasoning_context = {
            "symbol": symbol,
            "timestamp": cycle_dt.isoformat(),
            "session_state": session_state,
            "market_data": self._json_safe(data),
            "technical_composite": technical_composite,
            "options_flow": options_flow,
            "microstructure": microstructure,
        }
        reasoning = self.reasoning.analyze(pre_reasoning_context)
        gemini_context = self._build_gemini_context(
            market_data=data,
            options_flow=options_flow,
            microstructure=microstructure,
            technical_composite=technical_composite,
        )
        gemini_reasoning = self._maybe_run_gemini(gemini_context, technical_composite)
        reasoning_reconciliation = self._reconcile_all_reasoning(
            technical=technical_composite,
            gemini=gemini_reasoning,
            claude=reasoning,
        )
        news_packet = self._news_packet(collected_news)
        gemini_packet = self._gemini_module_packet(gemini_reasoning)

        module_outputs = {
            **technical_outputs,
            "OPTIONS_FLOW": options_flow,
            "MICROSTRUCTURE": microstructure,
            "REASONING": reasoning,
        }
        if news_packet is not None:
            module_outputs["NEWS"] = news_packet
        if not self.disable_sentiment:
            module_outputs["SENTIMENT"] = sentiment
        if gemini_packet is not None:
            module_outputs["GEMINI"] = gemini_packet
        enhanced_signal = self.aggregator.aggregate(module_outputs, session_state)
        enhanced_signal["reasoning_summary"] = reasoning.get("reasoning_summary", "")
        enhanced_signal["trade_entry_time"] = data.get("trade_entry_time") or cycle_dt.isoformat()
        enhanced_signal["risk_decision"] = self._risk_decision(enhanced_signal, data)
        enhanced_signal["news_count"] = len(collected_news)
        enhanced_signal["gemini_reasoning"] = gemini_reasoning
        enhanced_signal["claude_reasoning"] = reasoning
        enhanced_signal["gemini_vs_claude"] = reasoning_reconciliation
        ab_test = self._build_ab_test_result(
            module_outputs=module_outputs,
            session_state=session_state,
            gemini_reasoning=gemini_reasoning,
        )
        parallel_ab_test = self._build_parallel_ab_test_result(
            module_outputs=module_outputs,
            session_state=session_state,
            gemini_reasoning=gemini_reasoning,
        )

        result = {
            "timestamp": cycle_dt.isoformat(),
            "symbol": symbol,
            "session_state": session_state,
            "dummy_mode": self.dummy_mode,
            "market_data": self._json_safe(data),
            "news": collected_news,
            "sentiment": sentiment,
            "options_flow": options_flow,
            "microstructure": microstructure,
            "reasoning": reasoning,
            "claude_reasoning": reasoning,
            "gemini_reasoning": gemini_reasoning,
            "gemini_vs_claude": reasoning_reconciliation,
            "technical_composite": technical_composite,
            "module_outputs": module_outputs,
            "enhanced_signal": enhanced_signal,
            "ab_test": ab_test,
            "parallel_ab_test": parallel_ab_test,
            "baseline_direction": parallel_ab_test.get("baseline_direction"),
            "baseline_confidence": parallel_ab_test.get("baseline_confidence"),
            "baseline_score": parallel_ab_test.get("baseline_score"),
            "gemini_direction": parallel_ab_test.get("gemini_direction"),
            "gemini_confidence": parallel_ab_test.get("gemini_confidence"),
            "gemini_score": parallel_ab_test.get("gemini_score"),
            "both_correct": parallel_ab_test.get("both_correct"),
            "baseline_only_correct": parallel_ab_test.get("baseline_only_correct"),
            "gemini_only_correct": parallel_ab_test.get("gemini_only_correct"),
        }
        self._append_journal(result)
        self.logger.info(
            "GREY2 cycle complete symbol=%s score=%s direction=%s confidence=%s risk_allowed=%s",
            symbol,
            enhanced_signal.get("composite_score"),
            enhanced_signal.get("direction_bias"),
            enhanced_signal.get("confidence"),
            enhanced_signal.get("risk_decision", {}).get("should_trade"),
        )
        return result

    def _maybe_run_gemini(
        self,
        market_context: Mapping[str, Any],
        technical_composite: Mapping[str, Any],
    ) -> dict | None:
        """Run Gemini only when enabled and its frequency/confidence gate allows it."""
        if not self.use_gemini or self.gemini_engine is None:
            return None

        self._gemini_cycle_count += 1
        frequency = max(1, int(getattr(self.gemini_engine, "frequency", 1)))
        if self._gemini_cycle_count % frequency != 0:
            return self.gemini_engine._fallback_response("Gemini skipped by frequency gate")

        technical_confidence = self._to_float(technical_composite.get("confidence")) or 0.0
        min_confidence = float(getattr(self.gemini_engine, "min_confidence", 0.55))
        if self.gemini_engine.enabled and technical_confidence >= min_confidence:
            return self.gemini_engine._fallback_response(
                "Gemini skipped because technical confidence is already high"
            )

        return self.gemini_engine.analyze_market(dict(market_context))

    def _build_gemini_context(
        self,
        *,
        market_data: Mapping[str, Any],
        options_flow: Mapping[str, Any],
        microstructure: Mapping[str, Any],
        technical_composite: Mapping[str, Any],
    ) -> dict:
        """Flatten GREY context into Gemini's operator-friendly prompt fields."""
        alerts = options_flow.get("alerts", []) if isinstance(options_flow, Mapping) else []
        return {
            "price": market_data.get("price"),
            "atr": market_data.get("atr_14") or market_data.get("atr"),
            "range": market_data.get("range") or market_data.get("intraday_range"),
            "put_wall": market_data.get("put_wall_weight"),
            "call_wall": market_data.get("call_wall_weight"),
            "pcr": market_data.get("pcr_oi") or market_data.get("pcr"),
            "unusual_oi": "; ".join(str(item.get("message", "")) for item in alerts) or options_flow.get("smart_positioning"),
            "gift_nifty": market_data.get("gift_nifty_return_pct") or market_data.get("gift_nifty"),
            "us_futures": market_data.get("us_futures_return_pct") or market_data.get("us_futures"),
            "vix": market_data.get("india_vix") or market_data.get("vix"),
            "fii_flow": market_data.get("fii_flow") or market_data.get("fii_flow_cr"),
            "spread": market_data.get("spread_pct") or microstructure.get("spread_pct"),
            "volume_profile": market_data.get("volume_profile"),
            "aggressiveness": market_data.get("aggressiveness") or microstructure.get("market_strength"),
            "technical_direction": technical_composite.get("direction_bias"),
            "technical_confidence": technical_composite.get("confidence"),
        }

    def _reconcile_all_reasoning(
        self,
        *,
        technical: Mapping[str, Any],
        gemini: Mapping[str, Any] | None,
        claude: Mapping[str, Any] | None,
    ) -> dict:
        """Compare technical, Gemini, and Claude-style reasoning outputs."""
        views = []
        technical_decision = self._decision_from_direction(technical.get("direction_bias"))
        views.append({
            "model": "TECHNICAL",
            "decision": technical_decision,
            "side": self._decision_side(technical_decision),
            "confidence": self._to_float(technical.get("confidence")) or 0.0,
        })
        if gemini and gemini.get("decision") != "FALLBACK_TO_RULES":
            views.append({
                "model": "GEMINI",
                "decision": str(gemini.get("decision")),
                "side": self._decision_side(gemini.get("decision")),
                "confidence": self._to_float(gemini.get("confidence")) or 0.0,
            })
        if claude:
            claude_decision = self._decision_from_direction(claude.get("direction"))
            views.append({
                "model": "CLAUDE",
                "decision": claude_decision,
                "side": self._decision_side(claude_decision),
                "confidence": self._to_float(claude.get("confidence")) or 0.0,
            })

        active = [view for view in views if view["side"] not in {"UNKNOWN", "FALLBACK"}]
        if not active:
            return {
                "consensus": False,
                "primary_decision": "WAIT_FOR_CLARITY",
                "confidence": 0.0,
                "models_used": [],
                "remark": "No usable reasoning model was available; fallback to GREY rules.",
            }

        sides = {view["side"] for view in active}
        models_used = [view["model"] for view in active]
        avg_confidence = sum(view["confidence"] for view in active) / len(active)
        primary = max(active, key=lambda view: view["confidence"])
        if len(sides) == 1:
            return {
                "consensus": True,
                "primary_decision": primary["decision"],
                "confidence": round(min(1.0, avg_confidence), 3),
                "models_used": models_used,
                "remark": f"Reasoning models agree on {primary['side']} bias.",
            }
        return {
            "consensus": False,
            "primary_decision": "WAIT_FOR_CLARITY",
            "confidence": round(max(0.0, avg_confidence * 0.50), 3),
            "models_used": models_used,
            "remark": "Gemini, Claude, or technical reasoning disagrees; manual review recommended.",
            "perspectives": active,
        }

    @staticmethod
    def _gemini_module_packet(gemini: Mapping[str, Any] | None) -> dict | None:
        """Convert Gemini output into the GREY aggregator packet shape."""
        if not gemini:
            return None
        decision = str(gemini.get("decision") or "FALLBACK_TO_RULES")
        confidence = GreyEnhancedPhase1Engine._clamp(
            GreyEnhancedPhase1Engine._to_float(gemini.get("confidence")) or 0.0,
            0.0,
            1.0,
        )
        side = GreyEnhancedPhase1Engine._decision_side(decision)
        score = 0.0
        if side == "BULL":
            score = 10.0 if decision == "STRONG_BULL" else 5.0
        elif side == "BEAR":
            score = -10.0 if decision == "STRONG_BEAR" else -5.0
        return {
            "module_id": "GEMINI",
            "score": score,
            "direction": side if side in {"BULL", "BEAR", "NEUTRAL"} else "NEUTRAL",
            "confidence": confidence,
            "status": "ACTIVE" if gemini.get("enabled") else "FALLBACK",
            "top_driver": str(gemini.get("reasoning", ""))[:160],
            "raw_components": {
                "decision": decision,
                "model": gemini.get("model"),
                "tokens_estimated": gemini.get("tokens_estimated"),
            },
        }

    @staticmethod
    def _decision_from_direction(direction: Any) -> str:
        text = str(direction or "").upper()
        if text == "BULL":
            return "MILD_BULL"
        if text == "BEAR":
            return "MILD_BEAR"
        return "NEUTRAL"

    @staticmethod
    def _decision_side(decision: Any) -> str:
        text = str(decision or "").upper()
        if "BULL" in text:
            return "BULL"
        if "BEAR" in text:
            return "BEAR"
        if text in {"NEUTRAL", "NEUTRAL_SETUP"}:
            return "NEUTRAL"
        if "FALLBACK" in text:
            return "FALLBACK"
        return "UNKNOWN"

    def run_loop(self, *, symbol: str = "NIFTY", interval_seconds: int | None = None) -> None:
        """Run every five minutes during market hours. Dummy mode still works."""
        interval = int(interval_seconds or os.getenv("GREY2_INTERVAL_SECONDS", "300"))
        print("GREY 2.0 enhanced engine running. Press Ctrl+C to stop.")
        while True:
            try:
                now = datetime.now()
                if self._is_market_hours(now) or self.dummy_mode:
                    result = self.run_once(symbol=symbol, dt=now)
                    self._print_console_summary(result)
                    self.send_heartbeat_to_telegram(result=result, dt=now)
                else:
                    print(f"{now:%H:%M:%S} outside market hours; sleeping.")
                time.sleep(interval)
            except KeyboardInterrupt:
                print("GREY 2.0 stopped by user.")
                break
            except Exception as exc:
                self.logger.exception("GREY2 loop failed safely: %s", exc)
                print(f"GREY 2.0 cycle skipped safely: {exc}")
                self.send_heartbeat_to_telegram(error=str(exc), dt=datetime.now())
                time.sleep(interval)

    def send_heartbeat_to_telegram(
        self,
        *,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
        dt: datetime | None = None,
    ) -> dict:
        """Send a throttled 15-minute GREY health heartbeat.

        Args:
            result: Latest cycle result, used to report degraded data.
            error: Latest loop error, if one occurred.
            dt: Current timestamp for throttle checks.

        Returns:
            Telegram sender result or a skipped marker.
        """
        heartbeat_dt = dt or datetime.now()
        if self._last_heartbeat_at is not None:
            elapsed = (heartbeat_dt - self._last_heartbeat_at).total_seconds()
            if elapsed < self.heartbeat_frequency_seconds:
                return {"sent": False, "skipped": True, "reason": "heartbeat throttle"}

        status = "OK GREY running"
        if error:
            status = f"WARNING GREY running but last cycle errored: {error}"
        elif isinstance(result, Mapping):
            errors = result.get("market_data", {}).get("data_provider_errors", [])
            if errors:
                status = f"WARNING GREY running with degraded data: {', '.join(map(str, errors[:2]))}"

        message = (
            f"{status} (cycle {self._cycle_count}, memory {self._memory_usage_text()}, "
            f"news_disabled={self.disable_news}, sentiment_disabled={self.disable_sentiment})"
        )
        self._last_heartbeat_at = heartbeat_dt
        self.logger.info("Heartbeat: %s", message)
        try:
            sender = getattr(self.phase1, "live_reporter", None)
            if sender is not None and hasattr(sender, "_send"):
                return sender._send(message)
        except Exception as exc:
            self.logger.warning("Heartbeat Telegram send failed safely: %s", exc)
        return {"sent": False, "skipped": True, "message": message}

    def _session_context(self, market_data: Mapping[str, Any], dt: datetime) -> tuple[str, bool]:
        event_minutes = self.phase1.calendar.get_next_event_minutes(dt)
        is_expiry = bool(market_data.get("is_expiry", False))
        session_state = self.phase1.session_machine.get_current_state(dt, is_expiry, event_minutes)
        is_expiry_sensitive = self.phase1.session_machine.is_expiry_sensitive(dt, is_expiry)
        return session_state, is_expiry_sensitive

    def _load_market_data(self, symbol: str) -> dict:
        if self.dummy_mode:
            return self._dummy_market_data(symbol)
        try:
            if self.data_provider is not None:
                return dict(self.data_provider.get_market_context(symbol))
            if GreyLiveDataProvider is not None:
                return dict(GreyLiveDataProvider().get_market_context(symbol))
        except Exception as exc:
            self.logger.warning("Live market context failed safely: %s", exc)
        return self._dummy_market_data(symbol)

    def _collect_news(self, news_items: list[dict] | None) -> list[dict]:
        """Return news only when the operator explicitly enables news."""
        if self.disable_news:
            self.logger.info("News aggregation disabled by GREY_DISABLE_NEWS")
            return []
        if news_items is not None:
            return list(news_items)
        if self.news is None:
            return []
        try:
            return list(self.news.collect(max_items=30))
        except Exception as exc:
            self.logger.warning("News aggregation failed safely: %s", exc)
            return []

    def _analyze_sentiment(
        self,
        news_items: list[dict],
        social_items: list[dict] | None,
    ) -> dict:
        """Return sentiment only when explicitly enabled."""
        if self.disable_sentiment:
            self.logger.info("Sentiment analysis disabled by GREY_DISABLE_SENTIMENT")
            return {
                "module_id": "SENTIMENT",
                "score": 0.0,
                "direction": "NEUTRAL",
                "confidence": 0.0,
                "status": "DISABLED",
                "top_driver": "sentiment disabled for shadow baseline",
            }
        if self.sentiment is None:
            return {"status": "UNAVAILABLE", "direction": "NEUTRAL", "confidence": 0.0}
        try:
            return dict(self.sentiment.analyze(news_items=news_items, social_items=social_items))
        except Exception as exc:
            self.logger.warning("Sentiment analysis failed safely: %s", exc)
            return {"status": "ERROR", "direction": "NEUTRAL", "confidence": 0.0, "error": str(exc)}

    def _risk_decision(self, signal: Mapping[str, Any], market_data: Mapping[str, Any]) -> dict:
        """Apply risk manager controls to one enhanced signal."""
        if self.risk_manager is None:
            return {"enabled": False, "should_trade": True, "reason": "risk manager disabled"}
        try:
            allowed = self.risk_manager.should_trade(signal)
            confidence = self._to_float(signal.get("confidence")) or 0.0
            vix_level = (
                self._to_float(market_data.get("india_vix"))
                or self._to_float(market_data.get("vix"))
                or 20.0
            )
            decision = {
                "enabled": True,
                "should_trade": allowed,
                "position_lots": self.risk_manager.position_size(confidence, vix_level) if allowed else 0,
                "vix_level": round(vix_level, 2),
                "max_daily_loss_amount": round(self.risk_manager.max_daily_loss_amount, 2),
                "current_daily_loss": round(self.risk_manager.current_daily_loss, 2),
            }
            sold_premium = self._to_float(market_data.get("sold_premium"))
            if sold_premium is not None:
                elapsed = self._time_in_trade_minutes(signal, market_data)
                decision["time_in_trade_minutes"] = elapsed
                decision["iron_condor_stop_loss"] = self.risk_manager.stop_loss_for_iron_condor(sold_premium, elapsed)
            self.logger.info("Risk decision: %s", decision)
            return decision
        except Exception as exc:
            self.logger.warning("Risk decision failed safely: %s", exc)
            return {"enabled": True, "should_trade": False, "error": str(exc)}

    def _build_ab_test_result(
        self,
        *,
        module_outputs: Mapping[str, Any],
        session_state: str,
        gemini_reasoning: Mapping[str, Any] | None,
    ) -> dict:
        """Log parallel Gemini-on and Gemini-off signal versions."""
        if not self.ab_test_mode:
            return {"enabled": False}
        try:
            without_gemini_outputs = {
                module_id: output
                for module_id, output in module_outputs.items()
                if str(module_id).upper() != "GEMINI"
            }
            version_b = self.aggregator.aggregate(dict(without_gemini_outputs), session_state)

            with_gemini_outputs = dict(without_gemini_outputs)
            gemini_packet = self._gemini_module_packet(gemini_reasoning)
            if gemini_packet is None:
                gemini_packet = self._gemini_module_packet({
                    "enabled": False,
                    "decision": "FALLBACK_TO_RULES",
                    "confidence": 0.0,
                    "reasoning": "A/B Gemini arm logged; Gemini unavailable or disabled",
                    "model": "none",
                    "tokens_estimated": 0,
                })
            if gemini_packet is not None:
                with_gemini_outputs["GEMINI"] = gemini_packet
            version_a = self.aggregator.aggregate(with_gemini_outputs, session_state)

            return {
                "enabled": True,
                "version_A_with_gemini": self._ab_signal_summary(version_a, gemini_enabled=True),
                "version_B_without_gemini": self._ab_signal_summary(version_b, gemini_enabled=False),
                "comparison_rule": "Keep Gemini only if version_A accuracy beats version_B by more than 5 percentage points.",
            }
        except Exception as exc:
            self.logger.warning("A/B test logging failed safely: %s", exc)
            return {"enabled": True, "error": str(exc)}

    @staticmethod
    def _ab_signal_summary(signal: Mapping[str, Any], *, gemini_enabled: bool) -> dict:
        """Return compact signal fields for A/B efficacy tracking."""
        return {
            "gemini_enabled": gemini_enabled,
            "direction_bias": signal.get("direction_bias"),
            "confidence": signal.get("confidence"),
            "composite_score": signal.get("composite_score"),
            "module_vector": signal.get("module_vector", {}),
        }

    def _build_parallel_ab_test_result(
        self,
        *,
        module_outputs: Mapping[str, Any],
        session_state: str,
        gemini_reasoning: Mapping[str, Any] | None,
    ) -> dict:
        """Build fair same-tick baseline and Gemini signal packets."""
        if not self.ab_test_mode:
            return {
                "enabled": False,
                "baseline_direction": None,
                "baseline_confidence": None,
                "baseline_score": None,
                "gemini_direction": None,
                "gemini_confidence": None,
                "gemini_score": None,
                "both_correct": None,
                "baseline_only_correct": None,
                "gemini_only_correct": None,
            }
        try:
            core_modules = {"REGIME", "VIX_REGIME", "OPTIONS_FLOW", "PCR", "EXPIRY_CYCLE", "GLOBAL"}
            baseline_outputs = {
                module_id: output
                for module_id, output in module_outputs.items()
                if str(module_id).upper() in core_modules
            }
            baseline_signal = self.aggregator.aggregate(dict(baseline_outputs), session_state)

            gemini_outputs = dict(baseline_outputs)
            gemini_packet = self._gemini_module_packet(gemini_reasoning)
            if gemini_packet is not None:
                gemini_outputs["GEMINI"] = gemini_packet
            gemini_signal = self.aggregator.aggregate(gemini_outputs, session_state)

            result = {
                "enabled": True,
                "baseline_direction": baseline_signal.get("direction_bias"),
                "baseline_confidence": baseline_signal.get("confidence"),
                "baseline_score": baseline_signal.get("composite_score"),
                "gemini_direction": gemini_signal.get("direction_bias"),
                "gemini_confidence": gemini_signal.get("confidence"),
                "gemini_score": gemini_signal.get("composite_score"),
                "both_correct": None,
                "baseline_only_correct": None,
                "gemini_only_correct": None,
                "baseline_correct": None,
                "gemini_correct": None,
                "baseline_module_vector": baseline_signal.get("module_vector", {}),
                "gemini_module_vector": gemini_signal.get("module_vector", {}),
            }
            self.logger.info("Parallel A/B signal: %s", result)
            return result
        except Exception as exc:
            self.logger.warning("Parallel A/B logging failed safely: %s", exc)
            return {
                "enabled": True,
                "error": str(exc),
                "baseline_direction": None,
                "baseline_confidence": None,
                "baseline_score": None,
                "gemini_direction": None,
                "gemini_confidence": None,
                "gemini_score": None,
                "both_correct": None,
                "baseline_only_correct": None,
                "gemini_only_correct": None,
            }

    def _time_in_trade_minutes(self, signal: Mapping[str, Any], market_data: Mapping[str, Any]) -> int:
        """Calculate elapsed minutes from trade entry timestamp or explicit input."""
        explicit = self._to_float(market_data.get("time_in_trade_minutes"))
        if explicit is not None:
            return max(0, int(explicit))
        entry = self._parse_dt(signal.get("trade_entry_time") or market_data.get("trade_entry_time"))
        now_dt = self._parse_dt(market_data.get("timestamp")) or datetime.now()
        if entry is None:
            return 0
        return max(0, int((now_dt - entry).total_seconds() // 60))

    def _optional_news_aggregator(self) -> Any | None:
        """Initialize news only when explicitly enabled."""
        try:
            from grey_news_aggregator import GreyNewsAggregator

            return GreyNewsAggregator(dummy_mode=self.dummy_mode, logger=self.logger)
        except Exception as exc:
            self.logger.warning("News aggregator initialization failed safely: %s", exc)
            return None

    def _optional_sentiment_engine(self) -> Any | None:
        """Initialize sentiment only when explicitly enabled."""
        try:
            from grey_sentiment_engine import GreySentimentEngine

            return GreySentimentEngine(dummy_mode=self.dummy_mode, logger=self.logger)
        except Exception as exc:
            self.logger.warning("Sentiment initialization failed safely: %s", exc)
            return None

    @staticmethod
    def _sanitize_unavailable_module_caps(module_outputs: Mapping[str, Any]) -> dict:
        """Keep missing support modules from zeroing the whole enhanced signal."""
        cleaned = {}
        for module_id, output in (module_outputs or {}).items():
            if not isinstance(output, Mapping):
                cleaned[module_id] = output
                continue
            packet = dict(output)
            status = str(packet.get("status") or "").upper()
            if status in {"INSUFFICIENT_DATA", "UNAVAILABLE"}:
                packet.pop("recommended_confidence_cap", None)
                flags = list(packet.get("caution_flags", []))
                flags.append(f"{str(module_id).upper()}_{status}")
                packet["caution_flags"] = flags
            cleaned[module_id] = packet
        return cleaned

    @staticmethod
    def _news_packet(news_items: list[dict]) -> dict | None:
        """Convert collected news into an aggregator packet when news is enabled."""
        if not news_items:
            return None
        avg_relevance = sum(float(item.get("relevance_score", 0.0)) for item in news_items) / len(news_items)
        confidence = min(0.70, 0.20 + avg_relevance * 0.70)
        return {
            "module_id": "NEWS",
            "score": 0.0,
            "direction": "NEUTRAL",
            "confidence": round(confidence, 3),
            "status": "ACTIVE",
            "top_driver": news_items[0].get("title", "relevant news collected"),
            "raw_components": {
                "count": len(news_items),
                "average_relevance": round(avg_relevance, 3),
            },
        }

    def _append_journal(self, result: Mapping[str, Any]) -> None:
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": result.get("timestamp"),
                "symbol": result.get("symbol"),
                "session_state": result.get("session_state"),
                "dummy_mode": result.get("dummy_mode"),
                "enhanced_signal": result.get("enhanced_signal"),
                "sentiment": result.get("sentiment"),
                "reasoning": result.get("reasoning"),
                "claude_reasoning": result.get("claude_reasoning"),
                "gemini_reasoning": result.get("gemini_reasoning"),
                "gemini_vs_claude": result.get("gemini_vs_claude"),
                "options_flow": result.get("options_flow"),
                "microstructure": result.get("microstructure"),
                "risk_decision": result.get("enhanced_signal", {}).get("risk_decision"),
                "ab_test": result.get("ab_test"),
                "parallel_ab_test": result.get("parallel_ab_test"),
                "baseline_direction": result.get("baseline_direction"),
                "baseline_confidence": result.get("baseline_confidence"),
                "baseline_score": result.get("baseline_score"),
                "gemini_direction": result.get("gemini_direction"),
                "gemini_confidence": result.get("gemini_confidence"),
                "gemini_score": result.get("gemini_score"),
                "both_correct": result.get("both_correct"),
                "baseline_only_correct": result.get("baseline_only_correct"),
                "gemini_only_correct": result.get("gemini_only_correct"),
            }
            with self.journal_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")
        except Exception as exc:
            self.logger.warning("Enhanced signal journal write failed safely: %s", exc)

    def _print_console_summary(self, result: Mapping[str, Any]) -> None:
        signal = result.get("enhanced_signal", {})
        caution = signal.get("caution_state", {})
        print("")
        print("GREY 2.0 Enhanced Signal")
        print(f"Time: {result.get('timestamp')}")
        print(f"Symbol: {result.get('symbol')}")
        print(f"Session: {result.get('session_state')}")
        print(f"Direction: {signal.get('direction_bias')}")
        print(f"Composite score: {signal.get('composite_score')}")
        print(f"Confidence: {signal.get('confidence')}")
        print(f"Caution: {caution.get('level', 'UNKNOWN') if isinstance(caution, Mapping) else 'UNKNOWN'}")
        print(f"Reasoning: {signal.get('reasoning_summary', '')[:240]}")
        gemini = result.get("gemini_reasoning")
        comparison = result.get("gemini_vs_claude")
        if isinstance(gemini, Mapping):
            print(
                "Gemini reasoning: "
                f"{gemini.get('decision')} confidence={gemini.get('confidence')}"
            )
            print(f"Gemini insight: {str(gemini.get('reasoning', ''))[:180]}")
        if isinstance(comparison, Mapping):
            print(f"Reasoning agreement: {comparison.get('remark')}")

    @staticmethod
    def _dummy_market_data(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "price": 23540.0,
            "price_change_from_open": 78.0,
            "atr_14": 62.0,
            "volatility_ratio": 0.96,
            "put_wall_weight": 8_500_000,
            "call_wall_weight": 1_200_000,
            "ivp": 0.45,
            "is_expiry": False,
            "bid_price": 23539.5,
            "ask_price": 23540.5,
            "bid_quantity": 18_000,
            "ask_quantity": 11_000,
            "buy_volume": 145_000,
            "sell_volume": 96_000,
            "volume": 450_000,
            "spread_pct": 0.004,
            "implied_volatility": 0.14,
            "india_vix": 14.2,
            "india_vix_prev_close": 14.0,
            "india_vix_5day_avg": 14.5,
            "pcr_oi": 1.25,
            "pcr_volume": 1.12,
            "pcr_5day_avg": 1.16,
            "days_to_expiry": 3,
            "current_weekday": 1,
            "is_monthly_expiry": False,
            "call_oi_change_pct": -12.0,
            "put_oi_change_pct": 14.0,
            "atm_call_oi_change": -8.0,
            "atm_put_oi_change": 16.0,
            "gift_nifty_return_pct": 0.004,
            "asia_return_pct": 0.002,
            "us_futures_return_pct": 0.001,
            "india_vix_change_pct": 0.014,
            "usdinr_change_pct": -0.001,
            "brent_change_pct": -0.002,
            "liquidity_change_pct": -0.010,
            "rate_change_bps": -1.0,
            "banking_return_pct": 0.006,
            "it_return_pct": 0.002,
            "energy_return_pct": 0.001,
            "defensive_return_pct": 0.0005,
            "sector_breadth": 0.68,
            "previous_price": 23480.0,
            "liquidity_score": 0.80,
            "bid": 23539.5,
            "ask": 23540.5,
            "trades": [{"side": "BUY", "quantity": 7_000, "price": 23540.0}],
        }

    @staticmethod
    def _is_market_hours(dt: datetime) -> bool:
        return dt_time(9, 15) <= dt.time() <= dt_time(15, 30)

    @staticmethod
    def _json_safe(value: Any) -> Any:
        try:
            json.dumps(value, default=str)
            return value
        except TypeError:
            return str(value)

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely parse a float."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        """Clamp numeric value between lower and upper."""
        return max(lower, min(upper, float(value)))

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        """Read a boolean environment variable with a safe default."""
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        """Parse common ISO timestamp values safely."""
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if value is None:
            return None
        try:
            text = str(value).strip()
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            return datetime.fromisoformat(text).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _memory_usage_text() -> str:
        """Return process memory percentage when psutil is available."""
        try:
            import psutil

            return f"{psutil.virtual_memory().percent:.0f}%"
        except Exception:
            return "unknown"

    @staticmethod
    def _configure_logger() -> logging.Logger:
        Path("logs").mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("grey2")
        if logger.handlers:
            return logger
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        file_handler = logging.FileHandler("logs/grey2_enhanced.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        return logger


def main() -> None:
    engine = GreyEnhancedPhase1Engine()
    loop = os.getenv("GREY2_LOOP", "False").strip().lower() == "true"
    if loop:
        engine.run_loop(symbol=os.getenv("GREY2_SYMBOL", "NIFTY"))
        return
    result = engine.run_once(symbol=os.getenv("GREY2_SYMBOL", "NIFTY"))
    engine._print_console_summary(result)
    print("")
    print("GREY 2.0 one-cycle run complete.")
    print("Set GREY2_LOOP=True to run every 5 minutes during market hours.")


if __name__ == "__main__":
    main()


__all__ = ["GreyEnhancedPhase1Engine"]
