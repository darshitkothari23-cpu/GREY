"""
Smoke test for GREY's VIX, PCR, expiry-cycle, and OI-change modules.

This test uses only dummy data. It does not call Angel One, NSE, or any broker.
"""

from __future__ import annotations

import json

from grey_expiry_cycle_module import GreyExpiryCycleModule
from grey_oi_change_module import GreyOiChangeModule
from grey_pcr_module import GreyPcrModule
from grey_signal_aggregator import GreySignalAggregator
from grey_vix_regime_module import GreyVixRegimeModule


def print_packet(title: str, packet: dict) -> None:
    """Print one module result in a readable way."""
    print(f"\n=== {title} ===")
    print(json.dumps(packet, indent=2, default=str))


def main() -> None:
    """Run all four new modules with realistic dummy NSE options data."""
    print("Step 1: Building dummy market data for the four new GREY modules...")
    market_data = {
        "india_vix": 14.8,
        "india_vix_prev_close": 13.2,
        "india_vix_5day_avg": 14.1,
        "pcr_oi": 1.32,
        "pcr_volume": 1.18,
        "pcr_5day_avg": 1.05,
        "days_to_expiry": 3,
        "is_monthly_expiry": False,
        "current_weekday": 1,
        "call_oi_change_pct": -12.5,
        "put_oi_change_pct": 14.0,
        "atm_call_oi_change": -16.0,
        "atm_put_oi_change": 18.0,
    }

    print("Step 2: Initializing modules...")
    vix_module = GreyVixRegimeModule()
    pcr_module = GreyPcrModule()
    expiry_module = GreyExpiryCycleModule()
    oi_module = GreyOiChangeModule()

    print("Step 3: Running module evaluations...")
    outputs = {
        "VIX_REGIME": vix_module.evaluate(market_data, "MIDDAY"),
        "PCR": pcr_module.evaluate(market_data, "MIDDAY"),
        "EXPIRY_CYCLE": expiry_module.evaluate(market_data, "MIDDAY"),
        "OI_CHANGE": oi_module.evaluate(market_data, "MIDDAY"),
    }

    print("Step 4: Printing module packets...")
    for module_id, packet in outputs.items():
        print_packet(module_id, packet)
        assert packet["module_id"] == module_id
        assert -10.0 <= float(packet["score"]) <= 10.0
        assert packet["direction"] in ("BULL", "BEAR", "NEUTRAL")
        assert 0.0 <= float(packet["confidence"]) <= 1.0
        assert packet["status"] in ("ACTIVE", "INSUFFICIENT_DATA", "UNAVAILABLE")
        assert "raw_components" in packet

    print("\nStep 5: Sending all four packets into GreySignalAggregator...")
    aggregate = GreySignalAggregator().aggregate(outputs, "MIDDAY")
    print(json.dumps(aggregate, indent=2, default=str))

    print("\nGREY new modules test OK")


if __name__ == "__main__":
    main()
