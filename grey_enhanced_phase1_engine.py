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
from grey_news_aggregator import GreyNewsAggregator
from grey_options_flow_monitor import GreyOptionsFlowMonitor
from grey_phase1_engine import GreyPhase1Engine
from grey_reasoning_engine import GreyReasoningEngine
from grey_sentiment_engine import GreySentimentEngine
from grey_signal_aggregator import GreySignalAggregator

try:
    from grey_live_data_provider import GreyLiveDataProvider
except Exception:
    GreyLiveDataProvider = None


class GreyEnhancedPhase1Engine:
    """Combine Phase 1 technical GREY with news, sentiment, AI, flow, and depth."""

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
        self.news = GreyNewsAggregator(dummy_mode=self.dummy_mode, logger=self.logger)
        self.sentiment = GreySentimentEngine(dummy_mode=self.dummy_mode, logger=self.logger)
        self.reasoning = GreyReasoningEngine(dummy_mode=self.dummy_mode, logger=self.logger)
        self.use_gemini = os.getenv("GREY_GEMINI_ENABLED", "False").strip().lower() == "true"
        self.gemini_engine = (
            GreyGeminiReasoningEngine(logger=self.logger)
            if self.use_gemini
            else None
        )
        self._gemini_cycle_count = 0
        self.options_flow = GreyOptionsFlowMonitor(dummy_mode=self.dummy_mode, logger=self.logger)
        self.microstructure = GreyMicrostructureAnalyzer(dummy_mode=self.dummy_mode, logger=self.logger)
        self.aggregator = GreySignalAggregator(config=self.ENHANCED_AGGREGATOR_CONFIG)

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

        collected_news = news_items if news_items is not None else self.news.collect(max_items=30)
        sentiment = self.sentiment.analyze(news_items=collected_news, social_items=social_items)
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
            "news": collected_news[:10],
            "sentiment": sentiment,
            "options_flow": options_flow,
            "microstructure": microstructure,
        }
        reasoning = self.reasoning.analyze(pre_reasoning_context)
        gemini_context = self._build_gemini_context(
            market_data=data,
            news_items=collected_news,
            sentiment=sentiment,
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
            "NEWS": news_packet,
            "SENTIMENT": sentiment,
            "OPTIONS_FLOW": options_flow,
            "MICROSTRUCTURE": microstructure,
            "REASONING": reasoning,
        }
        if gemini_packet is not None:
            module_outputs["GEMINI"] = gemini_packet
        enhanced_signal = self.aggregator.aggregate(module_outputs, session_state)
        enhanced_signal["reasoning_summary"] = reasoning.get("reasoning_summary", "")
        enhanced_signal["news_count"] = len(collected_news)
        enhanced_signal["gemini_reasoning"] = gemini_reasoning
        enhanced_signal["claude_reasoning"] = reasoning
        enhanced_signal["gemini_vs_claude"] = reasoning_reconciliation

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
        }
        self._append_journal(result)
        self.logger.info(
            "GREY2 cycle complete symbol=%s score=%s direction=%s confidence=%s",
            symbol,
            enhanced_signal.get("composite_score"),
            enhanced_signal.get("direction_bias"),
            enhanced_signal.get("confidence"),
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
        news_items: list[dict],
        sentiment: Mapping[str, Any],
        options_flow: Mapping[str, Any],
        microstructure: Mapping[str, Any],
        technical_composite: Mapping[str, Any],
    ) -> dict:
        """Flatten GREY context into Gemini's operator-friendly prompt fields."""
        source_scores = sentiment.get("source_scores", {}) if isinstance(sentiment, Mapping) else {}
        alerts = options_flow.get("alerts", []) if isinstance(options_flow, Mapping) else []
        return {
            "price": market_data.get("price"),
            "atr": market_data.get("atr_14") or market_data.get("atr"),
            "range": market_data.get("range") or market_data.get("intraday_range"),
            "latest_news": "; ".join(str(item.get("title", "")) for item in news_items[:3]) or "not provided",
            "twitter_sentiment": source_scores.get("twitter"),
            "surprise": sentiment.get("surprise") if isinstance(sentiment, Mapping) else None,
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
                else:
                    print(f"{now:%H:%M:%S} outside market hours; sleeping.")
                time.sleep(interval)
            except KeyboardInterrupt:
                print("GREY 2.0 stopped by user.")
                break
            except Exception as exc:
                self.logger.exception("GREY2 loop failed safely: %s", exc)
                print(f"GREY 2.0 cycle skipped safely: {exc}")
                time.sleep(interval)

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
    def _news_packet(news_items: list[dict]) -> dict:
        if not news_items:
            return {
                "module_id": "NEWS",
                "score": 0.0,
                "direction": "NEUTRAL",
                "confidence": 0.0,
                "status": "INSUFFICIENT_DATA",
                "top_driver": "no relevant news collected",
            }
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
        if value is None:
            return None

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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
