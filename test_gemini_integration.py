"""Integration checks for GREY Gemini reasoning."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager

from grey_enhanced_phase1_engine import GreyEnhancedPhase1Engine
from grey_gemini_reasoning_engine import GreyGeminiReasoningEngine


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DUMMY_CONTEXT = {
    "price": 24350,
    "atr": 180,
    "range": 150,
    "latest_news": "RBI rate decision next week",
    "twitter_sentiment": -0.65,
    "surprise": 0.3,
    "put_wall": 5000,
    "call_wall": 2000,
    "pcr": 1.2,
    "unusual_oi": "Puts being sold",
    "gift_nifty": 0.5,
    "us_futures": 0.0,
    "vix": 15.2,
    "fii_flow": 200,
    "spread": 2,
    "volume_profile": "Heavy at 24,350",
    "aggressiveness": "Sellers in control",
}


VALID_DECISIONS = {
    "STRONG_BULL",
    "MILD_BULL",
    "MILD_BEAR",
    "STRONG_BEAR",
    "WAIT_FOR_CLARITY",
    "NEUTRAL",
    "NEUTRAL_SETUP",
    "FALLBACK_TO_RULES",
}


@contextmanager
def env_override(**values):
    old_values = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_initialization() -> None:
    with env_override(GOOGLE_GEMINI_API_KEY="", GREY_GEMINI_ENABLED="False"):
        engine = GreyGeminiReasoningEngine()
        assert engine.model_name == "gemini-2.0-flash"
        assert engine.enabled is False
    print("\u2713 test_initialization")


def test_dummy_mode() -> None:
    with env_override(GOOGLE_GEMINI_API_KEY="", GREY_GEMINI_ENABLED="False"):
        engine = GreyGeminiReasoningEngine()
        output = engine.analyze_market(DUMMY_CONTEXT)
        assert output["reasoning"]
        assert output["decision"] in VALID_DECISIONS
        assert 0.0 <= output["confidence"] <= 1.0
    print("\u2713 test_dummy_mode")


def test_fallback() -> None:
    with env_override(GOOGLE_GEMINI_API_KEY="", GREY_GEMINI_ENABLED="True"):
        engine = GreyGeminiReasoningEngine()
        output = engine.analyze_market(DUMMY_CONTEXT)
        assert output["enabled"] is False
        assert output["decision"] == "FALLBACK_TO_RULES"
    print("\u2713 test_fallback")


def test_formatting() -> None:
    engine = GreyGeminiReasoningEngine()
    prompt = engine._format_prompt(DUMMY_CONTEXT)
    assert "PRICE DATA" in prompt
    assert "OPTIONS POSITIONING" in prompt
    assert "MACRO CONTEXT" in prompt
    assert "MICROSTRUCTURE" in prompt
    assert "Return only JSON" in prompt
    print("\u2713 test_formatting")


def test_decision_extraction() -> None:
    engine = GreyGeminiReasoningEngine()
    assert engine._extract_decision('{"decision":"STRONG_BULL","confidence":0.8,"reasoning":"trend"}') == "STRONG_BULL"
    assert engine._extract_decision('{"decision":"MILD_BEAR","confidence":0.6,"reasoning":"pressure"}') == "MILD_BEAR"
    assert engine._extract_decision("strong bull setup, buy dips") == "NEUTRAL"
    print("\u2713 test_decision_extraction")


def test_confidence_extraction() -> None:
    engine = GreyGeminiReasoningEngine()
    assert engine._extract_confidence('{"decision":"NEUTRAL","confidence":0.72,"reasoning":"balanced"}') == 0.72
    assert engine._extract_confidence('{"decision":"NEUTRAL","confidence":1.5,"reasoning":"clamped"}') == 1.0
    assert engine._extract_confidence("balanced view") == 0.0
    print("\u2713 test_confidence_extraction")


def test_integration() -> None:
    with env_override(GREY_GEMINI_ENABLED="True", GOOGLE_GEMINI_API_KEY=""):
        engine = GreyEnhancedPhase1Engine(dummy_mode=True)
        result = engine.run_once()
        gemini = result["gemini_reasoning"]
        assert gemini["decision"] in VALID_DECISIONS
        assert "gemini_vs_claude" in result
        assert "gemini_vs_claude" in result["enhanced_signal"]
    print("\u2713 test_integration")


if __name__ == "__main__":
    test_initialization()
    test_dummy_mode()
    test_fallback()
    test_formatting()
    test_decision_extraction()
    test_confidence_extraction()
    test_integration()
    print("")
    print("gemini integration OK")
