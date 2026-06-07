"""Smoke test for the GREY 2.0 enhanced intelligence layer."""

from __future__ import annotations

from grey_enhanced_phase1_engine import GreyEnhancedPhase1Engine


def test_enhanced_engine_dummy_cycle() -> None:
    market_data = {
        "symbol": "NIFTY",
        "price": 23540.0,
        "price_change_from_open": 78.0,
        "atr_14": 62.0,
        "volatility_ratio": 0.96,
        "put_wall_weight": 8_500_000,
        "call_wall_weight": 1_200_000,
        "ivp": 0.45,
        "is_expiry": False,
        "bid_price": 23539.5,
        "ask_price": 23540.5,
        "bid_quantity": 18_000,
        "ask_quantity": 11_000,
        "buy_volume": 145_000,
        "sell_volume": 96_000,
    }
    option_rows = [
        {
            "strike": 23500,
            "option_type": "PE",
            "oi": 212_000,
            "oi_change": 26_500,
            "volume": 18_200,
            "last_traded_qty": 8_400,
            "lot_size": 75,
        },
        {
            "strike": 23700,
            "option_type": "CE",
            "oi": 124_000,
            "oi_change": 7_200,
            "volume": 9_100,
            "last_traded_qty": 2_250,
            "lot_size": 75,
        },
    ]
    news_items = [
        {
            "title": "NIFTY holds gains as banks lead index advance",
            "summary": "Banking stocks remain firm while volatility stays contained.",
            "source": "dummy-news",
        }
    ]
    social_items = [
        {"source": "twitter", "text": "NIFTY breadth looks strong today"},
        {"source": "stocktwits", "text": "Options flow still bullish but watch resistance"},
    ]

    engine = GreyEnhancedPhase1Engine(dummy_mode=True)
    result = engine.run_once(
        symbol="NIFTY",
        market_data=market_data,
        option_rows=option_rows,
        news_items=news_items,
        social_items=social_items,
    )

    assert result["symbol"] == "NIFTY"
    assert result["enhanced_signal"]["direction_bias"] in {"BULL", "BEAR", "NEUTRAL"}
    assert result["enhanced_signal"]["confidence"] > 0.0
    assert isinstance(result["enhanced_signal"]["module_vector"], dict)
    assert "OPTIONS_FLOW" in result["module_outputs"]
    assert "MICROSTRUCTURE" in result["module_outputs"]
    assert "SENTIMENT" in result["module_outputs"]
    assert "REASONING" in result["module_outputs"]
    assert "reasoning_summary" in result["enhanced_signal"]


if __name__ == "__main__":
    test_enhanced_engine_dummy_cycle()
    print("grey2 enhanced OK")
