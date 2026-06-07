"""
Master live data provider for GREY.

This module combines broker spot/candle data, NSE India VIX, efficient PCR, and
open-interest change tracking into one GREY market_data dictionary.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping

from grey_oi_tracker import GreyOiTracker
from grey_pcr_calculator import GreyPcrCalculator
from grey_vix_data_provider import GreyVixDataProvider


class GreyLiveDataProvider:
    """Single entry point for GREY live market context."""

    def __init__(
        self,
        *,
        broker_client: Any | None = None,
        vix_provider: GreyVixDataProvider | None = None,
        pcr_calculator: GreyPcrCalculator | None = None,
        oi_tracker: GreyOiTracker | None = None,
    ) -> None:
        # Broker client is usually LiveMarketDataClient from grey_live_forward_tester.py.
        self.broker_client = broker_client

        # NSE VIX provider handles scrape/cache/fallback.
        self.vix_provider = vix_provider or GreyVixDataProvider()

        # PCR calculator uses broker batches when broker_client is available.
        self.pcr_calculator = pcr_calculator or GreyPcrCalculator(broker_client=broker_client)

        # OI tracker stores open baseline and calculates percent change.
        self.oi_tracker = oi_tracker or GreyOiTracker()

    def get_market_context(self, symbol: str = "NIFTY") -> dict:
        """Return a complete GREY market_data dictionary."""
        errors: list[str] = []
        context: dict[str, Any] = {
            "symbol": symbol,
            "timestamp": datetime.now(),
        }

        # Step 1: Fetch spot, open move, ATR, and OHLCV from broker.
        base_context = self._safe_base_context(symbol, errors)
        context.update(base_context)

        # Step 2: Fetch India VIX from NSE with cache/fallback.
        vix_context = self._safe_vix_context(errors)
        context.update(vix_context)

        # Step 3: Calculate PCR and wall weights from limited ATM +/- 5% option rows.
        pcr_context = self._safe_pcr_context(symbol, context.get("price"), errors)
        context.update(pcr_context)

        # Step 4: Track OI change from today's first seen baseline.
        oi_context = self.oi_tracker.update_and_calculate(symbol, pcr_context, dt=context["timestamp"])
        context.update(oi_context)

        # Step 5: Add expiry-cycle fields when near-expiry data is available.
        context.update(self._expiry_context(pcr_context.get("near_expiry"), context["timestamp"]))

        # Step 6: Add option-module fallback fields if upstream data is partial.
        context.setdefault("put_wall_weight", 0.0)
        context.setdefault("call_wall_weight", 0.0)
        context.setdefault("ivp", 0.5)

        # Step 7: Add VIX aliases expected by GREY modules.
        if context.get("vix_prev_close") is not None:
            context["india_vix_prev_close"] = context.get("vix_prev_close")
        if context.get("india_vix") and context.get("vix_prev_close"):
            context.setdefault("volatility_ratio", self._safe_ratio(context["india_vix"], context["vix_prev_close"]))

        # Step 8: Add provider health metadata.
        context["data_provider_status"] = "OK" if not errors else "DEGRADED"
        context["data_provider_errors"] = errors
        return context

    def fetch_live_market_data(self, symbol: str = "NIFTY") -> dict:
        """Compatibility wrapper for code expecting fetch_live_market_data()."""
        return self.get_market_context(symbol)

    def _safe_base_context(self, symbol: str, errors: list[str]) -> dict:
        """Fetch broker context without allowing failures to stop GREY."""
        try:
            return self._fetch_base_context(symbol)
        except Exception as exc:
            errors.append(f"base_context_failed={exc}")
            return {}

    def _fetch_base_context(self, symbol: str) -> dict:
        """Fetch spot/candle data from broker client without relying on broker VIX."""
        if self.broker_client is None:
            return {}

        # Test clients or future adapters can expose a simple public method.
        if hasattr(self.broker_client, "fetch_base_market_data"):
            return dict(self.broker_client.fetch_base_market_data(symbol))

        # Use GREY's current LiveMarketDataClient private helpers to avoid its old VIX path.
        required = (
            "_ensure_session",
            "_resolve_index_instrument",
            "_fetch_nifty_spot",
        )
        if all(hasattr(self.broker_client, name) for name in required):
            self.broker_client._ensure_session()
            spot_instrument = self.broker_client._resolve_index_instrument(symbol)
            spot = self.broker_client._fetch_nifty_spot(spot_instrument, symbol)
            context = {
                "price": spot.get("price"),
                "price_change_from_open": spot.get("price", 0.0) - spot.get("open", spot.get("price", 0.0)),
            }
            if hasattr(self.broker_client, "_calculate_atr_14"):
                try:
                    context["atr_14"] = self.broker_client._calculate_atr_14(spot_instrument)
                except Exception as exc:
                    context["atr_14_error"] = str(exc)
            if hasattr(self.broker_client, "_get_intraday_ohlcv"):
                try:
                    context["ohlcv_df"] = self.broker_client._get_intraday_ohlcv(
                        spot_instrument,
                        interval="FIFTEEN_MINUTE",
                        count=512,
                    )
                except Exception as exc:
                    context["ohlcv_error"] = str(exc)
            return context

        # Final fallback for custom adapters; may include their own VIX path.
        if hasattr(self.broker_client, "fetch_live_market_data"):
            return dict(self.broker_client.fetch_live_market_data(symbol=symbol))

        return {}

    def _safe_vix_context(self, errors: list[str]) -> dict:
        """Fetch VIX context safely."""
        vix_context = self.vix_provider.get_vix_data()
        if vix_context.get("error"):
            errors.append(f"vix_context_warning={vix_context['error']}")
        return vix_context

    def _safe_pcr_context(self, symbol: str, spot_price: Any, errors: list[str]) -> dict:
        """Fetch PCR context safely."""
        pcr_context = self.pcr_calculator.calculate(
            symbol=symbol,
            spot_price=self._to_float(spot_price),
        )
        if pcr_context.get("error"):
            errors.append(f"pcr_context_warning={pcr_context['error']}")
        return pcr_context

    def _expiry_context(self, near_expiry: Any, now_dt: datetime) -> dict:
        """Build expiry fields for the expiry-cycle module."""
        expiry_date = self._parse_expiry_date(near_expiry)
        if expiry_date is None:
            return {
                "days_to_expiry": None,
                "is_monthly_expiry": False,
                "current_weekday": now_dt.weekday(),
            }
        days_to_expiry = (expiry_date - now_dt.date()).days
        return {
            "days_to_expiry": days_to_expiry,
            "is_monthly_expiry": self._is_monthly_expiry(expiry_date),
            "current_weekday": now_dt.weekday(),
            "is_expiry": days_to_expiry == 0,
            "near_expiry": expiry_date.isoformat(),
        }

    @staticmethod
    def _parse_expiry_date(value: Any) -> date | None:
        """Parse common NSE/Angel expiry date strings."""
        if isinstance(value, date):
            return value
        if not value:
            return None
        text = str(value).strip().upper()
        for fmt in ("%d%b%Y", "%d%b%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _is_monthly_expiry(expiry_date: date) -> bool:
        """Return True when expiry date is the last Thursday of its month."""
        # NSE index monthly expiries are commonly the last Thursday.
        if expiry_date.weekday() != 3:
            return False
        return (expiry_date + timedelta(days=7)).month != expiry_date.month

    @staticmethod
    def _safe_ratio(numerator: Any, denominator: Any) -> float:
        """Safely calculate a ratio."""
        num = GreyLiveDataProvider._to_float(numerator)
        den = GreyLiveDataProvider._to_float(denominator)
        if num is None or den is None or den == 0:
            return 1.0
        return round(num / den, 4)

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely parse a float."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


__all__ = ["GreyLiveDataProvider"]
