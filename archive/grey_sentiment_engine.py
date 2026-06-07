"""
Sentiment aggregation for GREY 2.0.

This module combines news and optional social inputs into a simple, bounded
operator-friendly sentiment view. It accepts supplied Twitter, Reddit, and
StockTwits text but does not scrape private APIs on its own.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Iterable, Mapping


class GreySentimentEngine:
    """Aggregate news and social sentiment with contradiction detection."""

    POSITIVE_TERMS = {
        "bullish": 1.0,
        "strong": 0.7,
        "breakout": 0.8,
        "supportive": 0.7,
        "gain": 0.5,
        "gains": 0.5,
        "advance": 0.6,
        "rally": 0.8,
        "firm": 0.5,
        "lead": 0.4,
        "contained": 0.3,
        "improves": 0.5,
        "positive": 0.6,
    }
    NEGATIVE_TERMS = {
        "bearish": -1.0,
        "weak": -0.7,
        "breakdown": -0.8,
        "risk": -0.5,
        "caution": -0.4,
        "fall": -0.6,
        "falls": -0.6,
        "drop": -0.6,
        "selloff": -0.9,
        "volatile": -0.5,
        "inflation": -0.3,
        "crude": -0.2,
        "pressure": -0.5,
        "negative": -0.6,
    }
    SOURCE_WEIGHTS = {
        "news": 1.00,
        "twitter": 0.60,
        "reddit": 0.45,
        "stocktwits": 0.55,
    }

    def __init__(
        self,
        *,
        cache_path: str | Path | None = None,
        dummy_mode: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.cache_path = Path(cache_path or "data/live_cache/sentiment_state.json")
        self.dummy_mode = dummy_mode
        self.logger = logger or logging.getLogger(__name__)

    def analyze(
        self,
        *,
        news_items: list[dict] | None = None,
        social_items: list[dict] | None = None,
        source_sentiments: Mapping[str, float] | None = None,
    ) -> dict:
        """Return consensus, contradictions, surprise, and conviction."""
        news_items = news_items or ([] if not self.dummy_mode else self._dummy_news())
        social_items = social_items or ([] if not self.dummy_mode else self._dummy_social())
        explicit = dict(source_sentiments or {})

        source_scores = {}
        if news_items:
            source_scores["news"] = self._average(
                self._score_text(f"{item.get('title', '')} {item.get('summary', '')}")
                for item in news_items
            )

        grouped_social: dict[str, list[str]] = {"twitter": [], "reddit": [], "stocktwits": []}
        for item in social_items:
            if not isinstance(item, Mapping):
                continue
            source = str(item.get("source", "social")).lower()
            if source in grouped_social:
                grouped_social[source].append(str(item.get("text") or item.get("title") or ""))

        for source, texts in grouped_social.items():
            if texts:
                source_scores[source] = self._average(self._score_text(text) for text in texts)

        for source, score in explicit.items():
            source_scores[str(source).lower()] = self._clamp(float(score), -1.0, 1.0)

        consensus = self._weighted_consensus(source_scores)
        contradictions = self._contradictions(source_scores, consensus)
        previous = self._read_previous()
        surprise = abs(consensus - float(previous.get("consensus", 0.0)))
        conviction = self._conviction(source_scores, consensus, contradictions)
        packet = {
            "consensus": round(consensus, 3),
            "contradictions": contradictions,
            "surprise": round(min(1.0, surprise), 3),
            "conviction": round(conviction, 3),
            "source_scores": {key: round(value, 3) for key, value in source_scores.items()},
            "sample_size": len(news_items) + len(social_items),
            "module_id": "SENTIMENT",
            "score": round(consensus * 10.0, 3),
            "direction": self._direction(consensus),
            "confidence": round(conviction, 3),
            "status": "ACTIVE" if source_scores else "INSUFFICIENT_DATA",
            "top_driver": self._top_driver(source_scores, consensus),
        }
        self._write_previous(packet)
        return packet

    def _score_text(self, text: str) -> float:
        lowered = str(text or "").lower()
        score = 0.0
        hits = 0
        for term, weight in {**self.POSITIVE_TERMS, **self.NEGATIVE_TERMS}.items():
            if term in lowered:
                score += weight
                hits += 1
        if hits == 0:
            return 0.0
        return self._clamp(math.tanh(score / 2.5), -1.0, 1.0)

    def _weighted_consensus(self, source_scores: Mapping[str, float]) -> float:
        weighted = 0.0
        total = 0.0
        for source, score in source_scores.items():
            weight = self.SOURCE_WEIGHTS.get(source, 0.50)
            weighted += score * weight
            total += weight
        return 0.0 if total == 0 else self._clamp(weighted / total, -1.0, 1.0)

    def _contradictions(self, source_scores: Mapping[str, float], consensus: float) -> list[dict]:
        contradictions = []
        for source, score in source_scores.items():
            opposite = (score >= 0.20 and consensus <= -0.15) or (score <= -0.20 and consensus >= 0.15)
            gap = abs(score - consensus) >= 0.55
            if opposite or gap:
                contradictions.append({
                    "source": source,
                    "score": round(score, 3),
                    "reason": "opposes consensus" if opposite else "large score gap",
                })
        return contradictions

    def _conviction(
        self,
        source_scores: Mapping[str, float],
        consensus: float,
        contradictions: list[dict],
    ) -> float:
        if not source_scores:
            return 0.0
        avg_magnitude = sum(abs(score) for score in source_scores.values()) / len(source_scores)
        agreement = max(0.0, 1.0 - (len(contradictions) / max(1, len(source_scores))))
        sample_boost = min(1.0, len(source_scores) / 3.0)
        return self._clamp((0.35 + avg_magnitude * 0.65) * agreement * sample_boost, 0.0, 1.0)

    def _read_previous(self) -> dict:
        try:
            if self.cache_path.exists():
                with self.cache_path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
        except Exception as exc:
            self.logger.warning("Sentiment cache read failed safely: %s", exc)
        return {}

    def _write_previous(self, packet: Mapping[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("w", encoding="utf-8") as handle:
                json.dump({**dict(packet), "updated_at": time.time()}, handle, indent=2, sort_keys=True)
        except Exception as exc:
            self.logger.warning("Sentiment cache write failed safely: %s", exc)

    @staticmethod
    def _average(values: Iterable[float]) -> float:
        items = list(values)
        return 0.0 if not items else sum(items) / len(items)

    @staticmethod
    def _direction(score: float) -> str:
        if score >= 0.20:
            return "BULL"
        if score <= -0.20:
            return "BEAR"
        return "NEUTRAL"

    @staticmethod
    def _top_driver(source_scores: Mapping[str, float], consensus: float) -> str:
        if not source_scores:
            return "no sentiment sources available"
        source = max(source_scores, key=lambda key: abs(source_scores[key]))
        return f"{source} sentiment {source_scores[source]:.2f}; consensus {consensus:.2f}"

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))

    @staticmethod
    def _dummy_news() -> list[dict]:
        return [{"title": "NIFTY gains as banks lead", "summary": "Market breadth remains strong."}]

    @staticmethod
    def _dummy_social() -> list[dict]:
        return [
            {"source": "twitter", "text": "NIFTY looks bullish but resistance is near"},
            {"source": "stocktwits", "text": "Banks strong, volatility contained"},
        ]


__all__ = ["GreySentimentEngine"]
