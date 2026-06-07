"""Tests for deep-review remediation changes.

These tests use fake market data only. They do not place orders, call brokers,
query news feeds, or call Gemini.
"""

from __future__ import annotations

import importlib
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from grey_daily_efficacy_tracker import GreyDailyEfficacyTracker
from grey_enhanced_phase1_engine import GreyEnhancedPhase1Engine


def test_range_bound_accuracy_calculation() -> None:
    """Range-bound accuracy counts periods that stayed inside predicted bounds."""
    tracker = GreyDailyEfficacyTracker()
    signals = [
        {
            "timestamp": "2026-06-06T09:15:00",
            "predicted_high": 23600,
            "predicted_low": 23400,
            "evaluation_due_at": "2026-06-06T09:45:00",
        },
        {
            "timestamp": "2026-06-06T10:00:00",
            "kronos": {"predicted_high": 23560, "predicted_low": 23480},
            "evaluation_due_at": "2026-06-06T10:30:00",
        },
    ]
    candles = pd.DataFrame(
        [
            {"timestamp": "2026-06-06T09:15:00", "open": 23500, "high": 23540, "low": 23440, "close": 23510},
            {"timestamp": "2026-06-06T09:30:00", "open": 23510, "high": 23590, "low": 23420, "close": 23500},
            {"timestamp": "2026-06-06T10:00:00", "open": 23520, "high": 23570, "low": 23490, "close": 23540},
            {"timestamp": "2026-06-06T10:15:00", "open": 23540, "high": 23545, "low": 23485, "close": 23520},
        ]
    )

    accuracy = tracker.calculate_range_bound_accuracy(signals, candles)

    assert accuracy == 50.0


def test_risk_manager_position_sizing() -> None:
    """Position sizing uses confidence buckets and account-size scaling."""
    from grey_risk_manager import GreyRiskManager

    small_account = GreyRiskManager(account_size=100_000)
    large_account = GreyRiskManager(account_size=350_000)

    assert small_account.position_size(0.55, 20) == 1
    assert small_account.position_size(0.65, 20) == 2
    assert small_account.position_size(0.80, 20) == 3
    assert large_account.position_size(0.80, 20) == 9


def test_risk_manager_stop_loss() -> None:
    """Short-premium stop loss exits at 50 percent adverse premium expansion."""
    from grey_risk_manager import GreyRiskManager

    manager = GreyRiskManager(account_size=100_000)

    assert manager.stop_loss_for_iron_condor(100.0, 15) == 150.0
    assert manager.should_trade({"confidence": 0.7}) is True
    manager.record_trade_result(-2_500.0)
    assert manager.should_trade({"confidence": 0.7}) is False


def test_gemini_disabled_by_default(monkeypatch) -> None:
    """Gemini defaults to disabled unless GREY_GEMINI_ENABLED is true."""
    monkeypatch.delenv("GREY_GEMINI_ENABLED", raising=False)
    import grey_gemini_reasoning_engine

    importlib.reload(grey_gemini_reasoning_engine)
    engine = grey_gemini_reasoning_engine.GreyGeminiReasoningEngine(api_key="fake")

    assert engine.requested_enabled is False
    assert engine.enabled is False


def test_news_aggregation_disabled(monkeypatch, tmp_path: Path) -> None:
    """Enhanced cycles do not initialize or run the news aggregator by default."""
    monkeypatch.setenv("GREY_DISABLE_NEWS", "True")
    engine = GreyEnhancedPhase1Engine(dummy_mode=True, journal_path=tmp_path / "enhanced.jsonl")
    result = engine.run_once(symbol="NIFTY")

    assert engine.news is None
    assert result["news"] == []
    assert "NEWS" not in result["module_outputs"]


def test_sentiment_disabled(monkeypatch, tmp_path: Path) -> None:
    """Enhanced cycles do not initialize or run sentiment by default."""
    monkeypatch.setenv("GREY_DISABLE_SENTIMENT", "True")
    engine = GreyEnhancedPhase1Engine(dummy_mode=True, journal_path=tmp_path / "enhanced.jsonl")
    result = engine.run_once(symbol="NIFTY")

    assert engine.sentiment is None
    assert result["sentiment"]["status"] == "DISABLED"
    assert "SENTIMENT" not in result["module_outputs"]


def test_a_b_test_logging(monkeypatch, tmp_path: Path) -> None:
    """A/B mode records with-Gemini and without-Gemini versions in the journal."""
    monkeypatch.setenv("GREY_A_B_TEST_MODE", "True")
    monkeypatch.setenv("GREY_GEMINI_ENABLED", "False")
    journal_path = tmp_path / "enhanced.jsonl"
    engine = GreyEnhancedPhase1Engine(dummy_mode=True, journal_path=journal_path)

    result = engine.run_once(symbol="NIFTY")
    record = json.loads(journal_path.read_text(encoding="utf-8").splitlines()[-1])

    assert result["ab_test"]["enabled"] is True
    assert "version_A_with_gemini" in result["ab_test"]
    assert "version_B_without_gemini" in result["ab_test"]
    assert record["ab_test"]["version_A_with_gemini"]["gemini_enabled"] is True
    assert record["ab_test"]["version_B_without_gemini"]["gemini_enabled"] is False


def test_efficacy_includes_both_metrics(tmp_path: Path) -> None:
    """Daily efficacy JSON includes directional and range-bound accuracy fields."""
    tracker = GreyDailyEfficacyTracker()
    signals = [
        {
            "timestamp": "2026-06-06T09:15:00",
            "symbol": "NIFTY",
            "direction_bias": "BULL",
            "confidence": 0.7,
            "entry_price": 23500,
            "predicted_high": 23600,
            "predicted_low": 23400,
            "evaluation_due_at": "2026-06-06T09:45:00",
        }
    ]
    candles = pd.DataFrame(
        [
            {"timestamp": "2026-06-06T09:15:00", "open": 23500, "high": 23540, "low": 23440, "close": 23510},
            {"timestamp": "2026-06-06T09:30:00", "open": 23510, "high": 23590, "low": 23420, "close": 23530},
        ]
    )

    report = tracker.build_report(
        signal_log=signals,
        ohlcv_data=candles,
        report_date="2026-06-06",
        symbol="NIFTY",
    )
    output = tracker.save_report(report, tmp_path)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert "directional_accuracy" in saved["summary"]
    assert "range_bound_accuracy" in saved["summary"]
    assert saved["summary"]["range_bound_accuracy"] == 100.0


def test_phase1_range_bound_evaluation(monkeypatch) -> None:
    """Phase 1 can evaluate range-bound fit alongside directional outcome."""
    monkeypatch.setenv("GREY_USE_RANGE_BOUND_EVALUATION", "True")
    from grey_phase1_engine import GreyPhase1Engine

    engine = GreyPhase1Engine()
    evaluation = engine.evaluate_signal(
        {
            "timestamp": "2026-06-06T09:15:00",
            "entry_price": 23500,
            "direction_bias": "BULL",
            "predicted_high": 23600,
            "predicted_low": 23400,
        },
        {"price": 23520, "high": 23580, "low": 23410},
        datetime(2026, 6, 6, 9, 30),
    )

    assert evaluation["directional_outcome"] == "CORRECT"
    assert evaluation["range_outcome"] == "CORRECT_RANGE"
