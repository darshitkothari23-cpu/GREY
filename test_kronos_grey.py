"""
Local shadow-mode test for GREY + Kronos.

This script does not use Angel One credentials. It builds fake NIFTY candles,
runs the Kronos review module, and sends the output through the GREY aggregator.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from grey_kronos_module import GreyKronosModule
from grey_signal_aggregator import GreySignalAggregator


def build_dummy_ohlcv(rows: int = 512) -> pd.DataFrame:
    """Build simple, realistic-looking 15-minute NIFTY candles for local testing."""
    rng = np.random.default_rng(42)
    timestamps = pd.date_range("2026-01-01 09:15", periods=rows, freq="15min")
    drift = np.linspace(0, 140, rows)
    noise = rng.normal(0, 18, rows).cumsum() * 0.05
    close = 22500 + drift + noise
    open_ = np.concatenate([[close[0] - 8], close[:-1]])
    high = np.maximum(open_, close) + rng.uniform(8, 28, rows)
    low = np.minimum(open_, close) - rng.uniform(8, 28, rows)
    volume = rng.integers(800_000, 2_200_000, rows)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def main() -> None:
    print("Step 1: Building dummy NIFTY candle data...")
    ohlcv_df = build_dummy_ohlcv()

    print("Step 2: Running GreyKronosModule.evaluate()...")
    kronos = GreyKronosModule()
    kronos_output = kronos.evaluate(
        ohlcv_df=ohlcv_df,
        session_state="MIDDAY",
        pred_candles=5,
    )
    print(json.dumps(kronos_output, indent=2, default=str))

    print("Step 3: Sending Kronos plus dummy modules into GreySignalAggregator...")
    module_outputs = {
        "KRONOS": kronos_output,
        "OPTIONS": {
            "module_id": "OPTIONS",
            "score": 4.0,
            "direction": "BULL",
            "confidence": 0.65,
            "status": "ACTIVE",
            "reason": "Dummy supportive options context.",
        },
        "REGIME": {
            "module_id": "REGIME",
            "score": 2.0,
            "direction": "BULL",
            "confidence": 0.55,
            "status": "ACTIVE",
            "reason": "Dummy mild bullish regime.",
        },
    }
    aggregate = GreySignalAggregator().aggregate(module_outputs, "MIDDAY")
    print(json.dumps(aggregate, indent=2, default=str))
    print("GREY Kronos test OK")


if __name__ == "__main__":
    main()
