"""
Claude-backed reasoning engine for GREY 2.0.

When enabled and configured, this module sends the complete market context to
Claude and asks for structured reasoning. If Claude is disabled or unavailable,
GREY uses a deterministic local fallback so the live loop continues.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class GreyReasoningEngine:
    """Generate structured market reasoning with Claude or local fallback."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        enabled: bool | None = None,
        timeout_seconds: int = 20,
        cache_path: str | Path | None = None,
        dummy_mode: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("GREY_CLAUDE_MODEL", "claude-3-5-sonnet-latest")
        env_enabled = os.getenv("GREY_REASONING_ENABLED", "False").strip().lower() == "true"
        self.enabled = env_enabled if enabled is None else enabled
        self.timeout_seconds = timeout_seconds
        self.cache_path = Path(cache_path or "data/live_cache/reasoning_last.json")
        self.dummy_mode = dummy_mode
        self.logger = logger or logging.getLogger(__name__)

    def analyze(self, market_context: Mapping[str, Any]) -> dict:
        """Return structured reasoning and a GREY-compatible score packet."""
        if self.dummy_mode or not self.enabled or not self.api_key:
            return self._local_reasoning(market_context, reason="local fallback")

        try:
            prompt = self._build_prompt(market_context)
            response = self._call_claude(prompt)
            decision = self._parse_decision(response)
            packet = self._packet_from_decision(decision, response, "CLAUDE")
            self._write_cache(packet)
            return packet
        except Exception as exc:
            self.logger.warning("Claude reasoning failed safely: %s", exc)
            fallback = self._local_reasoning(market_context, reason=f"Claude unavailable: {exc}")
            self._write_cache(fallback)
            return fallback

    def _call_claude(self, prompt: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "max_tokens": 900,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        request = urllib.request.Request(
            self.API_URL,
            data=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Claude HTTP {exc.code}: {body[:300]}") from exc

        content = data.get("content", [])
        text_parts = []
        for block in content if isinstance(content, list) else []:
            if isinstance(block, Mapping) and block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
        return "\n".join(text_parts).strip()

    def _build_prompt(self, market_context: Mapping[str, Any]) -> str:
        safe_context = json.dumps(market_context, default=str, indent=2, sort_keys=True)[:20_000]
        return (
            "You are reviewing NSE/NIFTY market intelligence for GREY. "
            "GREY is not a broker and must not produce trade orders.\n\n"
            "Question: What's your analysis? What's not obvious? What are the risks?\n\n"
            "Return only JSON with these keys: decision, direction, confidence, "
            "reasoning_summary, not_obvious, risks, caution_flags.\n"
            "Allowed direction values: BULL, BEAR, NEUTRAL.\n\n"
            f"Market context:\n{safe_context}"
        )

    def _parse_decision(self, response_text: str) -> dict:
        if not response_text:
            return {}
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", response_text, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return {"reasoning_summary": response_text[:700], "direction": "NEUTRAL", "confidence": 0.20}

    def _packet_from_decision(self, decision: Mapping[str, Any], raw_text: str, source: str) -> dict:
        direction = str(decision.get("direction") or "NEUTRAL").upper()
        if direction not in {"BULL", "BEAR", "NEUTRAL"}:
            direction = "NEUTRAL"
        confidence = self._clamp(float(decision.get("confidence") or 0.25), 0.0, 1.0)
        score = {"BULL": 10.0, "BEAR": -10.0, "NEUTRAL": 0.0}[direction] * confidence
        summary = str(decision.get("reasoning_summary") or decision.get("decision") or "No reasoning summary.")
        return {
            "module_id": "REASONING",
            "score": round(score, 3),
            "direction": direction,
            "confidence": round(confidence, 3),
            "status": "ACTIVE",
            "reasoning_source": source,
            "reasoning_summary": summary[:900],
            "not_obvious": decision.get("not_obvious", []),
            "risks": decision.get("risks", []),
            "caution_flags": decision.get("caution_flags", []),
            "top_driver": summary[:160],
            "raw_text": raw_text[:2_000],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _local_reasoning(self, market_context: Mapping[str, Any], reason: str) -> dict:
        composite = market_context.get("technical_composite", {})
        sentiment = market_context.get("sentiment", {})
        flow = market_context.get("options_flow", {})
        micro = market_context.get("microstructure", {})

        scores = [
            self._packet_score(composite),
            self._packet_score(sentiment),
            self._packet_score(flow),
            self._packet_score(micro),
        ]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        direction = "BULL" if avg_score >= 0.18 else "BEAR" if avg_score <= -0.18 else "NEUTRAL"
        confidence = min(0.70, 0.25 + abs(avg_score) * 0.65)
        summary = (
            f"Local GREY reasoning used because {reason}. "
            f"Technical, sentiment, flow, and microstructure average score is {avg_score:.2f}; "
            f"bias is {direction} with conservative confidence."
        )
        decision = {
            "direction": direction,
            "confidence": confidence,
            "reasoning_summary": summary,
            "not_obvious": ["Local fallback avoids blocking the live loop when Claude is unavailable."],
            "risks": ["Review source modules before trusting a single composite reading."],
            "caution_flags": [] if direction != "NEUTRAL" else ["LOW_CONVICTION_REASONING"],
        }
        return self._packet_from_decision(decision, summary, "LOCAL_FALLBACK")

    @staticmethod
    def _packet_score(packet: Any) -> float:
        if not isinstance(packet, Mapping):
            return 0.0
        if packet.get("score") is not None:
            try:
                return max(-1.0, min(1.0, float(packet["score"]) / 10.0))
            except (TypeError, ValueError):
                return 0.0
        if packet.get("composite_score") is not None:
            try:
                return max(-1.0, min(1.0, float(packet["composite_score"])))
            except (TypeError, ValueError):
                return 0.0
        direction = str(packet.get("direction") or packet.get("direction_bias") or "").upper()
        return 0.5 if direction == "BULL" else -0.5 if direction == "BEAR" else 0.0

    def _write_cache(self, packet: Mapping[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("w", encoding="utf-8") as handle:
                json.dump(dict(packet), handle, indent=2, sort_keys=True, default=str)
        except Exception as exc:
            self.logger.warning("Reasoning cache write failed safely: %s", exc)

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))


__all__ = ["GreyReasoningEngine"]
