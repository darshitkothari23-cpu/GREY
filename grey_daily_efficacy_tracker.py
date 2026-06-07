"""
Daily efficacy tracker for GREY.

This file evaluates whether GREY module signals warned about important
intraday market moves before those moves happened.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from grey_ev_calculator import GreyEVCalculator


class GreyDailyEfficacyTracker:
    """Build an end-of-day GREY efficacy report from signals and OHLCV candles."""

    DEFAULT_CONFIG = {
        "early_warning_minutes": 30,
        "trend_candles": 3,
        "rally_crash_threshold_pct": 0.005,
        "reversal_leg_threshold_pct": 0.003,
        "breakout_lookback_candles": 4,
        "breakout_threshold_pct": 0.003,
        "consolidation_candles": 2,
        "consolidation_range_pct": 0.0025,
        "consolidation_exit_threshold_pct": 0.007,
        "trading_hours": "09:15-15:30",
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        # Start with safe default thresholds for 15-minute NIFTY candles.
        self.config = dict(self.DEFAULT_CONFIG)

        # Allow callers to override thresholds without editing this file.
        if config:
            self.config.update(dict(config))

    def build_report(
        self,
        *,
        signal_log: str | Path | Iterable[Mapping[str, Any]],
        ohlcv_data: str | Path | pd.DataFrame,
        report_date: date | str | None = None,
        symbol: str = "NIFTY",
        market_events: list[dict] | None = None,
    ) -> dict:
        """Build the full daily efficacy report."""
        try:
            # Load and clean candle data first because it determines the report date.
            candles = self.load_ohlcv(ohlcv_data)

            # Choose a report date from the caller, or from the latest candle.
            effective_date = self._resolve_report_date(report_date, candles)

            # Keep only candles from the report day.
            day_candles = self._filter_date(candles, effective_date)

            # Load and expand GREY Phase 1 signals into module-level records.
            raw_signals = self._read_signal_records(signal_log)
            signals = self.load_signals(raw_signals, effective_date, symbol)

            # Identify market moves automatically unless the caller provides them.
            moves = market_events or self.identify_market_moves(day_candles)

            # Score whether modules warned before each detected move.
            evaluated_moves = self.evaluate_moves(signals, moves)

            # Score each module across all evaluated moves.
            scorecard = self.module_performance_scorecard(evaluated_moves)

            # Build a plain-English summary and insight section.
            summary = self._summary(evaluated_moves)
            summary.update(self._comprehensive_metrics(raw_signals, day_candles))
            ab_test_results = self.calculate_ab_test_results(raw_signals)
            market_conditions = self._market_conditions(raw_signals, day_candles)
            insights = self._daily_insights(summary, scorecard)

            # Return a dashboard- and JSON-friendly report structure.
            return {
                "report_date": effective_date.isoformat(),
                "symbol": symbol,
                "trading_hours": self.config["trading_hours"],
                "summary": summary,
                "market_moves": evaluated_moves,
                "module_performance_scorecard": scorecard,
                "module_performance": scorecard,
                "ab_test_results": ab_test_results,
                "market_conditions": market_conditions,
                "daily_insights": insights,
            }
        except Exception as exc:
            # Return an error report instead of crashing a scheduled task.
            fallback_date = self._date_to_text(report_date) or date.today().isoformat()
            return {
                "report_date": fallback_date,
                "symbol": symbol,
                "trading_hours": self.config["trading_hours"],
                "summary": {
                    "total_moves_identified": 0,
                    "moves_with_early_warning": 0,
                    "efficacy_score": 0.0,
                    "directional_accuracy": 0.0,
                    "range_bound_accuracy": 0.0,
                    "directional_accuracy_pct": 0.0,
                    "range_bound_accuracy_pct": 0.0,
                    "atr_adjusted_range_accuracy_pct": 0.0,
                    "simulated_ev_after_costs": 0.0,
                    "remark": f"Daily efficacy report failed safely: {exc}",
                },
                "market_moves": [],
                "module_performance_scorecard": {},
                "module_performance": {},
                "ab_test_results": {},
                "market_conditions": {},
                "daily_insights": {
                    "best_performing_module": None,
                    "worst_performing_module": None,
                    "system_efficacy": "0.0/10",
                    "system_remark": f"Could not build report: {exc}",
                    "recommendations": ["Check signal log path and OHLCV CSV path."],
                },
                "error": str(exc),
            }

    def load_signals(
        self,
        signal_log: str | Path | Iterable[Mapping[str, Any]],
        report_date: date,
        symbol: str,
    ) -> list[dict]:
        """Load GREY Phase 1 signals and expand module_vector into module records."""
        try:
            # Read JSONL records from disk or accept an already-loaded iterable.
            raw_records = self._read_signal_records(signal_log)

            # Expand each Phase 1 signal into module-level calls.
            module_records: list[dict] = []
            for signal in raw_records:
                timestamp = self._parse_dt(signal.get("timestamp"))
                if timestamp is None or timestamp.date() != report_date:
                    continue
                if symbol and str(signal.get("symbol", symbol)).upper() != symbol.upper():
                    continue

                # Include the composite GREY view as its own review line.
                module_records.append({
                    "timestamp": timestamp,
                    "module": "COMPOSITE",
                    "direction": str(signal.get("direction_bias", "NEUTRAL")).upper(),
                    "confidence": self._clamp_unit(signal.get("confidence")),
                    "signal_id": signal.get("timestamp"),
                    "session_state": signal.get("session_state"),
                })

                # Include every module contribution from the saved module vector.
                module_vector = signal.get("module_vector", {})
                if not isinstance(module_vector, Mapping):
                    continue
                for module_id, vector in module_vector.items():
                    if not isinstance(vector, Mapping) or vector.get("is_guard"):
                        continue
                    module_records.append({
                        "timestamp": timestamp,
                        "module": str(module_id).upper(),
                        "direction": str(vector.get("direction", "NEUTRAL")).upper(),
                        "confidence": self._clamp_unit(vector.get("confidence")),
                        "signal_id": signal.get("timestamp"),
                        "session_state": signal.get("session_state"),
                    })

            # Sort records so lead-time calculations are stable and readable.
            module_records.sort(key=lambda item: item["timestamp"])
            return module_records
        except Exception:
            # Signal loading should fail loudly to the caller's safe wrapper.
            raise

    def load_ohlcv(self, ohlcv_data: str | Path | pd.DataFrame) -> pd.DataFrame:
        """Load and normalize OHLCV candles."""
        try:
            # Accept a DataFrame directly for tests and replay workflows.
            if isinstance(ohlcv_data, pd.DataFrame):
                df = ohlcv_data.copy()
            else:
                # Otherwise read a CSV file from disk.
                path = Path(ohlcv_data)
                if not path.exists():
                    raise FileNotFoundError(f"OHLCV file not found: {path}")
                df = pd.read_csv(path)

            # Accept either timestamp or timestamps column names.
            if "timestamp" not in df.columns and "timestamps" in df.columns:
                df = df.rename(columns={"timestamps": "timestamp"})
            if "timestamp" not in df.columns:
                raise ValueError("OHLCV data must include timestamp or timestamps column.")

            # Convert timestamp and candle columns into safe typed values.
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            for column in ("open", "high", "low", "close"):
                if column not in df.columns:
                    raise ValueError(f"OHLCV data is missing required column: {column}")
                df[column] = pd.to_numeric(df[column], errors="coerce")
            if "volume" not in df.columns:
                df["volume"] = 0.0
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)

            # Drop broken rows and sort by time.
            df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
            df = df.sort_values("timestamp").reset_index(drop=True)
            if df.empty:
                raise ValueError("OHLCV data has no usable candle rows.")
            return df
        except Exception:
            # Candle loading should fail loudly to the caller's safe wrapper.
            raise

    def calculate_directional_accuracy(
        self,
        signals: Iterable[Mapping[str, Any]],
        ohlcv_data: str | Path | pd.DataFrame,
    ) -> float:
        """Measure whether BULL/BEAR signals matched the later close direction.

        Inputs are the raw GREY signal records and OHLCV candles. The method
        returns a percentage from 0.0 to 100.0 and skips neutral, incomplete, or
        unparseable records instead of crashing the report job.
        """
        try:
            candles = self.load_ohlcv(ohlcv_data)
            total = 0
            correct = 0
            for signal in signals:
                direction = str(signal.get("direction_bias") or signal.get("direction") or "").upper()
                if direction not in {"BULL", "BEAR"}:
                    continue

                start_dt = self._parse_dt(signal.get("timestamp"))
                if start_dt is None:
                    continue

                entry_price = self._to_float(signal.get("entry_price") or signal.get("price"))
                exit_price = self._exit_price_for_signal(signal, candles, start_dt)
                if entry_price is None or exit_price is None or entry_price <= 0:
                    continue

                actual_move = exit_price - entry_price
                total += 1
                if (direction == "BULL" and actual_move > 0) or (direction == "BEAR" and actual_move < 0):
                    correct += 1

            return round((correct / total) * 100.0, 2) if total else 0.0
        except Exception:
            return 0.0

    def calculate_range_bound_accuracy(
        self,
        signals: Iterable[Mapping[str, Any]],
        ohlcv_data: str | Path | pd.DataFrame,
    ) -> float:
        """Measure whether actual highs/lows stayed inside predicted bounds.

        This is the Iron Condor viability metric. Each raw signal must provide
        predicted_high and predicted_low either at the top level or inside a
        Kronos packet. A period is correct when actual_high <= predicted_high
        and actual_low >= predicted_low during the signal evaluation window.
        """
        try:
            candles = self.load_ohlcv(ohlcv_data)
            total = 0
            correct = 0
            for signal in signals:
                start_dt = self._parse_dt(signal.get("timestamp"))
                if start_dt is None:
                    continue

                predicted_high = self._predicted_bound(signal, "predicted_high")
                predicted_low = self._predicted_bound(signal, "predicted_low")
                if predicted_high is None or predicted_low is None:
                    continue

                window = self._signal_candle_window(signal, candles, start_dt)
                if window.empty:
                    continue

                actual_high = self._to_float(window["high"].max())
                actual_low = self._to_float(window["low"].min())
                if actual_high is None or actual_low is None:
                    continue

                total += 1
                if actual_high <= predicted_high and actual_low >= predicted_low:
                    correct += 1

            return round((correct / total) * 100.0, 2) if total else 0.0
        except Exception:
            return 0.0

    def calculate_atr_adjusted_range_accuracy(
        self,
        signals: Iterable[Mapping[str, Any]],
        ohlcv_data: str | Path | pd.DataFrame,
        *,
        atr_multiplier: float = 1.5,
    ) -> float:
        """Measure whether actual range fit inside open +/- ATR-adjusted bounds."""
        try:
            candles = self._with_atr_14(self.load_ohlcv(ohlcv_data))
            total = 0
            correct = 0
            for signal in signals:
                start_dt = self._parse_dt(signal.get("timestamp"))
                if start_dt is None:
                    continue
                window = self._signal_candle_window(signal, candles, start_dt)
                if window.empty:
                    continue
                first = window.iloc[0]
                open_price = self._to_float(first.get("open"))
                atr_14 = self._to_float(first.get("atr_14"))
                if open_price is None or atr_14 is None or atr_14 <= 0:
                    continue
                dynamic_high = open_price + (float(atr_multiplier) * atr_14)
                dynamic_low = open_price - (float(atr_multiplier) * atr_14)
                total += 1
                if float(window["high"].max()) <= dynamic_high and float(window["low"].min()) >= dynamic_low:
                    correct += 1
            return round((correct / total) * 100.0, 2) if total else 0.0
        except Exception:
            return 0.0

    def calculate_ab_test_results(self, signals: Iterable[Mapping[str, Any]]) -> dict:
        """Calculate baseline and Gemini A/B accuracy from signal records."""
        baseline_total = baseline_correct = 0
        gemini_total = gemini_correct = 0
        for signal in signals:
            ab = signal.get("parallel_ab_test") or signal.get("ab_test") or {}
            if not isinstance(ab, Mapping):
                continue
            baseline_flag = ab.get("baseline_correct")
            gemini_flag = ab.get("gemini_correct")
            if baseline_flag is not None:
                baseline_total += 1
                baseline_correct += 1 if bool(baseline_flag) else 0
            if gemini_flag is not None:
                gemini_total += 1
                gemini_correct += 1 if bool(gemini_flag) else 0

        baseline_accuracy = round((baseline_correct / baseline_total) * 100.0, 2) if baseline_total else 0.0
        gemini_accuracy = round((gemini_correct / gemini_total) * 100.0, 2) if gemini_total else 0.0
        return {
            "baseline_accuracy_pct": baseline_accuracy,
            "gemini_accuracy_pct": gemini_accuracy,
            "gemini_accuracy_lift_pct": round(gemini_accuracy - baseline_accuracy, 2),
            "baseline_samples": baseline_total,
            "gemini_samples": gemini_total,
        }

    def identify_market_moves(self, candles: pd.DataFrame) -> list[dict]:
        """Detect rallies, crashes, reversals, breakouts, and consolidation exits."""
        try:
            # Work on a clean local copy of the candle data.
            df = candles.copy().sort_values("timestamp").reset_index(drop=True)
            moves: list[dict] = []

            # Detect three-candle rallies and crashes.
            moves.extend(self._detect_rallies_and_crashes(df))

            # Detect momentum reversals.
            moves.extend(self._detect_reversals(df))

            # Detect support/resistance breakouts.
            moves.extend(self._detect_breakouts(df))

            # Detect narrow-range exits.
            moves.extend(self._detect_consolidation_exits(df))

            # Remove near-duplicates so the report stays readable.
            return self._dedupe_moves(moves)
        except Exception:
            # Move detection errors should fail loudly to the caller's safe wrapper.
            raise

    def evaluate_moves(self, signals: list[dict], moves: list[dict]) -> list[dict]:
        """Evaluate whether module signals warned before each market move."""
        evaluated = []
        for index, move in enumerate(sorted(moves, key=lambda item: item["start_dt"]), start=1):
            # Look back 30 minutes before the move starts.
            start_dt = move["start_dt"]
            window_start = start_dt - timedelta(minutes=self.config["early_warning_minutes"])

            # Select module records inside the warning window.
            pre_signals = [
                signal for signal in signals
                if window_start <= signal["timestamp"] < start_dt
            ]

            # Turn module signals into aligned/wrong/missed rows.
            signal_rows = [
                self._signal_alignment_row(signal, move)
                for signal in pre_signals
            ]

            # Build one latest-call breakdown per module.
            module_breakdown = self._module_breakdown(pre_signals, move)

            # Calculate early-warning fields.
            aligned_signals = [row for row in signal_rows if row["status"] == "ALIGNED"]
            early_warning_given = bool(aligned_signals)
            early_warning_confidence = self._average(row["confidence"] for row in aligned_signals)
            warning_lead_time = self._warning_lead_time(aligned_signals, start_dt)

            # Calculate one 0-10 move efficacy score.
            efficacy_score = self._move_efficacy_score(signal_rows)

            # Return the move in the requested report-friendly shape.
            evaluated.append({
                "move_id": index,
                "type": move["type"],
                "direction": move["direction"],
                "start_time": start_dt.strftime("%H:%M"),
                "start_timestamp": start_dt.isoformat(),
                "magnitude_points": round(move["magnitude_points"], 2),
                "magnitude_pct": round(move["magnitude_pct"] * 100.0, 3),
                "duration_minutes": move["duration_minutes"],
                "signals_before": signal_rows,
                "early_warning_status": "YES" if early_warning_given else "NO",
                "early_warning_given": early_warning_given,
                "early_warning_confidence": round(early_warning_confidence, 3),
                "early_warning_lead_time_minutes": warning_lead_time,
                "module_breakdown": module_breakdown,
                "efficacy_score": round(efficacy_score, 2),
                "remark": self._move_remark(move, early_warning_given, warning_lead_time, module_breakdown),
            })
        return evaluated

    def module_performance_scorecard(self, evaluated_moves: list[dict]) -> dict:
        """Build module-wise accuracy and quality ratings."""
        scorecard: dict[str, dict[str, Any]] = {}
        for move in evaluated_moves:
            for module_id, breakdown in move.get("module_breakdown", {}).items():
                bucket = scorecard.setdefault(module_id, {
                    "total_relevant_calls": 0,
                    "correct": 0,
                    "wrong": 0,
                    "missed": 0,
                    "confidence_values": [],
                    "scores": [],
                })
                bucket["total_relevant_calls"] += 1
                bucket["scores"].append(float(breakdown.get("score", 0.0)))
                bucket["confidence_values"].append(float(breakdown.get("confidence_level", 0.0)))
                status = breakdown.get("status")
                if status == "ALIGNED":
                    bucket["correct"] += 1
                elif status == "WRONG":
                    bucket["wrong"] += 1
                else:
                    bucket["missed"] += 1

        # Convert internal buckets into the report-card structure.
        finalized = {}
        for module_id, bucket in scorecard.items():
            total = bucket["total_relevant_calls"]
            accuracy_pct = (bucket["correct"] / total * 100.0) if total else 0.0
            avg_confidence = self._average(bucket["confidence_values"])
            avg_score = self._average(bucket["scores"])
            finalized[module_id] = {
                "total_relevant_calls": total,
                "correct": bucket["correct"],
                "wrong": bucket["wrong"],
                "missed": bucket["missed"],
                "accuracy_pct": round(accuracy_pct, 2),
                "avg_confidence": round(avg_confidence, 3),
                "average_score": round(avg_score, 2),
                "quality_rating": self._quality_rating(accuracy_pct),
                "notes": self._module_notes(module_id, accuracy_pct),
            }
        return finalized

    def save_report(self, report: Mapping[str, Any], output_dir: str | Path = "daily_reports") -> Path:
        """Save the JSON report to daily_reports/efficacy_YYYY-MM-DD.json."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        report_date = str(report.get("report_date", date.today().isoformat()))
        report_file = output_path / f"efficacy_{report_date}.json"
        report_file.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return report_file

    def format_pretty_report(self, report: Mapping[str, Any]) -> str:
        """Create a clear console report for a non-technical operator."""
        summary = report.get("summary", {})
        insights = report.get("daily_insights", {})
        lines = [
            "=" * 56,
            f"GREY Daily Efficacy Report - {report.get('report_date')}",
            "=" * 56,
            f"Symbol: {report.get('symbol', 'NIFTY')}",
            f"Trading hours: {report.get('trading_hours')}",
            f"Moves identified: {summary.get('total_moves_identified', 0)}",
            f"Moves with early warning: {summary.get('moves_with_early_warning', 0)}",
            f"System efficacy: {summary.get('efficacy_score', 0.0)}/10",
            f"Directional accuracy: {summary.get('directional_accuracy', 0.0)}%",
            f"Range-bound accuracy: {summary.get('range_bound_accuracy', 0.0)}%",
            f"ATR-adjusted range accuracy: {summary.get('atr_adjusted_range_accuracy_pct', 0.0)}%",
            f"Simulated EV after costs: Rs {summary.get('simulated_ev_after_costs', 0.0)}",
            f"Remark: {summary.get('remark', '')}",
            "",
            "Market Moves:",
        ]
        for move in report.get("market_moves", []):
            lines.append(
                f"- #{move.get('move_id')} {move.get('type')} "
                f"{move.get('start_time')} {move.get('magnitude_pct')}% "
                f"warning={move.get('early_warning_status')} "
                f"score={move.get('efficacy_score')}/10"
            )
        if not report.get("market_moves"):
            lines.append("- No major market moves identified.")

        lines.extend(["", "Module Scorecard:"])
        for module_id, card in report.get("module_performance_scorecard", {}).items():
            lines.append(
                f"- {module_id}: accuracy={card.get('accuracy_pct')}% "
                f"avg_conf={card.get('avg_confidence')} "
                f"rating={card.get('quality_rating')}"
            )
        if not report.get("module_performance_scorecard"):
            lines.append("- No module calls were evaluated.")

        lines.extend([
            "",
            "Daily Insights:",
            f"Best module: {insights.get('best_performing_module')}",
            f"Worst module: {insights.get('worst_performing_module')}",
            f"System remark: {insights.get('system_remark')}",
            "Recommendations:",
        ])
        for recommendation in insights.get("recommendations", []):
            lines.append(f"- {recommendation}")
        lines.append("=" * 56)
        return "\n".join(lines)

    def _detect_rallies_and_crashes(self, df: pd.DataFrame) -> list[dict]:
        """Detect three consecutive rising or falling closes."""
        moves = []
        count = int(self.config["trend_candles"])
        threshold = float(self.config["rally_crash_threshold_pct"])
        for start in range(0, max(0, len(df) - count + 1)):
            window = df.iloc[start:start + count]
            closes = list(window["close"])
            total_move = (closes[-1] - closes[0]) / closes[0]
            if all(closes[i] > closes[i - 1] for i in range(1, len(closes))) and total_move > threshold:
                moves.append(self._move("RALLY", "BULL", window, closes[-1] - closes[0], total_move))
            if all(closes[i] < closes[i - 1] for i in range(1, len(closes))) and total_move < -threshold:
                moves.append(self._move("CRASH", "BEAR", window, closes[-1] - closes[0], total_move))
        return moves

    def _detect_reversals(self, df: pd.DataFrame) -> list[dict]:
        """Detect a momentum direction change."""
        moves = []
        threshold = float(self.config["reversal_leg_threshold_pct"])
        for pivot in range(2, max(2, len(df) - 2)):
            before = df.iloc[pivot - 2:pivot + 1]
            after = df.iloc[pivot:pivot + 3]
            before_move = (before["close"].iloc[-1] - before["close"].iloc[0]) / before["close"].iloc[0]
            after_move = (after["close"].iloc[-1] - after["close"].iloc[0]) / after["close"].iloc[0]
            if abs(before_move) >= threshold and abs(after_move) >= threshold and before_move * after_move < 0:
                direction = "BULL" if after_move > 0 else "BEAR"
                moves.append(self._move("REVERSAL", direction, after, after["close"].iloc[-1] - after["close"].iloc[0], after_move))
        return moves

    def _detect_breakouts(self, df: pd.DataFrame) -> list[dict]:
        """Detect a close breaking recent support or resistance."""
        moves = []
        lookback = int(self.config["breakout_lookback_candles"])
        threshold = float(self.config["breakout_threshold_pct"])
        for index in range(lookback, len(df)):
            recent = df.iloc[index - lookback:index]
            candle = df.iloc[index:index + 1]
            resistance = float(recent["high"].max())
            support = float(recent["low"].min())
            close = float(candle["close"].iloc[0])
            if close > resistance * (1.0 + threshold):
                move_pct = (close - resistance) / resistance
                moves.append(self._move("BREAKOUT", "BULL", candle, close - resistance, move_pct))
            elif close < support * (1.0 - threshold):
                move_pct = (close - support) / support
                moves.append(self._move("BREAKOUT", "BEAR", candle, close - support, move_pct))
        return moves

    def _detect_consolidation_exits(self, df: pd.DataFrame) -> list[dict]:
        """Detect a narrow two-candle range followed by a large move."""
        moves = []
        narrow_count = int(self.config["consolidation_candles"])
        narrow_threshold = float(self.config["consolidation_range_pct"])
        exit_threshold = float(self.config["consolidation_exit_threshold_pct"])
        for index in range(narrow_count, len(df)):
            prior = df.iloc[index - narrow_count:index]
            candle = df.iloc[index:index + 1]
            range_pct = (prior["high"].max() - prior["low"].min()) / prior["close"].mean()
            move_pct = (candle["close"].iloc[0] - prior["close"].iloc[-1]) / prior["close"].iloc[-1]
            if range_pct <= narrow_threshold and abs(move_pct) >= exit_threshold:
                direction = "BULL" if move_pct > 0 else "BEAR"
                moves.append(self._move("CONSOLIDATION_EXIT", direction, candle, candle["close"].iloc[0] - prior["close"].iloc[-1], move_pct))
        return moves

    @staticmethod
    def _move(move_type: str, direction: str, window: pd.DataFrame, points: float, pct: float) -> dict:
        """Create one normalized move record."""
        start_dt = pd.Timestamp(window["timestamp"].iloc[0]).to_pydatetime()
        end_dt = pd.Timestamp(window["timestamp"].iloc[-1]).to_pydatetime()
        if len(window) <= 1:
            duration = 15
        else:
            interval = max(15, int((end_dt - start_dt).total_seconds() // 60))
            duration = interval + 15
        return {
            "type": move_type,
            "direction": direction,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "magnitude_points": float(points),
            "magnitude_pct": float(pct),
            "duration_minutes": duration,
        }

    def _dedupe_moves(self, moves: list[dict]) -> list[dict]:
        """Remove overlapping near-duplicate moves."""
        priority = {
            "RALLY": 1,
            "CRASH": 1,
            "REVERSAL": 2,
            "BREAKOUT": 3,
            "CONSOLIDATION_EXIT": 4,
        }
        sorted_moves = sorted(
            moves,
            key=lambda item: (item["start_dt"], priority.get(item["type"], 9), -abs(item["magnitude_pct"])),
        )
        kept: list[dict] = []
        for move in sorted_moves:
            too_close = any(
                abs((move["start_dt"] - existing["start_dt"]).total_seconds()) < 15 * 60
                and move["direction"] == existing["direction"]
                for existing in kept
            )
            if not too_close:
                kept.append(move)
        return kept

    def _signal_alignment_row(self, signal: Mapping[str, Any], move: Mapping[str, Any]) -> dict:
        """Convert one signal into aligned/wrong/missed status for a move."""
        status = self._alignment_status(signal.get("direction"), move.get("direction"))
        timestamp = signal["timestamp"]
        return {
            "timestamp": timestamp.strftime("%H:%M"),
            "full_timestamp": timestamp.isoformat(),
            "module": signal.get("module"),
            "direction": signal.get("direction", "NEUTRAL"),
            "confidence": round(float(signal.get("confidence", 0.0)), 3),
            "status": status,
            "status_text": self._status_text(status),
            "minutes_before_move": int((move["start_dt"] - timestamp).total_seconds() // 60),
        }

    def _module_breakdown(self, pre_signals: list[dict], move: Mapping[str, Any]) -> dict:
        """Build latest module call breakdown before a move."""
        latest_by_module: dict[str, dict] = {}
        for signal in pre_signals:
            module = str(signal.get("module", "UNKNOWN"))
            if module not in latest_by_module or signal["timestamp"] > latest_by_module[module]["timestamp"]:
                latest_by_module[module] = signal

        breakdown = {}
        for module_id, signal in sorted(latest_by_module.items()):
            status = self._alignment_status(signal.get("direction"), move.get("direction"))
            score = self._status_score(status, signal.get("confidence", 0.0))
            breakdown[module_id] = {
                "was_bullish": signal.get("direction") == "BULL",
                "confidence_level": round(float(signal.get("confidence", 0.0)), 3),
                "accuracy_contribution": round(score, 2),
                "score": round(score, 2),
                "status": status,
                "call_accuracy": self._call_accuracy_text(signal.get("direction"), move.get("type"), move.get("direction"), status),
                "remark": self._module_remark(status),
            }
        return breakdown

    def _summary(self, moves: list[dict]) -> dict:
        """Build top-level daily report summary."""
        total = len(moves)
        warned = sum(bool(move.get("early_warning_given")) for move in moves)
        efficacy = self._average(move.get("efficacy_score", 0.0) for move in moves) if total else 0.0
        return {
            "total_moves_identified": total,
            "moves_with_early_warning": warned,
            "efficacy_score": round(efficacy, 2),
            "remark": f"System gave warnings for {warned}/{total} major moves" if total else "No major moves identified.",
        }

    def _comprehensive_metrics(
        self,
        raw_signals: Iterable[Mapping[str, Any]],
        day_candles: pd.DataFrame,
    ) -> dict:
        """Build all pre-shadow-mode daily efficacy metrics."""
        signals = [dict(signal) for signal in raw_signals]
        directional = self.calculate_directional_accuracy(signals, day_candles)
        kronos_range = self.calculate_range_bound_accuracy(signals, day_candles)
        atr_range = self.calculate_atr_adjusted_range_accuracy(signals, day_candles)
        trade_stats = self._trade_stats(signals)
        ab = self.calculate_ab_test_results(signals)
        win_pct_unit = trade_stats["win_pct"] / 100.0 if trade_stats["total_signals"] else self._env_float("GREY_EXPECTED_WIN_PCT", 0.58)
        avg_profit = trade_stats["avg_profit_per_win_rupees"] or self._env_float("GREY_EXPECTED_PROFIT_PER_TRADE", 2850.0)
        avg_loss = trade_stats["avg_loss_per_loss_rupees"] or self._env_float("GREY_EXPECTED_LOSS_PER_TRADE", 3150.0)
        ev = GreyEVCalculator().calculate_ev(win_pct_unit, avg_profit, avg_loss)
        return {
            "directional_accuracy": directional,
            "range_bound_accuracy": kronos_range,
            "directional_accuracy_pct": directional,
            "range_bound_accuracy_pct": kronos_range,
            "kronos_range_accuracy_pct": kronos_range,
            "atr_adjusted_range_accuracy_pct": atr_range,
            "simulated_ev_after_costs": ev,
            "baseline_accuracy_pct": ab["baseline_accuracy_pct"],
            "gemini_accuracy_pct": ab["gemini_accuracy_pct"],
            "gemini_accuracy_lift_pct": ab["gemini_accuracy_lift_pct"],
            **trade_stats,
        }

    def _trade_stats(self, signals: list[Mapping[str, Any]]) -> dict:
        """Calculate win/loss, drawdown, and Sharpe-style stats from signal PnL."""
        pnls: list[float] = []
        for signal in signals:
            pnl = self._to_float(signal.get("pnl") or signal.get("realized_pnl") or signal.get("simulated_pnl"))
            if pnl is not None:
                pnls.append(pnl)
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl <= 0]
        total = len(pnls)
        win_pct = round((len(wins) / total) * 100.0, 2) if total else 0.0
        loss_pct = round((len(losses) / total) * 100.0, 2) if total else 0.0
        avg_profit = round(sum(wins) / len(wins), 2) if wins else 0.0
        avg_loss = round(abs(sum(losses) / len(losses)), 2) if losses else 0.0
        equity = []
        running = 0.0
        for pnl in pnls:
            running += pnl
            equity.append(running)
        max_dd = self._max_drawdown(equity)
        return {
            "win_pct": win_pct,
            "loss_pct": loss_pct,
            "avg_profit_per_win_rupees": avg_profit,
            "avg_loss_per_loss_rupees": avg_loss,
            "win_loss_ratio": round((avg_profit / avg_loss), 3) if avg_loss else 0.0,
            "max_drawdown_today_rupees": round(max_dd["rupees"], 2),
            "max_drawdown_today_pct": round(max_dd["pct"], 2),
            "sharpe_ratio_today": round(self._sharpe_ratio(pnls), 3),
            "profitable_signals_count": len(wins),
            "losing_signals_count": len(losses),
            "total_signals": total,
        }

    def _market_conditions(self, signals: list[Mapping[str, Any]], candles: pd.DataFrame) -> dict:
        """Build a compact market-condition packet for the report."""
        latest_signal = signals[-1] if signals else {}
        return {
            "india_vix": latest_signal.get("india_vix") or latest_signal.get("vix"),
            "session": latest_signal.get("session_state"),
            "conditions": latest_signal.get("market_conditions") or "not_recorded",
            "candles_evaluated": int(len(candles)),
        }

    @staticmethod
    def _with_atr_14(candles: pd.DataFrame) -> pd.DataFrame:
        """Add a 14-period true-range average column to candle data."""
        df = candles.copy().sort_values("timestamp").reset_index(drop=True)
        previous_close = df["close"].shift(1)
        true_range = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - previous_close).abs(),
                (df["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        df["atr_14"] = true_range.rolling(window=14, min_periods=1).mean()
        return df

    @staticmethod
    def _max_drawdown(equity: list[float]) -> dict:
        """Return max drawdown from an equity list."""
        peak = 0.0
        max_dd = 0.0
        for value in equity:
            peak = max(peak, value)
            max_dd = max(max_dd, peak - value)
        pct = (max_dd / peak * 100.0) if peak > 0 else 0.0
        return {"rupees": max_dd, "pct": pct}

    @staticmethod
    def _sharpe_ratio(pnls: list[float]) -> float:
        """Return simple daily trade-level Sharpe ratio."""
        if len(pnls) < 2:
            return 0.0
        mean = sum(pnls) / len(pnls)
        variance = sum((pnl - mean) ** 2 for pnl in pnls) / (len(pnls) - 1)
        std = math.sqrt(variance)
        return 0.0 if std == 0 else (mean / std) * math.sqrt(len(pnls))

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        """Read a float env setting safely."""
        try:
            return float(os.getenv(name, str(default)) or default)
        except (TypeError, ValueError):
            return default

    def _daily_insights(self, summary: Mapping[str, Any], scorecard: Mapping[str, Any]) -> dict:
        """Build plain-English daily insights."""
        best = self._rank_module(scorecard, best=True)
        worst = self._rank_module(scorecard, best=False)
        efficacy_text = f"{summary.get('efficacy_score', 0.0)}/10"
        recommendations = []
        if best:
            recommendations.append(f"Review whether {best} deserves more trust tomorrow.")
        if worst:
            recommendations.append(f"Inspect {worst}; it lagged or conflicted today.")
        if not recommendations:
            recommendations.append("Collect more signals and candles before changing weights.")
        return {
            "best_performing_module": best,
            "worst_performing_module": worst,
            "system_efficacy": efficacy_text,
            "system_remark": summary.get("remark", ""),
            "recommendations": recommendations,
        }

    def _move_efficacy_score(self, rows: list[dict]) -> float:
        """Score a move from aligned/wrong/missed module signals."""
        if not rows:
            return 0.0
        scores = [self._status_score(row["status"], row["confidence"]) for row in rows]
        return self._average(scores)

    @staticmethod
    def _alignment_status(signal_direction: Any, move_direction: Any) -> str:
        """Return ALIGNED, WRONG, or MISSED for a signal direction."""
        signal_text = str(signal_direction or "NEUTRAL").upper()
        move_text = str(move_direction or "NEUTRAL").upper()
        if signal_text == move_text and signal_text in ("BULL", "BEAR"):
            return "ALIGNED"
        if signal_text in ("BULL", "BEAR") and signal_text != move_text:
            return "WRONG"
        return "MISSED"

    @staticmethod
    def _status_score(status: str, confidence: Any) -> float:
        """Convert alignment status into a 0-10 contribution."""
        conf = GreyDailyEfficacyTracker._clamp_unit(confidence)
        if status == "ALIGNED":
            return 7.0 + 3.0 * conf
        if status == "WRONG":
            return max(0.0, 3.0 - 3.0 * conf)
        return 4.0

    @staticmethod
    def _status_text(status: str) -> str:
        """Return a simple printable status label."""
        if status == "ALIGNED":
            return "ALIGNED"
        if status == "WRONG":
            return "WRONG"
        return "MISSED"

    @staticmethod
    def _call_accuracy_text(direction: Any, move_type: Any, move_direction: Any, status: str) -> str:
        """Build the readable call-accuracy sentence."""
        return f"{direction} given, {move_type} {move_direction} happened -> {status}"

    @staticmethod
    def _module_remark(status: str) -> str:
        """Return a short operator-friendly module remark."""
        if status == "ALIGNED":
            return "Nailed it"
        if status == "WRONG":
            return "Conflicted"
        return "Missed"

    @staticmethod
    def _quality_rating(accuracy_pct: float) -> str:
        """Convert accuracy percentage into a simple rating."""
        if accuracy_pct >= 70.0:
            return "GOOD"
        if accuracy_pct >= 50.0:
            return "FAIR"
        return "POOR"

    @staticmethod
    def _module_notes(module_id: str, accuracy_pct: float) -> str:
        """Build module notes from accuracy."""
        if accuracy_pct >= 70.0:
            return f"{module_id} was useful today."
        if accuracy_pct >= 50.0:
            return f"{module_id} was mixed; review before changing weights."
        return f"{module_id} lagged or conflicted; inspect inputs and logic."

    @staticmethod
    def _rank_module(scorecard: Mapping[str, Any], *, best: bool) -> str | None:
        """Find best or worst module by average score."""
        if not scorecard:
            return None
        return sorted(
            scorecard,
            key=lambda module: scorecard[module].get("average_score", 0.0),
            reverse=best,
        )[0]

    @staticmethod
    def _warning_lead_time(aligned_rows: list[dict], start_dt: datetime) -> int | None:
        """Return the earliest aligned warning lead time in minutes."""
        if not aligned_rows:
            return None
        return max(int((start_dt - datetime.fromisoformat(row["full_timestamp"])).total_seconds() // 60) for row in aligned_rows)

    @staticmethod
    def _move_remark(
        move: Mapping[str, Any],
        early_warning_given: bool,
        lead_time: int | None,
        module_breakdown: Mapping[str, Any],
    ) -> str:
        """Build one short remark for a market move."""
        if not module_breakdown:
            return "No GREY module signals were available before this move."
        aligned = [module for module, data in module_breakdown.items() if data.get("status") == "ALIGNED"]
        if early_warning_given:
            lead = f"{lead_time}min early" if lead_time is not None else "before the move"
            return f"{', '.join(aligned[:3])} warned {lead}."
        return f"No aligned warning before {move.get('type')}."

    @staticmethod
    def _average(values: Iterable[Any]) -> float:
        """Return a safe numeric average."""
        numbers = []
        for value in values:
            try:
                numbers.append(float(value))
            except (TypeError, ValueError):
                continue
        return sum(numbers) / len(numbers) if numbers else 0.0

    @staticmethod
    def _read_signal_records(signal_log: str | Path | Iterable[Mapping[str, Any]]) -> list[dict]:
        """Read Phase 1 signal JSONL or accept loaded records."""
        if isinstance(signal_log, (str, Path)):
            path = Path(signal_log)
            if not path.exists():
                raise FileNotFoundError(f"Signal log not found: {path}")
            records = []
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        records.append(json.loads(line))
            return records
        return [dict(record) for record in signal_log]

    def _signal_candle_window(
        self,
        signal: Mapping[str, Any],
        candles: pd.DataFrame,
        start_dt: datetime,
    ) -> pd.DataFrame:
        """Return candles in the signal's evaluation period."""
        end_dt = (
            self._parse_dt(signal.get("evaluation_due_at"))
            or self._parse_dt(signal.get("evaluated_at"))
            or start_dt + timedelta(minutes=int(self.config["early_warning_minutes"]))
        )
        return candles[(candles["timestamp"] >= start_dt) & (candles["timestamp"] < end_dt)].copy()

    def _exit_price_for_signal(
        self,
        signal: Mapping[str, Any],
        candles: pd.DataFrame,
        start_dt: datetime,
    ) -> float | None:
        """Return the last close in a signal evaluation window."""
        window = self._signal_candle_window(signal, candles, start_dt)
        if window.empty:
            return None
        return self._to_float(window["close"].iloc[-1])

    @classmethod
    def _predicted_bound(cls, signal: Mapping[str, Any], key: str) -> float | None:
        """Find a predicted high/low in top-level or Kronos-shaped records."""
        direct = cls._to_float(signal.get(key))
        if direct is not None:
            return direct

        candidate_paths = (
            ("kronos", key),
            ("KRONOS", key),
            ("kronos_prediction", key),
            ("module_outputs", "KRONOS", key),
            ("module_outputs", "KRONOS", "raw_components", key),
            ("module_vector", "KRONOS", key),
            ("module_vector", "KRONOS", "raw_components", key),
        )
        for path in candidate_paths:
            value: Any = signal
            for part in path:
                if not isinstance(value, Mapping):
                    value = None
                    break
                value = value.get(part)
            parsed = cls._to_float(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _resolve_report_date(report_date: date | str | None, candles: pd.DataFrame) -> date:
        """Pick report date from input or latest candle."""
        if isinstance(report_date, date):
            return report_date
        if isinstance(report_date, str) and report_date.strip():
            return date.fromisoformat(report_date.strip())
        return pd.Timestamp(candles["timestamp"].max()).date()

    @staticmethod
    def _filter_date(candles: pd.DataFrame, report_date: date) -> pd.DataFrame:
        """Keep only candles from one report date."""
        filtered = candles[candles["timestamp"].dt.date == report_date].copy()
        if filtered.empty:
            raise ValueError(f"No OHLCV candles found for {report_date}.")
        return filtered.reset_index(drop=True)

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        """Parse a signal timestamp safely."""
        if isinstance(value, datetime):
            return value
        if value is None:
            return None
        try:
            text = str(value)
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            return datetime.fromisoformat(text).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _clamp_unit(value: Any) -> float:
        """Clamp any numeric value into 0.0 to 1.0."""
        numeric = GreyDailyEfficacyTracker._to_float(value)
        if numeric is None:
            return 0.0
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely parse a numeric value."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _date_to_text(value: date | str | None) -> str | None:
        """Convert optional date input to ISO text."""
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None


__all__ = ["GreyDailyEfficacyTracker"]
