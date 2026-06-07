"""
India VIX data provider for GREY.

This provider reads India VIX from NSE's public index data, caches the result,
and falls back safely when the website blocks or fails.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


class GreyVixDataProvider:
    """Fetch live India VIX with cache and fallback handling."""

    NSE_HOME_URL = "https://www.nseindia.com"
    NSE_LIVE_INDICES_URL = "https://www.nseindia.com/market-data/live-market-indices"
    NSE_ALL_INDICES_API = "https://www.nseindia.com/api/allIndices"

    def __init__(
        self,
        *,
        cache_path: str | Path = "data/live_cache/india_vix.json",
        cache_seconds: int | None = None,
        timeout_seconds: int = 10,
        fetcher: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        # Store cache on disk so GREY survives transient NSE failures.
        self.cache_path = Path(cache_path)

        # Default cache TTL is 5 minutes to avoid scraping every minute.
        self.cache_seconds = int(cache_seconds or os.getenv("GREY_VIX_CACHE_SECONDS", "300"))

        # Keep NSE requests short so live GREY does not hang.
        self.timeout_seconds = timeout_seconds

        # Tests can inject a fake fetcher; live mode uses NSE.
        self.fetcher = fetcher

        # Keep an in-memory cache for repeated calls in the same process.
        self._memory_cache: dict | None = None

        # Keep a simple opener so NSE cookies can be reused.
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def get_vix_data(self, *, force_refresh: bool = False) -> dict:
        """Return India VIX data as {india_vix, vix_prev_close, ...metadata}."""
        try:
            # Use memory cache first if it is still fresh.
            memory = self._fresh_memory_cache()
            if memory and not force_refresh:
                return self._with_source(memory, "memory_cache")

            # Use disk cache next if it is still fresh.
            disk = self._read_cache()
            if disk and self._is_fresh(disk) and not force_refresh:
                self._memory_cache = disk
                return self._with_source(disk, "disk_cache")

            # Fetch live NSE data when no fresh cache is available.
            fetched_payload = self.fetcher() if self.fetcher else self._fetch_from_nse()
            parsed = self._parse_nse_payload(fetched_payload)
            parsed["as_of"] = self._now_iso()
            parsed["is_stale"] = False
            self._write_cache(parsed)
            self._memory_cache = parsed
            return self._with_source(parsed, "nse")
        except Exception as exc:
            # Use any disk cache, even stale, before falling back to static values.
            cached = self._read_cache()
            if cached:
                cached["is_stale"] = True
                cached["error"] = str(exc)
                return self._with_source(cached, "stale_cache")

            # Use optional operator-provided fallback values from .env.
            fallback = self._env_fallback(str(exc))
            if fallback:
                return fallback

            # Return a safe unavailable packet-shaped data dict.
            return {
                "india_vix": None,
                "vix_prev_close": None,
                "source": "unavailable",
                "as_of": self._now_iso(),
                "is_stale": True,
                "error": str(exc),
            }

    def _fetch_from_nse(self) -> Mapping[str, Any]:
        """Fetch NSE all-indices JSON with browser-like headers and cookies."""
        # First request primes cookies that NSE often expects.
        self._open_json_or_html(self.NSE_LIVE_INDICES_URL)

        # Second request reads the JSON API used by the page.
        response_text = self._open_json_or_html(self.NSE_ALL_INDICES_API)
        return json.loads(response_text)

    def _open_json_or_html(self, url: str) -> str:
        """Open one NSE URL and return decoded response text."""
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"
                ),
                "Accept": "application/json,text/html,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": self.NSE_HOME_URL,
                "Connection": "keep-alive",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"NSE VIX HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"NSE VIX network error: {exc}") from exc

    def _parse_nse_payload(self, payload: Mapping[str, Any]) -> dict:
        """Extract India VIX and previous close from NSE allIndices payload."""
        rows = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError("NSE allIndices payload missing data list")

        for row in rows:
            if not isinstance(row, Mapping):
                continue
            index_name = str(row.get("index") or row.get("indexSymbol") or row.get("name") or "").upper()
            if "INDIA VIX" not in index_name and "INDIAVIX" not in index_name:
                continue

            india_vix = self._first_float(row, ("last", "lastPrice", "ltp", "value"))
            prev_close = self._first_float(row, ("previousClose", "previous_close", "prevClose"))
            if india_vix is None:
                raise ValueError(f"NSE India VIX row missing live value: {row}")
            return {
                "india_vix": india_vix,
                "vix_prev_close": prev_close,
            }
        raise ValueError("India VIX row not found in NSE allIndices payload")

    def _fresh_memory_cache(self) -> dict | None:
        """Return in-memory cache only when it is still fresh."""
        if not self._memory_cache:
            return None
        if self._is_fresh(self._memory_cache):
            return dict(self._memory_cache)
        return None

    def _read_cache(self) -> dict | None:
        """Read cached VIX data from disk."""
        try:
            if not self.cache_path.exists():
                return None
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_cache(self, data: Mapping[str, Any]) -> None:
        """Write VIX cache to disk."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(dict(data), indent=2, default=str), encoding="utf-8")
        except Exception:
            # Cache write failure should not break live market context.
            return

    def _is_fresh(self, data: Mapping[str, Any]) -> bool:
        """Return True when cache timestamp is inside TTL."""
        as_of = self._parse_dt(data.get("as_of"))
        if as_of is None:
            return False
        return (time.time() - as_of.timestamp()) <= self.cache_seconds

    def _env_fallback(self, error: str) -> dict | None:
        """Return static fallback values from .env when configured."""
        india_vix = self._to_float(os.getenv("GREY_FALLBACK_INDIA_VIX"))
        prev_close = self._to_float(os.getenv("GREY_FALLBACK_VIX_PREV_CLOSE"))
        if india_vix is None:
            return None
        return {
            "india_vix": india_vix,
            "vix_prev_close": prev_close,
            "source": "env_fallback",
            "as_of": self._now_iso(),
            "is_stale": True,
            "error": error,
        }

    @staticmethod
    def _with_source(data: Mapping[str, Any], source: str) -> dict:
        """Attach source metadata without mutating the original cache dict."""
        result = dict(data)
        result["source"] = source
        return result

    @staticmethod
    def _first_float(data: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
        """Return the first parseable numeric field."""
        for key in keys:
            value = GreyVixDataProvider._to_float(data.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely parse a float from NSE or env values."""
        if value is None:
            return None
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        """Parse ISO timestamp safely."""
        if value is None:
            return None
        try:
            text = str(value)
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _now_iso() -> str:
        """Return current UTC timestamp for cache metadata."""
        return datetime.now(timezone.utc).isoformat()


__all__ = ["GreyVixDataProvider"]
