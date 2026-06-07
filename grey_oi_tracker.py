"""
Open-interest baseline tracker for GREY.

This tracker stores OI seen near market open and calculates percentage change
from that baseline during the day.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


class GreyOiTracker:
    """Track call/put OI change from market-open baseline."""

    def __init__(self, storage_path: str | Path = "data/live_cache/oi_baselines.json") -> None:
        # Store baseline on disk so restarts during the day do not lose context.
        self.storage_path = Path(storage_path)

    def update_and_calculate(
        self,
        symbol: str,
        current_context: Mapping[str, Any],
        *,
        dt: datetime | None = None,
    ) -> dict:
        """Update latest OI and return percent change from today's baseline."""
        try:
            # Normalize timestamp and symbol keys.
            current_dt = dt or datetime.now()
            symbol_key = str(symbol or "NIFTY").upper()
            day_key = current_dt.date().isoformat()

            # Read current totals from PCR/option context.
            current_call_oi = self._to_float(current_context.get("call_oi_total"))
            current_put_oi = self._to_float(current_context.get("put_oi_total"))
            current_atm_call_oi = self._to_float(current_context.get("atm_call_oi"))
            current_atm_put_oi = self._to_float(current_context.get("atm_put_oi"))

            # Missing total OI means there is nothing useful to track.
            if current_call_oi is None or current_put_oi is None:
                return self._empty_result("Missing call_oi_total or put_oi_total.")

            # Load or initialize today's baseline.
            store = self._load_store()
            symbol_store = store.setdefault(symbol_key, {})
            baseline = symbol_store.get(day_key)
            baseline_initialized = False
            if not baseline:
                baseline = {
                    "baseline_time": current_dt.isoformat(),
                    "call_oi_total": current_call_oi,
                    "put_oi_total": current_put_oi,
                    "atm_call_oi": current_atm_call_oi,
                    "atm_put_oi": current_atm_put_oi,
                }
                symbol_store.clear()
                symbol_store[day_key] = baseline
                baseline_initialized = True

            # Calculate percentage change versus baseline.
            result = {
                "call_oi_change_pct": self._pct_change(current_call_oi, baseline.get("call_oi_total")),
                "put_oi_change_pct": self._pct_change(current_put_oi, baseline.get("put_oi_total")),
                "atm_call_oi_change": self._pct_change(current_atm_call_oi, baseline.get("atm_call_oi")),
                "atm_put_oi_change": self._pct_change(current_atm_put_oi, baseline.get("atm_put_oi")),
                "oi_baseline_time": baseline.get("baseline_time"),
                "oi_latest_time": current_dt.isoformat(),
                "baseline_initialized": baseline_initialized,
                "oi_tracker_status": "OK",
            }

            # Save latest values for audit/debugging.
            symbol_store[day_key]["latest"] = {
                "timestamp": current_dt.isoformat(),
                "call_oi_total": current_call_oi,
                "put_oi_total": current_put_oi,
                "atm_call_oi": current_atm_call_oi,
                "atm_put_oi": current_atm_put_oi,
                "call_oi_change_pct": result["call_oi_change_pct"],
                "put_oi_change_pct": result["put_oi_change_pct"],
                "atm_call_oi_change": result["atm_call_oi_change"],
                "atm_put_oi_change": result["atm_put_oi_change"],
            }
            self._write_store(store)
            return result
        except Exception as exc:
            # Return neutral changes instead of breaking live GREY.
            return self._empty_result(f"OI tracker failed safely: {exc}")

    def _load_store(self) -> dict:
        """Load OI baseline JSON store."""
        try:
            if not self.storage_path.exists():
                return {}
            return json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_store(self, store: Mapping[str, Any]) -> None:
        """Write OI baseline JSON store."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(json.dumps(dict(store), indent=2, default=str), encoding="utf-8")
        except Exception:
            return

    @staticmethod
    def _pct_change(current: float | None, baseline: Any) -> float | None:
        """Calculate percentage change from baseline."""
        base = GreyOiTracker._to_float(baseline)
        if current is None or base is None or base == 0:
            return None
        return round((float(current) - base) / base * 100.0, 3)

    @staticmethod
    def _empty_result(reason: str) -> dict:
        """Return safe OI values when tracking is unavailable."""
        return {
            "call_oi_change_pct": 0.0,
            "put_oi_change_pct": 0.0,
            "atm_call_oi_change": None,
            "atm_put_oi_change": None,
            "oi_baseline_time": None,
            "oi_latest_time": None,
            "baseline_initialized": False,
            "oi_tracker_status": "UNAVAILABLE",
            "oi_tracker_error": reason,
        }

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely parse numeric OI values."""
        if value is None:
            return None
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None


__all__ = ["GreyOiTracker"]
