"""Pre-shadow-mode backtest runner for GREY.

This is a conservative historical simulator for validating whether GREY has
any plausible EV before live shadow mode. It does not place orders.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from grey_ev_calculator import GreyEVCalculator
from grey_risk_manager import GreyRiskManager


class GreyBacktestRunner:
    """Run a simple Iron Condor EV backtest over 1-minute NIFTY candles."""

    def __init__(
        self,
        csv_file_path: str | Path,
        module_weights: Mapping[str, float] | None = None,
        position_sizing_config: Mapping[str, Any] | None = None,
        stop_loss_config: Mapping[str, Any] | None = None,
        *,
        output_path: str | Path = "backtest_results.json",
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize backtest input paths and configs."""
        self.csv_file_path = Path(csv_file_path)
        self.module_weights = dict(module_weights or {})
        self.position_sizing_config = dict(position_sizing_config or {})
        self.stop_loss_config = dict(stop_loss_config or {})
        self.output_path = Path(output_path)
        self.logger = logger or logging.getLogger(__name__)
        self.ev_calculator = GreyEVCalculator(logger=self.logger)

    def load_data(self, csv_path: str | Path) -> pd.DataFrame:
        """Load and normalize 1-minute NIFTY OHLCV data."""
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Backtest data not found: {path}")
        df = pd.read_csv(path)
        if "timestamp" not in df.columns and "timestamps" in df.columns:
            df = df.rename(columns={"timestamps": "timestamp"})
        required = ("timestamp", "open", "high", "low", "close")
        missing = [column for column in required if column not in df.columns]
        if missing:
            raise ValueError(f"Backtest CSV missing columns: {missing}")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            if column not in df.columns:
                df[column] = 0.0
            df[column] = pd.to_numeric(df[column], errors="coerce")
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
        if df.empty:
            raise ValueError("Backtest CSV has no usable rows.")
        return df.sort_values("timestamp").reset_index(drop=True)

    def run_backtest(self) -> dict:
        """Run the pre-shadow backtest and save backtest_results.json."""
        try:
            one_minute = self.load_data(self.csv_file_path)
            bars = self._to_five_minute_bars(one_minute)
            trades = []
            for index in range(0, max(0, len(bars) - 1)):
                bar = bars.iloc[index]
                future = bars.iloc[index + 1:index + 7]
                if future.empty:
                    continue
                signal = self.generate_signal_on_bar(bar.to_dict(), modules=self.module_weights)
                if signal.get("direction") == "SKIP":
                    continue
                stop_loss = signal.get("stop_loss", 0.0)
                trade = self.simulate_trade(
                    signal,
                    entry_price=float(bar["close"]),
                    stop_loss=float(stop_loss or 0.0),
                    duration_minutes=len(future) * 5,
                    future_bars=future,
                )
                trades.append(trade)

            result = self._metrics_from_trades(trades)
            self.output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            self.logger.info("Backtest complete: %s", result)
            return result
        except Exception as exc:
            self.logger.warning("Backtest failed safely: %s", exc)
            result = self._empty_metrics(error=str(exc))
            self.output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            return result

    def generate_signal_on_bar(self, bar: Mapping[str, Any], modules: Mapping[str, Any] | None = None) -> dict:
        """Generate a simple range-bound signal from one 5-minute bar."""
        close_price = self._to_float(bar.get("close")) or 0.0
        open_price = self._to_float(bar.get("open")) or close_price
        if close_price <= 0:
            return {"direction": "SKIP"}
        confidence = 0.60 if abs(close_price - open_price) / close_price < 0.01 else 0.50
        vix_level = self._to_float(bar.get("india_vix")) or 20.0
        manager = GreyRiskManager(
            account_size=float(self.position_sizing_config.get("account_size", 100_000)),
            logger=self.logger,
        )
        lots = manager.position_size(confidence, vix_level)
        sold_premium = float(self.stop_loss_config.get("sold_premium", 100.0))
        return {
            "direction": "RANGE_BOUND",
            "confidence": confidence,
            "lots": lots,
            "sold_premium": sold_premium,
            "stop_loss": manager.stop_loss_for_iron_condor(sold_premium, 0),
            "entry_time": str(bar.get("timestamp")),
        }

    def simulate_trade(
        self,
        signal: Mapping[str, Any],
        entry_price: float,
        stop_loss: float,
        duration_minutes: int,
        future_bars: pd.DataFrame | None = None,
    ) -> dict:
        """Simulate one Iron Condor result with fixed cost penalty."""
        del entry_price, duration_minutes
        future = future_bars if future_bars is not None else pd.DataFrame()
        sold_premium = float(signal.get("sold_premium", 100.0))
        stop_price = float(stop_loss or sold_premium * 1.5)
        range_break = False
        if not future.empty:
            first_open = float(future["open"].iloc[0])
            atr_proxy = max(1.0, float((future["high"] - future["low"]).mean()))
            upper = first_open + 1.5 * atr_proxy
            lower = first_open - 1.5 * atr_proxy
            range_break = bool(future["high"].max() > upper or future["low"].min() < lower)
        gross_profit = float(os.getenv("GREY_EXPECTED_PROFIT_PER_TRADE", "2850") or "2850")
        gross_loss = float(os.getenv("GREY_EXPECTED_LOSS_PER_TRADE", "3150") or "3150")
        pnl = -gross_loss if range_break or stop_price <= sold_premium else gross_profit
        pnl_after_costs = pnl - self.ev_calculator.total_costs_rupees
        return {
            "pnl": round(pnl_after_costs, 2),
            "gross_pnl": pnl,
            "is_win": pnl > 0,
            "range_break": range_break,
        }

    def _to_five_minute_bars(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate 1-minute candles into 5-minute bars."""
        indexed = df.set_index("timestamp")
        bars = indexed.resample("5min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })
        return bars.dropna(subset=["open", "high", "low", "close"]).reset_index()

    def _metrics_from_trades(self, trades: list[Mapping[str, Any]]) -> dict:
        """Convert simulated trades into required backtest metrics."""
        if not trades:
            return self._empty_metrics()
        pnls = [float(trade.get("pnl", 0.0)) for trade in trades]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl <= 0]
        win_pct = len(wins) / len(pnls)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        equity = []
        running = 0.0
        for pnl in pnls:
            running += pnl
            equity.append(running)
        max_drawdown = self._max_drawdown(equity)
        sharpe = self._sharpe_ratio(pnls)
        return {
            "accuracy_pct": round(win_pct * 100.0, 2),
            "ev_simulated": self.ev_calculator.calculate_ev(win_pct, avg_win, avg_loss),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_drawdown["pct"], 2),
            "max_drawdown_rupees": round(max_drawdown["rupees"], 2),
            "win_pct": round(win_pct * 100.0, 2),
            "loss_pct": round((1.0 - win_pct) * 100.0, 2),
            "avg_win_rupees": round(avg_win, 2),
            "avg_loss_rupees": round(avg_loss, 2),
            "total_trades": len(pnls),
            "profitable_trades": len(wins),
            "losing_trades": len(losses),
        }

    @staticmethod
    def _max_drawdown(equity: list[float]) -> dict:
        """Return max drawdown from equity curve."""
        peak = 0.0
        max_dd = 0.0
        for value in equity:
            peak = max(peak, value)
            max_dd = max(max_dd, peak - value)
        pct = (max_dd / peak * 100.0) if peak > 0 else 0.0
        return {"rupees": max_dd, "pct": pct}

    @staticmethod
    def _sharpe_ratio(pnls: list[float]) -> float:
        """Return simple trade-level Sharpe ratio."""
        if len(pnls) < 2:
            return 0.0
        mean = sum(pnls) / len(pnls)
        variance = sum((pnl - mean) ** 2 for pnl in pnls) / (len(pnls) - 1)
        std = math.sqrt(variance)
        return 0.0 if std == 0 else (mean / std) * math.sqrt(len(pnls))

    @staticmethod
    def _empty_metrics(error: str | None = None) -> dict:
        """Return a complete empty backtest metric packet."""
        result = {
            "accuracy_pct": 0.0,
            "ev_simulated": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_rupees": 0.0,
            "win_pct": 0.0,
            "loss_pct": 0.0,
            "avg_win_rupees": 0.0,
            "avg_loss_rupees": 0.0,
            "total_trades": 0,
            "profitable_trades": 0,
            "losing_trades": 0,
        }
        if error:
            result["error"] = error
        return result

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely parse a float."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def main() -> None:
    """CLI entrypoint for pre-shadow-mode backtesting."""
    parser = argparse.ArgumentParser(description="Run GREY pre-shadow-mode backtest.")
    parser.add_argument("--data", default=os.getenv("GREY_BACKTEST_DATA_PATH", "data/nifty_3months.csv"))
    parser.add_argument("--output", default="backtest_results.json")
    args = parser.parse_args()
    result = GreyBacktestRunner(csv_file_path=args.data, output_path=args.output).run_backtest()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["GreyBacktestRunner"]
