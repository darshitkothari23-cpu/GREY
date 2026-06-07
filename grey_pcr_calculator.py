"""
Efficient PCR calculator for GREY.

This calculator uses only key NIFTY option strikes around ATM, caches the
result for 15 minutes, and avoids one-call-per-contract option-chain logic.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


class GreyPcrCalculator:
    """Calculate PCR OI and PCR volume from limited option-chain data."""

    def __init__(
        self,
        *,
        broker_client: Any | None = None,
        cache_path: str | Path = "data/live_cache/pcr_context.json",
        cache_seconds: int | None = None,
        strike_band_pct: float = 0.05,
        option_rows_provider: Callable[[str, float], Iterable[Mapping[str, Any]]] | None = None,
    ) -> None:
        # Optional SmartAPI-backed GREY live client.
        self.broker_client = broker_client

        # Cache result so GREY does not recalculate every minute.
        self.cache_path = Path(cache_path)

        # Default PCR cache TTL is 15 minutes.
        self.cache_seconds = int(cache_seconds or os.getenv("GREY_PCR_CACHE_SECONDS", "900"))

        # Only strikes inside ATM +/- 5 percent are used by default.
        self.strike_band_pct = float(strike_band_pct)

        # Tests or replay jobs can inject rows directly.
        self.option_rows_provider = option_rows_provider

    def calculate(
        self,
        *,
        symbol: str = "NIFTY",
        spot_price: float | None = None,
        option_rows: Iterable[Mapping[str, Any]] | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Return PCR context for GREY market_data."""
        try:
            # Use fresh cache first when spot has not moved far enough to require recompute.
            cached = self._read_cache()
            if cached and self._is_fresh(cached) and not force_refresh:
                return self._with_source(cached, "cache")

            # Pull option rows from the supplied rows, injected provider, or broker client.
            rows = list(option_rows) if option_rows is not None else self._fetch_option_rows(symbol, spot_price)

            # Calculate PCR and wall weights from limited strikes.
            result = self._calculate_from_rows(symbol, spot_price, rows)
            result["as_of"] = self._now_iso()
            result["is_stale"] = False
            self._write_cache(result)
            return self._with_source(result, "live")
        except Exception as exc:
            # Use stale cache if live option data fails.
            cached = self._read_cache()
            if cached:
                cached["is_stale"] = True
                cached["error"] = str(exc)
                return self._with_source(cached, "stale_cache")

            # Return neutral-ish missing data values when no cache is available.
            return {
                "pcr_oi": None,
                "pcr_volume": None,
                "put_wall_weight": 0.0,
                "call_wall_weight": 0.0,
                "put_oi_total": 0.0,
                "call_oi_total": 0.0,
                "put_volume_total": 0.0,
                "call_volume_total": 0.0,
                "atm_put_oi": None,
                "atm_call_oi": None,
                "strikes_used": [],
                "source": "unavailable",
                "as_of": self._now_iso(),
                "is_stale": True,
                "error": str(exc),
            }

    def _fetch_option_rows(self, symbol: str, spot_price: float | None) -> list[Mapping[str, Any]]:
        """Fetch limited ATM +/- band option rows using a provider or broker client."""
        if self.option_rows_provider:
            if spot_price is None:
                raise ValueError("spot_price is required for option_rows_provider.")
            return list(self.option_rows_provider(symbol, spot_price))

        if self.broker_client is None:
            raise ValueError("No broker_client or option_rows provided for PCR calculation.")

        if spot_price is None:
            spot_price = self._spot_price_from_broker(symbol)

        # Reuse GREY live client's batched option resolver when available.
        if not hasattr(self.broker_client, "_resolve_near_month_options"):
            raise ValueError("broker_client does not expose _resolve_near_month_options.")
        if not hasattr(self.broker_client, "_fetch_option_market_rows"):
            raise ValueError("broker_client does not expose _fetch_option_market_rows.")

        contracts = list(self.broker_client._resolve_near_month_options(symbol))
        active_contracts = [
            contract for contract in contracts
            if self._inside_band(self._contract_strike(contract), spot_price)
        ]
        market_pairs = self.broker_client._fetch_option_market_rows(active_contracts)
        rows = []
        for contract, row in market_pairs:
            merged = dict(row)
            merged.setdefault("strike", self._contract_strike(contract))
            merged.setdefault("option_type", self._contract_option_type(contract))
            merged.setdefault("expiry", getattr(contract, "expiry", ""))
            rows.append(merged)
        return rows

    def _spot_price_from_broker(self, symbol: str) -> float:
        """Fetch spot price from the GREY live client private helpers."""
        if not hasattr(self.broker_client, "_resolve_index_instrument"):
            raise ValueError("broker_client cannot resolve spot instrument.")
        if not hasattr(self.broker_client, "_fetch_nifty_spot"):
            raise ValueError("broker_client cannot fetch spot price.")
        spot_instrument = self.broker_client._resolve_index_instrument(symbol)
        spot = self.broker_client._fetch_nifty_spot(spot_instrument, symbol)
        return float(spot["price"])

    def _calculate_from_rows(
        self,
        symbol: str,
        spot_price: float | None,
        rows: list[Mapping[str, Any]],
    ) -> dict:
        """Calculate PCR, totals, wall weights, and ATM OI from option rows."""
        if not rows:
            raise ValueError("No option rows available for PCR calculation.")

        put_oi_total = 0.0
        call_oi_total = 0.0
        put_volume_total = 0.0
        call_volume_total = 0.0
        put_wall_weight = 0.0
        call_wall_weight = 0.0
        strike_rows: list[dict] = []

        for row in rows:
            strike = self._row_strike(row)
            option_type = self._row_option_type(row)
            if strike is None or option_type not in ("CE", "PE"):
                continue
            if spot_price is not None and not self._inside_band(strike, spot_price):
                continue

            oi = self._first_float(row, ("oi", "openInterest", "opnInterest")) or 0.0
            volume = self._first_float(row, ("volume", "tradeVolume", "tradingVolume")) or 0.0
            strike_rows.append({"strike": strike, "option_type": option_type, "oi": oi, "volume": volume})
            if option_type == "PE":
                put_oi_total += oi
                put_volume_total += volume
                put_wall_weight += oi * volume
            else:
                call_oi_total += oi
                call_volume_total += volume
                call_wall_weight += oi * volume

        if not strike_rows:
            raise ValueError("No valid option rows inside selected strike band.")

        pcr_oi = put_oi_total / call_oi_total if call_oi_total > 0 else None
        pcr_volume = put_volume_total / call_volume_total if call_volume_total > 0 else None
        atm_strike = self._nearest_strike(spot_price, [row["strike"] for row in strike_rows])
        atm_put_oi = self._atm_oi(strike_rows, atm_strike, "PE")
        atm_call_oi = self._atm_oi(strike_rows, atm_strike, "CE")

        expiries = sorted({str(row.get("expiry", "")) for row in rows if row.get("expiry")})
        return {
            "symbol": symbol,
            "pcr_oi": self._round_or_none(pcr_oi),
            "pcr_volume": self._round_or_none(pcr_volume),
            "put_wall_weight": round(put_wall_weight, 3),
            "call_wall_weight": round(call_wall_weight, 3),
            "put_oi_total": round(put_oi_total, 3),
            "call_oi_total": round(call_oi_total, 3),
            "put_volume_total": round(put_volume_total, 3),
            "call_volume_total": round(call_volume_total, 3),
            "atm_strike": atm_strike,
            "atm_put_oi": atm_put_oi,
            "atm_call_oi": atm_call_oi,
            "strikes_used": sorted({row["strike"] for row in strike_rows}),
            "option_row_count": len(strike_rows),
            "near_expiry": expiries[0] if expiries else None,
        }

    def _inside_band(self, strike: float, spot_price: float) -> bool:
        """Return True when strike is within ATM +/- configured band."""
        lower = spot_price * (1.0 - self.strike_band_pct)
        upper = spot_price * (1.0 + self.strike_band_pct)
        return lower <= strike <= upper

    @staticmethod
    def _contract_strike(contract: Any) -> float:
        """Read strike from GREY's Instrument object or dict."""
        if isinstance(contract, Mapping):
            return GreyPcrCalculator._normalize_strike(contract.get("strike"))
        return GreyPcrCalculator._normalize_strike(getattr(contract, "strike", 0.0))

    @staticmethod
    def _contract_option_type(contract: Any) -> str:
        """Read CE/PE option type from contract metadata."""
        if isinstance(contract, Mapping):
            text = str(contract.get("instrument_type") or contract.get("symbol") or "").upper()
        else:
            text = str(getattr(contract, "instrument_type", "") or getattr(contract, "symbol", "")).upper()
        if text.endswith("PE"):
            return "PE"
        if text.endswith("CE"):
            return "CE"
        return ""

    @staticmethod
    def _row_strike(row: Mapping[str, Any]) -> float | None:
        """Read a normalized strike from an option row."""
        value = GreyPcrCalculator._first_float(row, ("strike", "strikePrice"))
        if value is None:
            return None
        return GreyPcrCalculator._normalize_strike(value)

    @staticmethod
    def _row_option_type(row: Mapping[str, Any]) -> str:
        """Read CE/PE from an option row."""
        text = str(row.get("option_type") or row.get("optionType") or row.get("symbol") or "").upper()
        if text.endswith("PE") or text == "PE":
            return "PE"
        if text.endswith("CE") or text == "CE":
            return "CE"
        return ""

    @staticmethod
    def _nearest_strike(spot_price: float | None, strikes: Iterable[float]) -> float | None:
        """Pick the strike closest to spot price."""
        strike_list = list(strikes)
        if not strike_list:
            return None
        if spot_price is None:
            return sorted(strike_list)[len(strike_list) // 2]
        return min(strike_list, key=lambda strike: abs(strike - spot_price))

    @staticmethod
    def _atm_oi(rows: list[dict], atm_strike: float | None, option_type: str) -> float | None:
        """Return ATM OI for one option side."""
        if atm_strike is None:
            return None
        total = sum(row["oi"] for row in rows if row["strike"] == atm_strike and row["option_type"] == option_type)
        return round(total, 3)

    def _read_cache(self) -> dict | None:
        """Read PCR context cache from disk."""
        try:
            if not self.cache_path.exists():
                return None
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_cache(self, data: Mapping[str, Any]) -> None:
        """Write PCR context cache to disk."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(dict(data), indent=2, default=str), encoding="utf-8")
        except Exception:
            return

    def _is_fresh(self, data: Mapping[str, Any]) -> bool:
        """Return True when cache timestamp is inside TTL."""
        as_of = self._parse_dt(data.get("as_of"))
        if as_of is None:
            return False
        return (time.time() - as_of.timestamp()) <= self.cache_seconds

    @staticmethod
    def _with_source(data: Mapping[str, Any], source: str) -> dict:
        """Attach source metadata without mutating cache."""
        result = dict(data)
        result["source"] = source
        return result

    @staticmethod
    def _first_float(data: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
        """Return first parseable numeric field."""
        for key in keys:
            value = GreyPcrCalculator._to_float(data.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely parse float values from API rows."""
        if value is None:
            return None
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_strike(value: Any) -> float:
        """Normalize Angel strikes that sometimes arrive multiplied by 100."""
        raw = GreyPcrCalculator._to_float(value) or 0.0
        return raw / 100.0 if raw > 100000 else raw

    @staticmethod
    def _round_or_none(value: float | None) -> float | None:
        """Round floats while preserving None."""
        if value is None:
            return None
        return round(float(value), 4)

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        """Parse ISO cache timestamp."""
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


__all__ = ["GreyPcrCalculator"]
