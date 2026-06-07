"""
Kronos forecast module for GREY.

GREY uses this module as market-intelligence context only. It does not place
orders, size positions, or make execution decisions.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

import grey_config


class GreyKronosModule:
    """Wrap a local Kronos model and return a GREY-compatible score packet."""

    def __init__(
        self,
        model_dir: str | Path | None = None,
        kronos_repo_path: str | Path | None = None,
    ) -> None:
        # This name is how the GREY aggregator identifies this module.
        self.module_id = "KRONOS"

        # This folder should contain the fine-tuned model produced by finetune_kronos_nse.py.
        self.model_dir = Path(model_dir or getattr(
            grey_config,
            "GREY_KRONOS_MODEL_PATH",
            "kronos_nse_finetuned",
        ))

        # This points to the cloned Kronos GitHub repository.
        self.kronos_repo_path = Path(kronos_repo_path or getattr(
            grey_config,
            "GREY_KRONOS_REPO_PATH",
            "Kronos",
        ))

        # Kronos-small and Kronos-base use a 512-candle maximum context.
        self.max_context = int(getattr(grey_config, "GREY_KRONOS_MAX_CONTEXT", 512))

        # The predictor is loaded lazily so GREY can start even if Kronos is not installed.
        self._predictor: Any | None = None
        self._warned_missing_model = False

    def evaluate(
        self,
        ohlcv_df: pd.DataFrame | None,
        session_state: str,
        pred_candles: int = 5,
    ) -> dict:
        """Forecast the next candles and return a standard GREY module packet."""
        try:
            # Validate and clean the OHLCV data before passing it to Kronos.
            clean_df = self._prepare_ohlcv(ohlcv_df)
            if clean_df is None:
                return self._neutral_packet(
                    status="UNAVAILABLE",
                    reason="Kronos input missing or invalid OHLCV candles.",
                    session_state=session_state,
                )

            # Return a neutral packet if the fine-tuned model folder is not available.
            if not self._model_available():
                self._warn_model_missing()
                return self._neutral_packet(
                    status="UNAVAILABLE",
                    reason=f"Kronos model folder not found: {self.model_dir}",
                    session_state=session_state,
                )

            # Load the Kronos predictor only when the first real evaluation happens.
            predictor = self._load_predictor()

            # Ask Kronos for the next few 15-minute candles.
            pred_df = self._predict(predictor, clean_df, pred_candles)

            # Convert the forecast path into GREY score fields.
            return self._packet_from_prediction(clean_df, pred_df, session_state)
        except Exception as exc:
            return self._neutral_packet(
                status="UNAVAILABLE",
                reason=f"Kronos failed safely: {exc}",
                session_state=session_state,
            )

    def _load_predictor(self) -> Any:
        """Load Kronos from the local repo and local fine-tuned model folder."""
        if self._predictor is not None:
            return self._predictor

        # Add the cloned Kronos repository to Python's import path.
        repo_path = self.kronos_repo_path.resolve()
        if str(repo_path) not in sys.path:
            sys.path.insert(0, str(repo_path))

        # Kronos exposes these classes from its local `model` package.
        from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore

        # The fine-tune helper stores the predictor and tokenizer in simple subfolders.
        model_path = self._first_existing_path(
            self.model_dir / "model",
            self.model_dir / "basemodel" / "best_model",
            self.model_dir,
        )
        tokenizer_path = self._first_existing_path(
            self.model_dir / "tokenizer",
            self.model_dir / "tokenizer" / "best_model",
            self.model_dir,
        )

        # Load the tokenizer and model from local disk.
        tokenizer = KronosTokenizer.from_pretrained(str(tokenizer_path))
        model = Kronos.from_pretrained(str(model_path))

        # Let Kronos handle truncation at the supported context length.
        self._predictor = KronosPredictor(model, tokenizer, max_context=self.max_context)
        return self._predictor

    def _predict(self, predictor: Any, clean_df: pd.DataFrame, pred_candles: int) -> pd.DataFrame:
        """Run Kronos prediction using GREY's OHLCV DataFrame."""
        pred_len = max(1, int(pred_candles))

        # Kronos works best with no more than its maximum supported lookback.
        x_df = clean_df.tail(self.max_context).copy()

        # Kronos accepts `amount`; GREY does not always have it, so we send zero.
        if "amount" not in x_df.columns:
            x_df["amount"] = 0.0

        # Build the historical and future timestamp series Kronos expects.
        x_timestamp = pd.to_datetime(x_df["timestamp"])
        interval = self._infer_interval(x_timestamp)
        y_timestamp = pd.date_range(
            x_timestamp.iloc[-1] + interval,
            periods=pred_len,
            freq=interval,
        )

        # Run a low-temperature forecast to keep live shadow-mode output stable.
        return predictor.predict(
            df=x_df[["open", "high", "low", "close", "volume", "amount"]],
            x_timestamp=x_timestamp,
            y_timestamp=pd.Series(y_timestamp),
            pred_len=pred_len,
            T=0.6,
            top_p=0.9,
            sample_count=1,
            verbose=False,
        )

    def _packet_from_prediction(
        self,
        history_df: pd.DataFrame,
        pred_df: pd.DataFrame,
        session_state: str,
    ) -> dict:
        """Convert predicted candles into GREY's bounded score format."""
        last_close = float(history_df["close"].iloc[-1])
        predicted_high = float(pd.to_numeric(pred_df["high"], errors="coerce").max())
        predicted_low = float(pd.to_numeric(pred_df["low"], errors="coerce").min())
        predicted_close = float(pd.to_numeric(pred_df["close"], errors="coerce").iloc[-1])
        predicted_range = predicted_high - predicted_low

        # A 1 percent forecasted move maps to a full +10/-10 score.
        move_pct = (predicted_close - last_close) / last_close if last_close else 0.0
        score = self._clamp(move_pct / 0.01 * 10.0, -10.0, 10.0)
        direction = self._direction_from_score(score)

        # Confidence stays conservative because Kronos is a context module, not an execution engine.
        confidence = min(0.85, 0.35 + min(abs(score) / 10.0, 1.0) * 0.40)
        if session_state == "PRE_EVENT":
            confidence *= 0.50
        elif session_state == "OPENING_DRIVE":
            confidence *= 0.70

        # Safe strikes are a simple 0.5 percent buffer around Kronos' forecast range.
        safe_call_strike = predicted_high * 1.005
        safe_put_strike = predicted_low * 0.995

        return {
            "module_id": self.module_id,
            "score": round(score, 3),
            "direction": direction,
            "confidence": round(confidence, 3),
            "status": "ACTIVE",
            "reason": f"Kronos forecast close move {move_pct * 100:.2f}%.",
            "predicted_high": round(predicted_high, 2),
            "predicted_low": round(predicted_low, 2),
            "predicted_range": round(predicted_range, 2),
            "safe_call_strike": round(safe_call_strike, 2),
            "safe_put_strike": round(safe_put_strike, 2),
            "session_state": session_state,
            "top_driver": "kronos_forecast_range",
        }

    def _prepare_ohlcv(self, value: pd.DataFrame | None) -> pd.DataFrame | None:
        """Validate GREY's OHLCV input and normalize column names."""
        if value is None or not isinstance(value, pd.DataFrame) or value.empty:
            return None

        # Accept either `timestamp` or Kronos-style `timestamps`.
        df = value.copy()
        if "timestamp" not in df.columns and "timestamps" in df.columns:
            df = df.rename(columns={"timestamps": "timestamp"})
        if "timestamp" not in df.columns:
            df["timestamp"] = pd.date_range(
                "2000-01-01 09:15",
                periods=len(df),
                freq="15min",
            )

        required = ["open", "high", "low", "close", "volume"]
        if any(column not in df.columns for column in required):
            return None

        # Convert numeric candle columns and drop broken rows.
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        for column in required:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
        if len(df) < 20:
            return None
        return df.sort_values("timestamp").reset_index(drop=True)

    def _model_available(self) -> bool:
        """Return True only when the local fine-tuned Kronos folder exists."""
        return self.model_dir.exists() and any(self.model_dir.iterdir())

    def _warn_model_missing(self) -> None:
        """Print the missing-model warning once per process."""
        if self._warned_missing_model:
            return
        print(f"Warning: Kronos model not found at {self.model_dir}. Returning neutral KRONOS packet.")
        self._warned_missing_model = True

    def _neutral_packet(self, *, status: str, reason: str, session_state: str) -> dict:
        """Return a safe neutral GREY packet."""
        return {
            "module_id": self.module_id,
            "score": 0.0,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "status": status,
            "reason": reason,
            "predicted_high": None,
            "predicted_low": None,
            "predicted_range": None,
            "safe_call_strike": None,
            "safe_put_strike": None,
            "session_state": session_state,
            "top_driver": "kronos_unavailable",
        }

    @staticmethod
    def _infer_interval(timestamps: pd.Series) -> pd.Timedelta:
        """Infer the candle interval, falling back to 15 minutes."""
        deltas = timestamps.sort_values().diff().dropna()
        if deltas.empty:
            return pd.Timedelta(minutes=15)
        median_delta = deltas.median()
        if pd.isna(median_delta) or median_delta <= pd.Timedelta(0):
            return pd.Timedelta(minutes=15)
        return median_delta

    @staticmethod
    def _first_existing_path(*paths: Path) -> Path:
        """Pick the first path that exists, otherwise return the first candidate."""
        for path in paths:
            if path.exists():
                return path
        return paths[0]

    @staticmethod
    def _direction_from_score(score: float) -> str:
        if score >= 2.0:
            return "BULL"
        if score <= -2.0:
            return "BEAR"
        return "NEUTRAL"

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))


__all__ = ["GreyKronosModule"]
