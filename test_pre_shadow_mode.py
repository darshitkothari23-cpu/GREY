"""Mandatory pre-shadow-mode tests for GREY 2.0.

These tests use synthetic data only. They do not call NSE, Gemini, Angel One,
or Telegram.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from greeks_aware_strike_selector import GreeksAwareStrikeSelector
from grey_backtest_runner import GreyBacktestRunner
from grey_daily_efficacy_tracker import GreyDailyEfficacyTracker
from grey_enhanced_phase1_engine import GreyEnhancedPhase1Engine
from grey_ev_calculator import GreyEVCalculator
from grey_risk_manager import GreyRiskManager
from grey_vix_data_provider import GreyVixDataProvider


def test_position_sizing_with_vix_scaling() -> None:
    """VIX scaling reduces lots in high-volatility regimes."""
    manager = GreyRiskManager(account_size=100_000)

    assert manager.position_size(0.70, 15) == 2.67
    assert manager.position_size(0.70, 25) == 1.6


def test_time_weighted_stop_loss() -> None:
    """Iron Condor stops loosen as time in trade increases."""
    manager = GreyRiskManager(account_size=100_000)

    assert manager.stop_loss_for_iron_condor(100.0, 15) == 150.0
    assert manager.stop_loss_for_iron_condor(100.0, 90) == 175.0
    assert manager.stop_loss_for_iron_condor(100.0, 150) == 200.0


def test_ev_calculator_breakeven() -> None:
    """Expected value includes slippage, brokerage, and STT costs."""
    calculator = GreyEVCalculator()

    assert calculator.calculate_ev(0.58, 2850, 3150) == 20.0
    assert calculator.calculate_ev(0.65, 2850, 3150) == 440.0


def test_vix_dynamic_caching(tmp_path: Path) -> None:
    """VIX cache timeout is 60 seconds normally and 20 seconds in high VIX."""
    provider = GreyVixDataProvider(cache_path=tmp_path / "vix.json")
    now = datetime.now(timezone.utc)
    low_vix = {"india_vix": 19.0, "as_of": now.isoformat()}
    high_vix = {"india_vix": 21.0, "as_of": now.isoformat()}

    assert provider.dynamic_cache_seconds(low_vix) == 60
    assert provider.dynamic_cache_seconds(high_vix) == 20
    assert provider.is_vix_data_stale(low_vix, threshold_seconds=60) is False


def test_parallel_ab_logging(monkeypatch, tmp_path: Path) -> None:
    """Every enhanced signal logs baseline and Gemini arms on identical data."""
    monkeypatch.setenv("GREY_PARALLEL_AB_TEST", "True")
    monkeypatch.setenv("GREY_GEMINI_ENABLED", "True")
    monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "")
    journal_path = tmp_path / "enhanced.jsonl"
    engine = GreyEnhancedPhase1Engine(dummy_mode=True, journal_path=journal_path)

    result = engine.run_once(symbol="NIFTY")
    record = json.loads(journal_path.read_text(encoding="utf-8").splitlines()[-1])

    for source in (result, record):
        ab = source["parallel_ab_test"]
        assert "baseline_direction" in ab
        assert "baseline_confidence" in ab
        assert "baseline_score" in ab
        assert "gemini_direction" in ab
        assert "gemini_confidence" in ab
        assert "gemini_score" in ab
        assert "both_correct" in ab
        assert "baseline_only_correct" in ab
        assert "gemini_only_correct" in ab


def test_dynamic_range_thresholds() -> None:
    """ATR-adjusted range uses open +/- 1.5 times ATR_14."""
    tracker = GreyDailyEfficacyTracker()
    candles = pd.DataFrame(
        [
            {"timestamp": f"2026-06-06T09:{15 + i:02d}:00", "open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0}
            for i in range(14)
        ]
        + [
            {"timestamp": "2026-06-06T09:29:00", "open": 100.0, "high": 105.5, "low": 94.5, "close": 100.0}
        ]
    )

    metrics = tracker.calculate_atr_adjusted_range_accuracy(
        [{"timestamp": "2026-06-06T09:29:00", "evaluation_due_at": "2026-06-06T09:30:00"}],
        candles,
    )

    assert metrics == 100.0


def test_backtest_runner_loads_data(tmp_path: Path) -> None:
    """Backtest runner loads 1-minute CSV data without external services."""
    csv_path = _write_backtest_csv(tmp_path)
    runner = GreyBacktestRunner(csv_file_path=csv_path)

    data = runner.load_data(csv_path)

    assert len(data) == 30
    assert {"timestamp", "open", "high", "low", "close"}.issubset(data.columns)


def test_backtest_runner_outputs_metrics(tmp_path: Path) -> None:
    """Backtest runner outputs the required pre-shadow metrics."""
    csv_path = _write_backtest_csv(tmp_path)
    runner = GreyBacktestRunner(csv_file_path=csv_path)

    result = runner.run_backtest()

    for key in ("accuracy_pct", "ev_simulated", "sharpe_ratio", "max_drawdown_pct"):
        assert key in result


def test_greeks_strike_selector_returns_deltas() -> None:
    """Strike selector returns rough 16-delta Iron Condor structure."""
    selector = GreeksAwareStrikeSelector()

    strikes = selector.recommend_iron_condor_strikes(
        spot_price=24_350,
        iv_atm=0.14,
        days_to_expiry=3,
        target_delta=16,
    )

    assert strikes["call_delta"] == 0.16
    assert strikes["put_delta"] == -0.16
    assert strikes["call_strike"] > 24_350
    assert strikes["put_strike"] < 24_350


def _write_backtest_csv(tmp_path: Path) -> Path:
    """Write a small synthetic 1-minute OHLCV CSV."""
    rows = []
    base = pd.Timestamp("2026-06-06T09:15:00")
    for index in range(30):
        price = 23_500 + index * 2
        rows.append(
            {
                "timestamp": (base + pd.Timedelta(minutes=index)).isoformat(),
                "open": price,
                "high": price + 8,
                "low": price - 8,
                "close": price + 3,
                "volume": 10_000 + index,
            }
        )
    csv_path = tmp_path / "nifty_3months.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return csv_path
