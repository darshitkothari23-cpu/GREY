"""
Gemini reasoning engine for GREY 2.0.

This module adds Google Gemini as an optional market-reasoning layer. It is
safe by default: if the API key or dependency is missing, GREY returns a
structured fallback instead of crashing the live loop.

Example:
    engine = GreyGeminiReasoningEngine()
    result = engine.analyze_market({"price": 24350, "pcr": 1.2})
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


class GreyGeminiReasoningEngine:
    """Call Gemini for NSE options reasoning, with graceful fallback."""

    MODEL_NAME = "gemini-2.0-flash"
    VALID_DECISIONS = {
        "STRONG_BULL",
        "MILD_BULL",
        "MILD_BEAR",
        "STRONG_BEAR",
        "WAIT_FOR_CLARITY",
        "NEUTRAL",
        "NEUTRAL_SETUP",
        "FALLBACK_TO_RULES",
    }
    SYSTEM_INSTRUCTION = (
        "You are an expert NSE derivatives trader analyzing NIFTY/BANKNIFTY options.\n\n"
        "Analyze market context holistically:\n"
        "- Detect contradictions between signals (retail vs smart money)\n"
        "- Identify what market is missing or underpricing\n"
        "- Think through scenarios and risks\n"
        "- Suggest specific strikes and position management\n\n"
        "Return only JSON with this exact shape:\n"
        '{"decision":"STRONG_BULL|MILD_BULL|NEUTRAL|MILD_BEAR|STRONG_BEAR",'
        '"confidence":0.0,"reasoning":"text"}\n'
        "Be concise but thorough inside reasoning. Consider: What would a professional trader do right now?"
    )

    def __init__(
        self,
        *,
        api_key: str | None = None,
        enabled: bool | None = None,
        timeout_seconds: int | None = None,
        model_name: str | None = None,
        log_path: str | Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize Gemini configuration, history, and safe enabled state."""
        if load_dotenv is not None:
            load_dotenv()

        self.model_name = model_name or self.MODEL_NAME
        self.api_key = api_key if api_key is not None else os.getenv("GOOGLE_GEMINI_API_KEY", "")
        env_enabled = os.getenv("GREY_GEMINI_ENABLED", "False").strip().lower() == "true"
        self.requested_enabled = env_enabled if enabled is None else bool(enabled)
        self.timeout_seconds = int(timeout_seconds or os.getenv("GREY_GEMINI_TIMEOUT", "5"))
        self.frequency = int(os.getenv("GREY_GEMINI_FREQUENCY", "1") or "1")
        self.min_confidence = float(os.getenv("GREY_GEMINI_MIN_CONFIDENCE", "0.55") or "0.55")
        self.log_path = Path(log_path or "logs/gemini_reasoning.jsonl")
        self.logger = logger or logging.getLogger(__name__)
        self.conversation_history: list[dict] = []
        self.enabled = bool(self.requested_enabled and self.api_key)
        self.model = None

        if self.enabled:
            try:
                genai = self._load_gemini_library()
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(
                    self.model_name,
                    system_instruction=self.SYSTEM_INSTRUCTION,
                )
            except Exception as exc:
                self.enabled = False
                self.logger.warning("Gemini initialization failed safely: %s", exc)

    def analyze_market(self, market_context: dict) -> dict:
        """Analyze full market context and return a structured Gemini packet."""
        context = market_context or {}
        if not self.enabled or self.model is None:
            return self._fallback_response("Gemini API unavailable or disabled")

        prompt = self._format_prompt(context)
        self._add_history("user", prompt)

        try:
            response_text = self._generate_with_timeout(prompt)
            self._add_history("model", response_text)
            self._trim_conversation()
            structured = self._parse_structured_response(response_text)

            tokens_estimated = self._estimate_tokens(prompt) + self._estimate_tokens(response_text)
            packet = {
                "enabled": True,
                "reasoning": structured["reasoning"],
                "decision": structured["decision"],
                "confidence": structured["confidence"],
                "model": self.model_name,
                "tokens_estimated": tokens_estimated,
                "timestamp": datetime.now().isoformat(),
            }
            self._log_query(packet, prompt)
            return packet
        except TimeoutError:
            self.logger.warning("Gemini request timed out after %s seconds", self.timeout_seconds)
            return self._fallback_response("Gemini API timeout")
        except Exception as exc:
            self.logger.warning("Gemini reasoning failed safely: %s", exc)
            return self._fallback_response(f"Gemini API failed: {exc}")

    def _format_prompt(self, market_context: dict) -> str:
        """Format market data into a clear analysis request for Gemini."""
        data = market_context or {}
        return (
            "Analyze this NSE market context for GREY. GREY is a research and review system, "
            "not an order-placement engine.\n\n"
            "PRICE DATA\n"
            f"- Spot price: {self._pick(data, 'price', 'spot', 'current_price')}\n"
            f"- ATR: {self._pick(data, 'atr', 'atr_14')}\n"
            f"- Range: {self._pick(data, 'range', 'intraday_range')}\n\n"
            "NEWS & SENTIMENT\n"
            f"- Latest news: {self._pick(data, 'latest_news', 'news')}\n"
            f"- Twitter sentiment: {self._pick(data, 'twitter_sentiment')}\n"
            f"- Surprise: {self._pick(data, 'surprise')}\n\n"
            "OPTIONS POSITIONING\n"
            f"- Put wall: {self._pick(data, 'put_wall', 'put_wall_weight')}\n"
            f"- Call wall: {self._pick(data, 'call_wall', 'call_wall_weight')}\n"
            f"- PCR: {self._pick(data, 'pcr', 'pcr_oi')}\n"
            f"- Unusual OI: {self._pick(data, 'unusual_oi', 'unusual_options_activity')}\n\n"
            "MACRO CONTEXT\n"
            f"- GIFT Nifty: {self._pick(data, 'gift_nifty', 'gift_nifty_return_pct')}\n"
            f"- US futures: {self._pick(data, 'us_futures', 'us_futures_return_pct')}\n"
            f"- VIX: {self._pick(data, 'vix', 'india_vix')}\n"
            f"- FII flow: {self._pick(data, 'fii_flow', 'fii_flow_cr')}\n\n"
            "MICROSTRUCTURE\n"
            f"- Bid-ask spread: {self._pick(data, 'spread', 'spread_pct')}\n"
            f"- Volume profile: {self._pick(data, 'volume_profile')}\n"
            f"- Aggressiveness: {self._pick(data, 'aggressiveness')}\n\n"
            "YOUR ANALYSIS:\n"
            "Return only JSON using this schema:\n"
            '{"decision":"STRONG_BULL|MILD_BULL|NEUTRAL|MILD_BEAR|STRONG_BEAR",'
            '"confidence":0.0,"reasoning":"short explanation"}'
        )

    def _extract_decision(self, reasoning: str) -> str:
        """Extract a decision from structured JSON, with neutral fallback."""
        return self._parse_structured_response(reasoning)["decision"]

    def _extract_confidence(self, reasoning: str) -> float:
        """Extract confidence from structured JSON, with neutral fallback."""
        return self._parse_structured_response(reasoning)["confidence"]

    def _parse_structured_response(self, response_text: str) -> dict:
        """Parse Gemini JSON response into decision, confidence, and reasoning."""
        text = str(response_text or "").strip()
        parsed: Mapping[str, Any] = {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    parsed = {}

        decision = str(parsed.get("decision", "NEUTRAL")).upper() if isinstance(parsed, Mapping) else "NEUTRAL"
        if decision not in {"STRONG_BULL", "MILD_BULL", "NEUTRAL", "MILD_BEAR", "STRONG_BEAR"}:
            decision = "NEUTRAL"

        confidence = self._clamp_unit(parsed.get("confidence", 0.0) if isinstance(parsed, Mapping) else 0.0)
        reasoning = str(parsed.get("reasoning", text) if isinstance(parsed, Mapping) else text).strip()
        if not reasoning:
            reasoning = "Gemini returned no reasoning text."
        return {"decision": decision, "confidence": confidence, "reasoning": reasoning}

    def _fallback_response(self, reason: str = "Gemini API unavailable or disabled") -> dict:
        """Return a structured response when Gemini cannot be used."""
        packet = {
            "enabled": False,
            "reasoning": reason,
            "decision": "FALLBACK_TO_RULES",
            "confidence": 0.0,
            "model": "none",
            "tokens_estimated": 0,
            "timestamp": datetime.now().isoformat(),
        }
        self._log_query(packet, "")
        return packet

    def _generate_with_timeout(self, prompt: str) -> str:
        """Run Gemini with request-level timeout control."""
        return self._generate_content(prompt)

    def _generate_content(self, prompt: str) -> str:
        """Call google-generativeai and extract response text safely."""
        response = self.model.generate_content(
            self._conversation_for_gemini(prompt),
            request_options={"timeout": self.timeout_seconds},
        )
        text = getattr(response, "text", None)
        if text:
            return str(text).strip()

        candidates = getattr(response, "candidates", None) or []
        parts = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    parts.append(str(part_text))
        return "\n".join(parts).strip() or "Gemini returned an empty response."

    @staticmethod
    def _load_gemini_library():
        """Import google-generativeai only when real Gemini mode is requested."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import google.generativeai as genai
        return genai

    def _conversation_for_gemini(self, prompt: str) -> list[dict]:
        """Return recent multi-turn context in Gemini's content format."""
        history = self.conversation_history[-20:]
        if not history or history[-1].get("parts", [""])[0] != prompt:
            history = [*history, {"role": "user", "parts": [prompt]}]
        return history

    def _add_history(self, role: str, text: str) -> None:
        """Append one user/model message to the short conversation memory."""
        self.conversation_history.append({"role": role, "parts": [str(text or "")]})
        self._trim_conversation()

    def _trim_conversation(self) -> None:
        """Keep only the last 10 exchanges to control token usage."""
        self.conversation_history = self.conversation_history[-20:]

    def _log_query(self, packet: Mapping[str, Any], prompt: str) -> None:
        """Log token estimates and daily cost metadata for later review."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            tokens = int(packet.get("tokens_estimated") or 0)
            today = date.today().isoformat()
            estimated_cost = self._estimate_cost(tokens)
            daily_tokens, daily_cost = self._daily_totals(today, tokens, estimated_cost)
            record = {
                "timestamp": packet.get("timestamp"),
                "date": today,
                "enabled": packet.get("enabled"),
                "decision": packet.get("decision"),
                "confidence": packet.get("confidence"),
                "model": packet.get("model"),
                "tokens_estimated": tokens,
                "estimated_cost_usd": estimated_cost,
                "daily_tokens_estimated": daily_tokens,
                "daily_estimated_cost_usd": daily_cost,
                "free_tier_warning": daily_tokens > 1_000_000,
                "free_tier_note": "15 requests/min free-tier friendly when queried every 5 minutes",
                "prompt_chars": len(prompt or ""),
            }
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        except Exception as exc:
            self.logger.warning("Gemini cost log failed safely: %s", exc)

    def _estimate_cost(self, tokens: int) -> float:
        """Return a rough cost placeholder; exact billing depends on Google pricing."""
        if tokens <= 0:
            return 0.0
        return round((tokens / 1_000_000.0) * 0.10, 6)

    def _daily_totals(self, today: str, current_tokens: int, current_cost: float) -> tuple[int, float]:
        """Calculate today's running token and estimated cost totals."""
        total_tokens = current_tokens
        total_cost = current_cost
        try:
            if self.log_path.exists():
                with self.log_path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        record = json.loads(line)
                        if record.get("date") != today:
                            continue
                        total_tokens += int(record.get("tokens_estimated") or 0)
                        total_cost += float(record.get("estimated_cost_usd") or 0.0)
        except Exception as exc:
            self.logger.warning("Gemini daily cost rollup failed safely: %s", exc)
        return total_tokens, round(total_cost, 6)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate tokens for cost tracking without requiring tokenizer packages."""
        if not text:
            return 0
        return max(1, int(len(text) / 4))

    @staticmethod
    def _clamp_unit(value: Any) -> float:
        """Clamp a numeric confidence value into 0.0 to 1.0."""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _pick(data: Mapping[str, Any], *keys: str) -> Any:
        """Pick the first present market-context value for prompt readability."""
        for key in keys:
            if key in data and data.get(key) not in (None, ""):
                return data.get(key)
        return "not provided"


__all__ = ["GreyGeminiReasoningEngine"]
