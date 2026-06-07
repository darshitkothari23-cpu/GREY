"""
Lightweight integration smoke test for GREY review modules.

This script uses dummy inputs only. It verifies import compatibility and a
minimal context/reporting flow without any live-market action behavior.
"""

from datetime import datetime, timedelta

from grey_daily_report import GreyDailyReport
from grey_data_quality_guard import GreyDataQualityGuard
from grey_evaluation_tracker import GreyEvaluationTracker
from grey_global_risk_module import GreyGlobalRiskModule
from grey_india_macro_module import GreyIndiaMacroModule
from grey_options_microstructure import GreyOptionsMicrostructure
from grey_regime_engine import GreyRegimeEngine
from grey_sector_rotation_module import GreySectorRotationModule
from grey_session_machine import GreySessionMachine
from grey_signal_aggregator import GreySignalAggregator
from market_calendar import MarketCalendar


def main() -> None:
    now = datetime(2026, 6, 1, 9, 20)
    calendar = MarketCalendar(events=[
        {
            "name": "Dummy RBI Event",
            "event_time": "10:00",
            "category": "policy",
            "priority": "HIGH",
        }
    ])
    event_minutes_away = calendar.get_next_event_minutes(now)

    session_machine = GreySessionMachine()
    session_state = session_machine.get_current_state(
        now,
        is_expiry=False,
        event_minutes_away=event_minutes_away,
    )

    options = GreyOptionsMicrostructure()
    regime = GreyRegimeEngine()
    global_risk = GreyGlobalRiskModule()
    india_macro = GreyIndiaMacroModule()
    sector_rotation = GreySectorRotationModule()
    data_quality = GreyDataQualityGuard()
    aggregator = GreySignalAggregator()
    tracker = GreyEvaluationTracker()
    report_builder = GreyDailyReport()

    market_data = {
        "price": 25000.0,
        "previous_price": 24980.0,
        "timestamp": now,
        "session_state": session_state,
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

    is_expiry_sensitive = session_machine.is_expiry_sensitive(now, is_expiry=False)
    module_outputs = {
        "OPTIONS": options.evaluate(market_data, session_state, is_expiry_sensitive),
        "REGIME": regime.evaluate(market_data, session_state, is_expiry_sensitive),
        "GLOBAL": global_risk.evaluate(market_data, session_state),
        "INDIA_MACRO": india_macro.evaluate(market_data, session_state),
        "SECTOR": sector_rotation.evaluate(market_data, session_state),
    }

    guard_inputs = dict(market_data)
    guard_inputs["module_outputs"] = module_outputs
    module_outputs["DATA_QUALITY"] = data_quality.evaluate(guard_inputs, now)

    composite_view = aggregator.aggregate(module_outputs, session_state)
    tracker.record_snapshot(now, market_data, module_outputs, composite_view)
    tracker.record_snapshot(
        now + timedelta(minutes=45),
        {**market_data, "session_state": "EARLY_TREND", "price": 25160.0},
        module_outputs,
        composite_view,
    )
    tracker_output = tracker.finalize_day({
        "realized_outcomes": {
            "move_pct": 0.006,
            "move_start_dt": (now + timedelta(minutes=45)).isoformat(),
        }
    })
    report = report_builder.build_report(
        tracker_output["daily_summary"],
        tracker_output,
        [composite_view],
    )

    expected_report_keys = {
        "headline_summary",
        "market_day_type",
        "key_time_blocks",
        "best_early_warnings",
        "false_confidence_events",
        "best_modules",
        "worst_modules",
        "report_notes",
    }
    missing_report_keys = expected_report_keys - set(report)
    if missing_report_keys:
        raise AssertionError(f"report missing keys: {sorted(missing_report_keys)}")
    if "direction_bias" not in composite_view:
        raise AssertionError("composite view missing direction_bias")
    if not isinstance(module_outputs["DATA_QUALITY"]["freeze_suggestion"], bool):
        raise AssertionError("data quality freeze_suggestion must be bool")

    print("GREY smoke test OK")


if __name__ == "__main__":
    main()
