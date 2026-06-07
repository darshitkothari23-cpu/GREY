"""
Options flow monitor for GREY 2.0.

The monitor analyses supplied option-chain rows, detects unusual lot-sized
activity, tracks OI change by strike, and labels put/call walls. It does not
fetch data or place orders.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


class GreyOptionsFlowMonitor:
    """Analyse real-time option chain rows for flow and positioning alerts."""

    def __init__(
        self,
        *,
        snapshot_path: str | Path | None = None,
        lot_size: int | None = None,
        unusual_lot_threshold: int = 100,
        cache_seconds: int | None = None,
        dummy_mode: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.snapshot_path = Path(snapshot_path or "data/live_cache/options_flow_snapshot.json")
        self.lot_size = int(lot_size or os.getenv("GREY_NIFTY_LOT_SIZE", "75"))
        self.unusual_lot_threshold = unusual_lot_threshold
        self.cache_seconds = int(cache_seconds or os.getenv("GREY_OPTIONS_FLOW_CACHE_SECONDS", "60"))
        self.dummy_mode = dummy_mode
        self.logger = logger or logging.getLogger(__name__)

    def analyze(
        self,
        option_rows: list[dict] | None = None,
        *,
        spot_price: float | None = None,
        timestamp: datetime | None = None,
    ) -> dict:
        """Return flow score, walls, OI change rates, and unusual alerts."""
        rows = option_rows or ([] if not self.dummy_mode else self._dummy_rows())
        now = timestamp or datetime.now(timezone.utc)
        if not rows:
            return self._empty_packet("INSUFFICIENT_DATA", "No option-chain rows supplied.")

        previous = self._read_snapshot()
        normalized = [self._normalize_row(row, spot_price) for row in rows if isinstance(row, Mapping)]
        normalized = [row for row in normalized if row]
        if not normalized:
            return self._empty_packet("INSUFFICIENT_DATA", "No usable option-chain rows supplied.")

        alerts = self._unusual_alerts(normalized)
        oi_changes = self._oi_change_rates(normalized, previous)
        put_walls = self._walls(normalized, "PE")
        call_walls = self._walls(normalized, "CE")
        score = self._flow_score(normalized, put_walls, call_walls, alerts)
        confidence = min(1.0, 0.35 + min(0.45, len(normalized) / 80.0) + min(0.20, len(alerts) * 0.04))
        smart_positioning = self._smart_positioning(score, alerts, put_walls, call_walls)

        packet = {
            "module_id": "OPTIONS_FLOW",
            "score": round(score, 3),
            "direction": self._direction(score),
            "confidence": round(confidence, 3),
            "status": "ACTIVE",
            "alerts": alerts,
            "put_walls": put_walls,
            "call_walls": call_walls,
            "oi_change_rate_by_strike": oi_changes,
            "smart_positioning": smart_positioning,
            "top_driver": smart_positioning,
            "updated_at": now.isoformat(),
        }
        self._write_snapshot(normalized, now)
        return packet

    def _normalize_row(self, row: Mapping[str, Any], spot_price: float | None) -> dict | None:
        strike = self._to_float(row.get("strike"))
        option_type = str(row.get("option_type") or row.get("type") or "").upper()
        oi = self._to_float(row.get("oi") or row.get("open_interest")) or 0.0
        volume = self._to_float(row.get("volume") or row.get("traded_volume")) or 0.0
        if strike is None or option_type not in {"CE", "PE"}:
            return None
        return {
            "strike": strike,
            "option_type": option_type,
            "oi": max(0.0, oi),
            "volume": max(0.0, volume),
            "oi_change": self._to_float(row.get("oi_change") or row.get("change_in_oi")) or 0.0,
            "last_traded_qty": self._to_float(row.get("last_traded_qty") or row.get("ltq")) or 0.0,
            "lot_size": int(self._to_float(row.get("lot_size")) or self.lot_size),
            "distance_from_spot_pct": (
                None if not spot_price else round(((strike - spot_price) / spot_price) * 100.0, 3)
            ),
        }

    def _unusual_alerts(self, rows: Iterable[dict]) -> list[dict]:
        alerts = []
        for row in rows:
            lots = row["last_traded_qty"] / max(1, row["lot_size"])
            if lots >= self.unusual_lot_threshold:
                alerts.append({
                    "strike": row["strike"],
                    "option_type": row["option_type"],
                    "lots": round(lots, 1),
                    "message": f"Unusual {row['option_type']} activity above {self.unusual_lot_threshold} lots",
                })
        return alerts

    def _oi_change_rates(self, rows: Iterable[dict], previous: Mapping[str, Any]) -> dict:
        previous_rows = previous.get("rows", {}) if isinstance(previous, Mapping) else {}
        rates = {}
        for row in rows:
            key = self._row_key(row)
            prev_oi = self._to_float(previous_rows.get(key, {}).get("oi")) if isinstance(previous_rows, Mapping) else None
            explicit = row.get("oi_change")
            if prev_oi and prev_oi > 0:
                change_pct = ((row["oi"] - prev_oi) / prev_oi) * 100.0
            elif row["oi"] > 0:
                change_pct = (explicit / row["oi"]) * 100.0
            else:
                change_pct = 0.0
            rates[key] = round(change_pct, 3)
        return rates

    @staticmethod
    def _walls(rows: Iterable[dict], option_type: str) -> list[dict]:
        filtered = [
            {
                "strike": row["strike"],
                "option_type": row["option_type"],
                "wall_weight": row["oi"] * max(1.0, row["volume"]),
                "oi": row["oi"],
                "volume": row["volume"],
                "distance_from_spot_pct": row.get("distance_from_spot_pct"),
            }
            for row in rows
            if row["option_type"] == option_type
        ]
        filtered.sort(key=lambda item: item["wall_weight"], reverse=True)
        return filtered[:3]

    def _flow_score(self, rows: list[dict], put_walls: list[dict], call_walls: list[dict], alerts: list[dict]) -> float:
        put_weight = sum(row["oi"] * max(1.0, row["volume"]) for row in rows if row["option_type"] == "PE")
        call_weight = sum(row["oi"] * max(1.0, row["volume"]) for row in rows if row["option_type"] == "CE")
        total = put_weight + call_weight
        skew_score = 0.0 if total == 0 else ((put_weight - call_weight) / total) * 10.0
        alert_adjustment = 0.0
        for alert in alerts:
            alert_adjustment += 0.35 if alert["option_type"] == "PE" else -0.35
        return self._clamp(skew_score + alert_adjustment, -10.0, 10.0)

    @staticmethod
    def _smart_positioning(score: float, alerts: list[dict], put_walls: list[dict], call_walls: list[dict]) -> str:
        if abs(score) < 2.0:
            return "Mixed or neutral option positioning"
        side = "put support building" if score > 0 else "call resistance building"
        alert_note = " with unusual activity" if alerts else ""
        wall = (put_walls if score > 0 else call_walls)[0] if (put_walls if score > 0 else call_walls) else {}
        strike = f" near {wall.get('strike')}" if wall else ""
        return f"{side}{strike}{alert_note}"

    def _read_snapshot(self) -> dict:
        try:
            if self.snapshot_path.exists():
                with self.snapshot_path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
        except Exception as exc:
            self.logger.warning("Options flow snapshot read failed safely: %s", exc)
        return {}

    def _write_snapshot(self, rows: list[dict], timestamp: datetime) -> None:
        try:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": timestamp.isoformat(),
                "created_at": time.time(),
                "rows": {self._row_key(row): row for row in rows},
            }
            with self.snapshot_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
        except Exception as exc:
            self.logger.warning("Options flow snapshot write failed safely: %s", exc)

    @staticmethod
    def _row_key(row: Mapping[str, Any]) -> str:
        return f"{int(float(row['strike']))}_{row['option_type']}"

    @staticmethod
    def _direction(score: float) -> str:
        if score >= 2.0:
            return "BULL"
        if score <= -2.0:
            return "BEAR"
        return "NEUTRAL"

    @staticmethod
    def _empty_packet(status: str, reason: str) -> dict:
        return {
            "module_id": "OPTIONS_FLOW",
            "score": 0.0,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "status": status,
            "reason": reason,
            "alerts": [],
            "put_walls": [],
            "call_walls": [],
            "oi_change_rate_by_strike": {},
            "smart_positioning": "No reliable options flow context",
            "top_driver": reason,
        }

    @staticmethod
    def _dummy_rows() -> list[dict]:
        return [
            {"strike": 23500, "option_type": "PE", "oi": 200000, "volume": 18000, "last_traded_qty": 9000},
            {"strike": 23700, "option_type": "CE", "oi": 120000, "volume": 9000, "last_traded_qty": 1500},
        ]

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


__all__ = ["GreyOptionsFlowMonitor"]
