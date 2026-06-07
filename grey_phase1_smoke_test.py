"""
Smoke test for GREY Phase 1 logging, evaluation, and Telegram reporting.
"""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from grey_phase1_engine import GreyPhase1Engine, GreySignalStore, GreyTelegramNotifier


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        store = GreySignalStore(Path(temp_dir) / "phase1_signals.jsonl")
        notifier = GreyTelegramNotifier(enabled=False, prefix="GREY:")
        engine = GreyPhase1Engine(store=store, notifier=notifier)

        signal_time = datetime(2026, 6, 1, 9, 20)
        market_data = {
            "price": 25000.0,
            "previous_price": 24980.0,
            "timestamp": signal_time,
            "volume": 100000,
            "spread_pct": 0.01,
            "implied_volatility": 16.0,
            "iv_percentile": 35.0,
            "put_wall_weight": 1_400_000.0,
            "call_wall_weight": 900_000.0,
            "ivp": 0.45,
            "event_premium_inflation": 0.20,
            "direction_signal": 0.30,
            "price_change_from_open": 45.0,
            "atr_14": 60.0,
            "price_change_pct": 0.006,
            "trend_strength": 0.70,
            "volatility_ratio": 1.05,
            "range_ratio": 1.00,
            "participation_ratio": 0.62,
            "breadth": 0.60,
            "gift_nifty_return_pct": 0.004,
            "asia_return_pct": 0.002,
            "us_futures_return_pct": 0.001,
            "vix_change_pct": -0.02,
            "usdinr_change_pct": -0.001,
            "brent_change_pct": -0.004,
            "liquidity_change_pct": -0.001,
            "rate_change_bps": 0.0,
            "private_banks_return_pct": 0.007,
            "it_return_pct": 0.003,
            "energy_return_pct": 0.002,
            "defensive_return_pct": 0.001,
            "sector_breadth": 0.65,
        }

        signal = engine.run_once("NIFTY", market_data, signal_time)
        for key in (
            "timestamp",
            "symbol",
            "session_state",
            "direction_bias",
            "confidence",
            "caution_state",
            "module_vector",
            "composite_score",
        ):
            assert key in signal, f"missing stored signal field: {key}"

        due_time = signal_time + timedelta(minutes=15)
        evaluated = engine.evaluate_due_signals(
            {"NIFTY": {"price": 25100.0}},
            due_time,
        )
        assert len(evaluated) == 1
        assert evaluated[0]["evaluation"]["result"] in (
            "CORRECT",
            "WRONG",
            "NEUTRAL_REVIEW",
        )
        assert "Actual move:" in notifier.sent_messages[0]
        assert "Module scores:" in notifier.sent_messages[0]
        assert "Total score:" in notifier.sent_messages[0]

    print("GREY Phase 1 smoke OK")


if __name__ == "__main__":
    main()
