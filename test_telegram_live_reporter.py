"""
Smoke test for GREY live Telegram module-score reporter.

This test does not send a real Telegram message. It uses dry-run mode.
"""

from __future__ import annotations

import sys

from grey_telegram_live_reporter import GreyTelegramLiveReporter


def build_dummy_composite() -> dict:
    """Create a realistic GREY aggregate signal for message testing."""
    return {
        "composite_score": 3.7,
        "direction_bias": "BULL",
        "confidence": 0.64,
        "conflict_state": "LOW_CONFLICT",
        "caution_state": {
            "level": "CAUTION",
            "flags": ["SESSION_OPENING_DRIVE_MACRO_CAUTION"],
            "freeze_suggestion": False,
        },
        "module_vector": {
            "REGIME": {"raw_score": 0.72, "direction": "BULL", "confidence": 0.72},
            "OPTIONS": {"raw_score": -0.15, "direction": "BEAR", "confidence": 0.48},
            "GLOBAL": {"raw_score": 0.58, "direction": "BULL", "confidence": 0.68},
            "KRONOS": {"raw_score": 0.61, "direction": "BULL", "confidence": 0.65},
            "VIX_REGIME": {"raw_score": 0.42, "direction": "BULL", "confidence": 0.71},
            "PCR": {"raw_score": 0.21, "direction": "BULL", "confidence": 0.55},
            "OI_CHANGE": {"raw_score": -0.08, "direction": "BEAR", "confidence": 0.42},
            "DATA_QUALITY": {"is_guard": True, "quality_state": "GOOD"},
        },
    }


def build_dummy_market_data() -> dict:
    """Create a small market-data packet for message header testing."""
    return {
        "symbol": "NIFTY",
        "price": 24350,
        "timestamp": "2026-06-06T11:30:00",
        "session_state": "EARLY_TREND",
    }


def main() -> None:
    """Run formatter and dry-run send checks."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    reporter = GreyTelegramLiveReporter(enabled=False)
    composite = build_dummy_composite()
    market_data = build_dummy_market_data()

    message = reporter._format_message(composite, market_data)
    print(message)

    assert "GREY | 11:30 AM | NIFTY 24,350" in message
    assert "MODULE SCORES:" in message
    assert "REGIME" in message
    assert "OPTIONS" in message
    assert "COMPOSITE: +3.7" in message
    assert "DIRECTION: BULL" in message
    assert "CONFLICT: LOW_CONFLICT" in message
    assert "VERDICT:" in message
    assert "Put selling" in message
    assert "CAUTION:" in message

    result = reporter.send_live_signal(composite, market_data)
    assert result["dry_run"] is True
    assert result["sent"] is False
    assert "message" in result

    assert "Strong Bullish" in reporter._verdict_from_signal("BULL", 0.70, "LOW_CONFLICT")["headline"]
    assert "Mildly Bearish" in reporter._verdict_from_signal("BEAR", 0.55, "LOW_CONFLICT")["headline"]
    assert "No Clear Direction" in reporter._verdict_from_signal("NEUTRAL", 0.90, "LOW_CONFLICT")["headline"]
    assert "Modules disagreeing sharply" in reporter._verdict_from_signal("BULL", 0.80, "HIGH_CONFLICT")["details"][-1]

    print("\ntelegram live reporter OK")


if __name__ == "__main__":
    main()
