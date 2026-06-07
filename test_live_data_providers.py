"""
Smoke tests for GREY live data providers.

These tests use fake data only. They do not call NSE, Angel One, or any broker.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from grey_live_data_provider import GreyLiveDataProvider
from grey_oi_tracker import GreyOiTracker
from grey_pcr_calculator import GreyPcrCalculator
from grey_vix_data_provider import GreyVixDataProvider


class FakeBrokerClient:
    """Small fake broker client for provider integration tests."""

    def fetch_base_market_data(self, symbol: str = "NIFTY") -> dict:
        return {
            "symbol": symbol,
            "price": 22500.0,
            "price_change_from_open": 110.0,
            "atr_14": 70.0,
            "is_expiry": False,
        }


def fake_vix_fetcher() -> dict:
    """Return a small NSE-like allIndices payload."""
    return {
        "data": [
            {
                "index": "INDIA VIX",
                "last": 14.8,
                "previousClose": 13.6,
            }
        ]
    }


def test_vix_provider_cache(tmp_path: Path) -> None:
    provider = GreyVixDataProvider(cache_path=tmp_path / "vix.json", fetcher=fake_vix_fetcher)
    first = provider.get_vix_data()
    second = provider.get_vix_data()
    assert first["india_vix"] == 14.8
    assert second["vix_prev_close"] == 13.6
    assert second["source"] in ("memory_cache", "nse")


def test_pcr_calculator_from_rows(tmp_path: Path) -> None:
    rows = [
        {"strike": 22400, "option_type": "PE", "oi": 1200, "volume": 80},
        {"strike": 22500, "option_type": "PE", "oi": 1800, "volume": 100},
        {"strike": 22500, "option_type": "CE", "oi": 1000, "volume": 90},
        {"strike": 22600, "option_type": "CE", "oi": 900, "volume": 70},
    ]
    calculator = GreyPcrCalculator(cache_path=tmp_path / "pcr.json")
    result = calculator.calculate(symbol="NIFTY", spot_price=22500.0, option_rows=rows)
    assert round(result["pcr_oi"], 3) == round(3000 / 1900, 3)
    assert result["put_wall_weight"] > result["call_wall_weight"]


def test_oi_tracker_baseline_and_change(tmp_path: Path) -> None:
    tracker = GreyOiTracker(storage_path=tmp_path / "oi.json")
    first = tracker.update_and_calculate(
        "NIFTY",
        {"call_oi_total": 1000, "put_oi_total": 1200},
        dt=datetime(2026, 6, 6, 9, 20),
    )
    second = tracker.update_and_calculate(
        "NIFTY",
        {"call_oi_total": 1100, "put_oi_total": 1500},
        dt=datetime(2026, 6, 6, 10, 20),
    )
    assert first["baseline_initialized"] is True
    assert second["call_oi_change_pct"] == 10.0
    assert second["put_oi_change_pct"] == 25.0


def test_master_provider_merge(tmp_path: Path) -> None:
    rows = [
        {"strike": 22400, "option_type": "PE", "oi": 1200, "volume": 80},
        {"strike": 22500, "option_type": "PE", "oi": 1800, "volume": 100},
        {"strike": 22500, "option_type": "CE", "oi": 1000, "volume": 90},
        {"strike": 22600, "option_type": "CE", "oi": 900, "volume": 70},
    ]
    provider = GreyLiveDataProvider(
        broker_client=FakeBrokerClient(),
        vix_provider=GreyVixDataProvider(cache_path=tmp_path / "vix.json", fetcher=fake_vix_fetcher),
        pcr_calculator=GreyPcrCalculator(cache_path=tmp_path / "pcr.json", option_rows_provider=lambda *_: rows),
        oi_tracker=GreyOiTracker(storage_path=tmp_path / "oi.json"),
    )
    context = provider.get_market_context("NIFTY")
    assert context["india_vix"] == 14.8
    assert context["pcr_oi"] > 1.0
    assert "call_oi_change_pct" in context
    assert context["data_provider_status"] in ("OK", "DEGRADED")


def main() -> None:
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_vix_provider_cache(tmp_path)
        test_pcr_calculator_from_rows(tmp_path)
        test_oi_tracker_baseline_and_change(tmp_path)
        test_master_provider_merge(tmp_path)
    print("live data providers OK")


if __name__ == "__main__":
    main()
