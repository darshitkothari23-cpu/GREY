"""
Real-time news collection for GREY 2.0.

The aggregator pulls market news and NSE announcements, scores each item for
NIFTY relevance, and returns a timestamped stream suitable for sentiment and
reasoning modules. It is intentionally read-only and never places trades.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


class GreyNewsAggregator:
    """Collect and score market news with cache-backed graceful fallback."""

    DEFAULT_FEEDS = [
        {
            "name": "Bloomberg Markets",
            "url": "https://feeds.bloomberg.com/markets/news.rss",
            "kind": "rss",
        },
        {
            "name": "Reuters Markets",
            "url": "https://www.reutersagency.com/feed/?best-topics=markets&post_type=best",
            "kind": "rss",
        },
        {
            "name": "CNBC Markets",
            "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "kind": "rss",
        },
        {
            "name": "ET Markets",
            "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
            "kind": "rss",
        },
        {
            "name": "NSE Announcements",
            "url": "https://www.nseindia.com/api/corporate-announcements?index=equities",
            "kind": "nse_json",
        },
    ]

    DIRECT_TERMS = {
        "nifty": 0.35,
        "nifty 50": 0.50,
        "nse": 0.28,
        "india": 0.16,
        "indian": 0.16,
        "sensex": 0.18,
        "bank nifty": 0.22,
        "gift nifty": 0.24,
    }
    MACRO_TERMS = {
        "rbi": 0.16,
        "inflation": 0.10,
        "cpi": 0.12,
        "fed": 0.10,
        "crude": 0.08,
        "rupee": 0.10,
        "usd/inr": 0.12,
        "vix": 0.10,
        "fii": 0.10,
        "dii": 0.08,
    }
    SECTOR_TERMS = {
        "bank": 0.10,
        "banks": 0.10,
        "financial": 0.08,
        "it stocks": 0.08,
        "energy": 0.06,
        "reliance": 0.08,
        "hdfc": 0.08,
        "icici": 0.08,
        "infosys": 0.06,
        "tcs": 0.06,
    }

    def __init__(
        self,
        *,
        feeds: list[dict] | None = None,
        cache_path: str | Path | None = None,
        cache_seconds: int | None = None,
        timeout_seconds: int = 8,
        min_relevance: float = 0.20,
        dummy_mode: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.feeds = feeds or self._feeds_from_env() or list(self.DEFAULT_FEEDS)
        self.cache_path = Path(cache_path or "data/live_cache/news_items.json")
        self.cache_seconds = int(cache_seconds or os.getenv("GREY_NEWS_CACHE_SECONDS", "300"))
        self.timeout_seconds = timeout_seconds
        self.min_relevance = min_relevance
        self.dummy_mode = dummy_mode
        self.logger = logger or logging.getLogger(__name__)

    def collect(self, max_items: int = 50, force_refresh: bool = False) -> list[dict]:
        """Return relevant market news, using cache when fresh or feeds fail."""
        cached = self._read_cache()
        if not force_refresh and self._cache_is_fresh(cached):
            return list(cached.get("items", []))[:max_items]

        if self.dummy_mode:
            items = self._dummy_items()
            self._write_cache(items)
            return items[:max_items]

        collected: list[dict] = []
        for feed in self.feeds:
            try:
                raw_items = self._fetch_feed(feed)
                collected.extend(self._score_items(raw_items, feed.get("name", "unknown")))
            except Exception as exc:
                self.logger.warning("News feed failed safely: %s: %s", feed.get("name"), exc)

        relevant = [
            item for item in self._dedupe(collected)
            if item.get("relevance_score", 0.0) >= self.min_relevance
        ]
        relevant.sort(key=lambda item: item.get("published_at") or "", reverse=True)

        if relevant:
            self._write_cache(relevant[:max_items])
            return relevant[:max_items]

        if cached.get("items"):
            return list(cached["items"])[:max_items]

        return []

    def score_relevance(self, title: str, summary: str = "") -> dict:
        """Score whether a headline is useful to NIFTY context."""
        text = f"{title or ''} {summary or ''}".lower()
        matched = []
        score = 0.0
        for source in (self.DIRECT_TERMS, self.MACRO_TERMS, self.SECTOR_TERMS):
            for term, weight in source.items():
                if re.search(rf"\b{re.escape(term)}\b", text):
                    score += weight
                    matched.append(term)
        if "market" in text and ("india" in text or "nifty" in text):
            score += 0.10
            matched.append("india_market_context")
        return {
            "relevance_score": round(min(1.0, score), 3),
            "matched_terms": sorted(set(matched)),
        }

    def _fetch_feed(self, feed: Mapping[str, Any]) -> list[dict]:
        url = str(feed.get("url", ""))
        if not url:
            return []

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 GREY/2.0 market-intelligence "
                    "(read-only research)"
                ),
                "Accept": "application/rss+xml, application/json, text/xml, */*",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read()

        if feed.get("kind") == "nse_json":
            return self._parse_nse_json(body, feed)
        return self._parse_rss(body, feed)

    def _parse_rss(self, body: bytes, feed: Mapping[str, Any]) -> list[dict]:
        root = ET.fromstring(body)
        items = []
        for node in root.findall(".//item") or root.findall(".//{*}item"):
            title = self._node_text(node, "title")
            link = self._node_text(node, "link")
            summary = self._node_text(node, "description")
            published = self._parse_date(self._node_text(node, "pubDate"))
            if not title:
                continue
            items.append({
                "source": feed.get("name", "rss"),
                "title": self._clean_text(title),
                "summary": self._clean_text(summary),
                "url": link,
                "published_at": published,
                "collected_at": self._now_iso(),
            })
        return items

    def _parse_nse_json(self, body: bytes, feed: Mapping[str, Any]) -> list[dict]:
        payload = json.loads(body.decode("utf-8", errors="replace"))
        records = payload if isinstance(payload, list) else payload.get("data", [])
        items = []
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, Mapping):
                continue
            title = (
                record.get("desc")
                or record.get("subject")
                or record.get("sm_name")
                or record.get("symbol")
                or ""
            )
            published = (
                record.get("an_dt")
                or record.get("date")
                or record.get("sort_date")
                or self._now_iso()
            )
            items.append({
                "source": feed.get("name", "NSE"),
                "title": self._clean_text(str(title)),
                "summary": self._clean_text(str(record.get("attchmntText") or "")),
                "url": str(record.get("attchmntFile") or ""),
                "published_at": str(published),
                "collected_at": self._now_iso(),
            })
        return items

    def _score_items(self, raw_items: Iterable[dict], source_name: str) -> list[dict]:
        scored = []
        for item in raw_items:
            score = self.score_relevance(item.get("title", ""), item.get("summary", ""))
            scored.append({
                **item,
                "source": item.get("source") or source_name,
                **score,
            })
        return scored

    def _read_cache(self) -> dict:
        try:
            if self.cache_path.exists():
                with self.cache_path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
        except Exception as exc:
            self.logger.warning("News cache read failed safely: %s", exc)
        return {}

    def _write_cache(self, items: list[dict]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("w", encoding="utf-8") as handle:
                json.dump(
                    {"created_at": time.time(), "items": items},
                    handle,
                    indent=2,
                    sort_keys=True,
                )
        except Exception as exc:
            self.logger.warning("News cache write failed safely: %s", exc)

    def _cache_is_fresh(self, cached: Mapping[str, Any]) -> bool:
        created_at = float(cached.get("created_at") or 0.0)
        return bool(cached.get("items")) and (time.time() - created_at) < self.cache_seconds

    def _dummy_items(self) -> list[dict]:
        base = {
            "source": "dummy-news",
            "published_at": self._now_iso(),
            "collected_at": self._now_iso(),
            "url": "",
        }
        items = [
            {
                **base,
                "title": "NIFTY trades firm as banks and financial stocks lead",
                "summary": "Breadth is supportive while India VIX stays contained.",
            },
            {
                **base,
                "title": "RBI liquidity update keeps traders cautious before event window",
                "summary": "Market participants watch rupee, crude, and bond yields.",
            },
        ]
        return self._score_items(items, "dummy-news")

    @staticmethod
    def _dedupe(items: Iterable[dict]) -> list[dict]:
        seen = set()
        unique = []
        for item in items:
            key = (
                str(item.get("source", "")).lower(),
                str(item.get("title", "")).strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    @staticmethod
    def _node_text(node: ET.Element, tag: str) -> str:
        found = node.find(tag)
        if found is None:
            found = node.find(f".//{{*}}{tag}")
        return "" if found is None or found.text is None else found.text.strip()

    @staticmethod
    def _parse_date(value: str) -> str:
        if not value:
            return GreyNewsAggregator._now_iso()
        try:
            return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
        except Exception:
            return value

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _feeds_from_env() -> list[dict] | None:
        raw = os.getenv("GREY_NEWS_FEEDS_JSON")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            return None


__all__ = ["GreyNewsAggregator"]
