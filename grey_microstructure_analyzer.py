"""
Market microstructure analyzer for GREY 2.0.

This module reads supplied quote, depth, and trade fields to estimate short-term
market strength or weakness. It is an analysis component only.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping


class GreyMicrostructureAnalyzer:
    """Analyse bid-ask quality, depth imbalance, and large execution pressure."""

    def __init__(
        self,
        *,
        large_order_threshold_qty: int | None = None,
        dummy_mode: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.large_order_threshold_qty = int(
            large_order_threshold_qty or os.getenv("GREY_LARGE_ORDER_THRESHOLD_QTY", "5000")
        )
        self.dummy_mode = dummy_mode
        self.logger = logger or logging.getLogger(__name__)

    def analyze(self, market_data: Mapping[str, Any] | None = None) -> dict:
        """Return a GREY packet for intraday market plumbing strength."""
        data = dict(market_data or {})
        if self.dummy_mode and not data:
            data = self._dummy_market_data()

        bid = self._to_float(data.get("bid_price"))
        ask = self._to_float(data.get("ask_price"))
        bid_qty = self._to_float(data.get("bid_quantity")) or 0.0
        ask_qty = self._to_float(data.get("ask_quantity")) or 0.0
        buy_volume = self._to_float(data.get("buy_volume")) or 0.0
        sell_volume = self._to_float(data.get("sell_volume")) or 0.0
        trades = data.get("trades") if isinstance(data.get("trades"), list) else []

        mid = None
        spread_pct = None
        spread_score = 0.0
        if bid is not None and ask is not None and bid > 0 and ask >= bid:
            mid = (bid + ask) / 2.0
            spread_pct = ((ask - bid) / mid) * 100.0 if mid else None
            spread_score = self._spread_score(spread_pct)

        depth_imbalance = self._imbalance(bid_qty, ask_qty)
        volume_imbalance = self._imbalance(buy_volume, sell_volume)
        large_orders = self._large_orders(trades)
        large_order_score = self._large_order_score(large_orders)
        raw = (
            depth_imbalance * 3.0
            + volume_imbalance * 4.0
            + spread_score
            + large_order_score
        )
        score = self._clamp(raw, -10.0, 10.0)
        confidence = self._confidence(spread_pct, bid_qty + ask_qty, buy_volume + sell_volume, trades)

        return {
            "module_id": "MICROSTRUCTURE",
            "score": round(score, 3),
            "direction": self._direction(score),
            "confidence": round(confidence, 3),
            "status": "ACTIVE" if confidence > 0 else "INSUFFICIENT_DATA",
            "market_strength": self._strength_label(score),
            "spread_pct": None if spread_pct is None else round(spread_pct, 4),
            "depth_imbalance": round(depth_imbalance, 3),
            "volume_imbalance": round(volume_imbalance, 3),
            "large_order_events": large_orders,
            "top_driver": self._top_driver(depth_imbalance, volume_imbalance, spread_pct, large_orders),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _large_orders(self, trades: list[dict]) -> list[dict]:
        events = []
        for trade in trades:
            if not isinstance(trade, Mapping):
                continue
            qty = self._to_float(trade.get("quantity") or trade.get("qty")) or 0.0
            if qty < self.large_order_threshold_qty:
                continue
            side = str(trade.get("side") or "UNKNOWN").upper()
            events.append({
                "side": side,
                "quantity": qty,
                "price": self._to_float(trade.get("price")),
                "message": f"Large {side} execution of {int(qty)} units",
            })
        return events[:10]

    def _large_order_score(self, events: list[dict]) -> float:
        score = 0.0
        for event in events:
            side = event.get("side")
            score += 0.75 if side == "BUY" else -0.75 if side == "SELL" else 0.0
        return self._clamp(score, -2.0, 2.0)

    @staticmethod
    def _spread_score(spread_pct: float | None) -> float:
        if spread_pct is None:
            return 0.0
        if spread_pct <= 0.01:
            return 0.75
        if spread_pct <= 0.03:
            return 0.25
        if spread_pct >= 0.10:
            return -1.25
        return -0.25

    @staticmethod
    def _imbalance(left: float, right: float) -> float:
        total = left + right
        if total <= 0:
            return 0.0
        return (left - right) / total

    def _confidence(self, spread_pct: float | None, depth_total: float, volume_total: float, trades: list) -> float:
        confidence = 0.0
        if spread_pct is not None:
            confidence += 0.25
        if depth_total > 0:
            confidence += 0.25
        if volume_total > 0:
            confidence += 0.30
        if trades:
            confidence += 0.20
        return self._clamp(confidence, 0.0, 1.0)

    @staticmethod
    def _direction(score: float) -> str:
        if score >= 2.0:
            return "BULL"
        if score <= -2.0:
            return "BEAR"
        return "NEUTRAL"

    @staticmethod
    def _strength_label(score: float) -> str:
        if score >= 5.0:
            return "STRONG_BULLISH"
        if score >= 2.0:
            return "BULLISH"
        if score <= -5.0:
            return "STRONG_BEARISH"
        if score <= -2.0:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _top_driver(
        depth_imbalance: float,
        volume_imbalance: float,
        spread_pct: float | None,
        large_orders: list[dict],
    ) -> str:
        drivers = {
            "depth imbalance": abs(depth_imbalance),
            "volume imbalance": abs(volume_imbalance),
            "large orders": 0.50 if large_orders else 0.0,
            "spread quality": 0.25 if spread_pct is not None else 0.0,
        }
        return max(drivers, key=drivers.get)

    @staticmethod
    def _dummy_market_data() -> dict:
        return {
            "bid_price": 23539.5,
            "ask_price": 23540.5,
            "bid_quantity": 18000,
            "ask_quantity": 11000,
            "buy_volume": 145000,
            "sell_volume": 96000,
            "trades": [{"side": "BUY", "quantity": 7000, "price": 23540.0}],
        }

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))


__all__ = ["GreyMicrostructureAnalyzer"]
