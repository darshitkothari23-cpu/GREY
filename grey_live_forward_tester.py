"""
GREY live forward tester for Phase 1 shadow mode using Angel One SmartAPI.

The script fetches live market context every 5 minutes during Indian market
hours and passes it to GreyPhase1Engine. It is market-intelligence plumbing
only. It does not place or manage orders.

.env keys:
    ANGEL_API_KEY=...
    ANGEL_CLIENT_ID=...
    ANGEL_PIN=...

Optional but strongly recommended for automatic login:
    ANGEL_TOTP_SECRET=...   # preferred; pyotp generates the current code
    ANGEL_TOTP=...          # fallback one-time code

Optional token overrides:
    ANGEL_NIFTY_SPOT_TOKEN=99926000
    ANGEL_INDIA_VIX_TOKEN=99926017
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyotp
from dotenv import load_dotenv
from SmartApi import SmartConnect

from grey_live_data_provider import GreyLiveDataProvider
from grey_phase1_engine import GreyPhase1Engine


IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = datetime_time(9, 15)
MARKET_CLOSE = datetime_time(15, 30)
LOOP_INTERVAL_SECONDS = 5 * 60
SYMBOL = "NIFTY"
SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/"
    "OpenAPI_File/files/OpenAPIScripMaster.json"
)


class MarketDataError(RuntimeError):
    """Raised when SmartAPI data is unavailable for the current cycle."""


class RateLimitError(MarketDataError):
    """Raised when Angel One rejects requests because of access-rate limits."""


@dataclass(frozen=True)
class Instrument:
    exchange: str
    token: str
    symbol: str
    name: str = ""
    expiry: str = ""
    strike: float = 0.0
    instrument_type: str = ""


class LiveMarketDataClient:
    """
    Angel One SmartAPI live data client for GREY Phase 1.

    This class loads credentials from `.env`, opens a SmartAPI session, resolves
    required instrument tokens, and builds the exact dictionary expected by the
    GREY modules:

    - price
    - price_change_from_open
    - atr_14
    - volatility_ratio
    - put_wall_weight
    - call_wall_weight
    - ivp
    - is_expiry
    - ohlcv_df
    """

    def __init__(self, env_path: str | Path = ".env") -> None:
        load_dotenv(env_path)
        self.api_key = self._required_env("ANGEL_API_KEY")
        self.client_id = self._required_env("ANGEL_CLIENT_ID")
        self.pin = self._required_env("ANGEL_PIN")
        self.totp_secret = os.getenv("ANGEL_TOTP_SECRET", "")
        self.static_totp = os.getenv("ANGEL_TOTP", "")
        self.smart_api: SmartConnect | None = None
        self.refresh_token: str | None = None
        self.feed_token: str | None = None
        self._scrip_master: list[dict] | None = None
        self.api_pause_seconds = float(os.getenv("ANGEL_API_PAUSE_SECONDS", "0.75"))

    def fetch_live_market_data(self, symbol: str = SYMBOL) -> dict[str, Any]:
        """Fetch and calculate GREY live inputs for the requested index."""
        try:
            self._ensure_session()
            spot_instrument = self._resolve_index_instrument(symbol)
            spot = self._fetch_nifty_spot(spot_instrument, symbol)
            ohlcv_df = self._get_intraday_ohlcv(
                spot_instrument,
                interval="FIFTEEN_MINUTE",
                count=512,
            )
            atr_14 = self._calculate_atr_14(spot_instrument)
            volatility_ratio, ivp = self._calculate_vix_context()
            option_context = self._calculate_option_wall_context(
                symbol=symbol,
                spot_price=spot["price"],
            )

            return {
                "price": spot["price"],
                "price_change_from_open": spot["price"] - spot["open"],
                "atr_14": atr_14,
                "volatility_ratio": volatility_ratio,
                "put_wall_weight": option_context["put_wall_weight"],
                "call_wall_weight": option_context["call_wall_weight"],
                "ivp": ivp,
                "is_expiry": option_context["is_expiry"],
                "ohlcv_df": ohlcv_df,
            }
        except Exception as exc:
            if self._is_rate_limit_error(exc):
                raise RateLimitError("Rate limit exceeded, skipping cycle") from exc
            raise MarketDataError(f"Angel SmartAPI data fetch failed: {exc}") from exc

    def fetch_recent_ohlcv(
        self,
        symbol: str = SYMBOL,
        interval: str = "FIFTEEN_MINUTE",
        count: int = 512,
    ) -> pd.DataFrame:
        """Fetch recent OHLCV candles for NSE data collection and Kronos."""
        try:
            self._ensure_session()
            spot_instrument = self._resolve_index_instrument(symbol)
            return self._get_intraday_ohlcv(
                spot_instrument,
                interval=interval,
                count=count,
            )
        except Exception as exc:
            if self._is_rate_limit_error(exc):
                raise RateLimitError("Rate limit exceeded, skipping cycle") from exc
            raise MarketDataError(f"Angel SmartAPI candle fetch failed: {exc}") from exc

    def _ensure_session(self) -> None:
        if self.smart_api is not None:
            return

        self.smart_api = SmartConnect(api_key=self.api_key)
        totp = self._current_totp()
        self._api_pause()
        session = self.smart_api.generateSession(self.client_id, self.pin, totp)
        if not self._is_ok(session):
            raise MarketDataError(f"SmartAPI login failed: {session}")

        data = session.get("data") or {}
        self.refresh_token = data.get("refreshToken")
        self.feed_token = self.smart_api.getfeedToken()
        if not self.refresh_token:
            raise MarketDataError("SmartAPI login did not return a refresh token")

        try:
            self._api_pause()
            self.smart_api.generateToken(self.refresh_token)
        except Exception as exc:
            logging.warning("SmartAPI token refresh after login failed: %s", exc)

    def _current_totp(self) -> str:
        if self.totp_secret:
            return pyotp.TOTP(self.totp_secret).now()
        if self.static_totp:
            return self.static_totp
        raise MarketDataError(
            "SmartAPI requires TOTP. Add ANGEL_TOTP_SECRET or ANGEL_TOTP to .env."
        )

    def _fetch_nifty_spot(
        self,
        spot_instrument: Instrument,
        symbol: str,
    ) -> dict[str, float]:
        quote = self._ltp(
            spot_instrument.exchange,
            spot_instrument.symbol,
            spot_instrument.token,
        )
        price = self._first_float(quote, ("ltp", "close", "last_traded_price"))
        open_price = self._first_float(quote, ("open", "open_price"))

        if price is None:
            raise MarketDataError(f"Missing live spot price for {symbol}: {quote}")
        if open_price is None:
            open_price = self._daily_open_from_candles(spot_instrument)

        return {"price": price, "open": open_price}

    def _calculate_atr_14(self, spot: Instrument) -> float:
        candles = self._get_daily_candles(spot, days=25)
        if len(candles) < 15:
            raise MarketDataError("Not enough daily candles to calculate ATR(14)")

        df = self._candles_to_df(candles)
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(14).mean().iloc[-1]
        if pd.isna(atr):
            raise MarketDataError("ATR(14) calculation returned NaN")
        return float(atr)

    def _calculate_vix_context(self) -> tuple[float, float]:
        vix = self._resolve_vix_instrument()
        live_quote = self._ltp(vix.exchange, vix.symbol, vix.token)
        live_vix = self._first_float(live_quote, ("ltp", "close", "last_traded_price"))
        if live_vix is None:
            raise MarketDataError(f"Missing live India VIX value: {live_quote}")

        candles = self._get_daily_candles(vix, days=45)
        df = self._candles_to_df(candles)
        closes = df["close"].dropna().tail(30)
        if closes.empty:
            raise MarketDataError("No India VIX history available")

        median_vix = float(closes.median())
        volatility_ratio = live_vix / median_vix if median_vix > 0 else 1.0
        ivp = float((closes < live_vix).sum() / len(closes))
        return volatility_ratio, ivp

    def _calculate_option_wall_context(
        self,
        *,
        symbol: str,
        spot_price: float,
    ) -> dict[str, Any]:
        contracts = self._resolve_near_month_options(symbol)
        lower = spot_price * 0.95
        upper = spot_price * 1.05
        active_contracts = [
            contract for contract in contracts
            if lower <= contract.strike <= upper
        ]
        if not active_contracts:
            raise MarketDataError("No near-month option contracts found within +/-5%")

        market_rows = self._fetch_option_market_rows(active_contracts)
        put_wall_weight = 0.0
        call_wall_weight = 0.0

        for contract, row in market_rows:
            volume = self._first_float(row, ("volume", "tradeVolume", "tradingVolume")) or 0.0
            oi = self._first_float(row, ("opnInterest", "openInterest", "oi")) or 0.0
            weight = volume * oi
            if contract.instrument_type.endswith("PE"):
                put_wall_weight += weight
            elif contract.instrument_type.endswith("CE"):
                call_wall_weight += weight

        near_expiry = self._nearest_expiry(active_contracts)
        return {
            "put_wall_weight": put_wall_weight,
            "call_wall_weight": call_wall_weight,
            "is_expiry": self._parse_expiry_date(near_expiry) == datetime.now(IST).date(),
        }

    def _fetch_option_market_rows(
        self,
        contracts: list[Instrument],
    ) -> list[tuple[Instrument, Mapping[str, Any]]]:
        rows: list[tuple[Instrument, Mapping[str, Any]]] = []
        for batch in self._chunks(contracts, 50):
            tokens = [contract.token for contract in batch]
            self._api_pause()
            response = self._api().getMarketData("FULL", {"NFO": tokens})
            if not self._is_ok(response):
                raise MarketDataError(f"Option market data failed: {response}")
            fetched = (response.get("data") or {}).get("fetched") or []
            by_token = {str(row.get("symbolToken")): row for row in fetched}
            for contract in batch:
                row = by_token.get(str(contract.token))
                if row:
                    rows.append((contract, row))
        return rows

    def _daily_open_from_candles(self, spot: Instrument) -> float:
        candles = self._get_daily_candles(spot, days=5)
        df = self._candles_to_df(candles)
        return float(df["open"].iloc[-1])

    def _get_daily_candles(self, instrument: Instrument, days: int) -> list:
        to_dt = datetime.now(IST)
        from_dt = to_dt - timedelta(days=days * 2)
        params = {
            "exchange": instrument.exchange,
            "symboltoken": instrument.token,
            "interval": "ONE_DAY",
            "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate": to_dt.strftime("%Y-%m-%d %H:%M"),
        }
        self._api_pause()
        response = self._api().getCandleData(params)
        if not self._is_ok(response):
            raise MarketDataError(f"Candle data failed for {instrument.symbol}: {response}")
        candles = response.get("data") or []
        if not candles:
            raise MarketDataError(f"No candles returned for {instrument.symbol}")
        return candles[-days:]

    def _get_intraday_ohlcv(
        self,
        instrument: Instrument,
        *,
        interval: str,
        count: int,
    ) -> pd.DataFrame:
        candles = self._get_intraday_candles(
            instrument,
            interval=interval,
            count=count,
        )
        df = self._candles_to_df(candles)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])
        return df.tail(count).reset_index(drop=True)

    def _get_intraday_candles(
        self,
        instrument: Instrument,
        *,
        interval: str,
        count: int,
    ) -> list:
        to_dt = datetime.now(IST)
        lookback_days = max(35, int(count / 20) + 15)
        from_dt = to_dt - timedelta(days=lookback_days)
        params = {
            "exchange": instrument.exchange,
            "symboltoken": instrument.token,
            "interval": interval,
            "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate": to_dt.strftime("%Y-%m-%d %H:%M"),
        }
        self._api_pause()
        response = self._api().getCandleData(params)
        if not self._is_ok(response):
            raise MarketDataError(f"Intraday candles failed for {instrument.symbol}: {response}")
        candles = response.get("data") or []
        if not candles:
            raise MarketDataError(f"No intraday candles returned for {instrument.symbol}")
        return candles[-count:]

    @staticmethod
    def _candles_to_df(candles: list) -> pd.DataFrame:
        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna(subset=["open", "high", "low", "close"])

    def _ltp(self, exchange: str, symbol: str, token: str) -> Mapping[str, Any]:
        self._api_pause()
        response = self._api().ltpData(exchange, symbol, token)
        if not self._is_ok(response):
            raise MarketDataError(f"LTP failed for {symbol}: {response}")
        data = response.get("data") or {}
        return data

    def _resolve_index_instrument(self, symbol: str) -> Instrument:
        token_override = os.getenv("ANGEL_NIFTY_SPOT_TOKEN", "")
        if symbol.upper() == "NIFTY" and token_override:
            return Instrument("NSE", token_override, "NIFTY 50", "NIFTY")

        for row in self._scrips():
            name = str(row.get("name", "")).upper()
            tradingsymbol = str(row.get("symbol", "")).upper()
            exch_seg = str(row.get("exch_seg", "")).upper()
            if exch_seg == "NSE" and (tradingsymbol == "NIFTY 50" or name == "NIFTY"):
                return self._instrument_from_row(row)

        return Instrument("NSE", "99926000", "NIFTY 50", "NIFTY")

    def _resolve_vix_instrument(self) -> Instrument:
        token_override = os.getenv("ANGEL_INDIA_VIX_TOKEN", "")
        if token_override:
            return Instrument("NSE", token_override, "INDIA VIX", "INDIA VIX")

        for row in self._scrips():
            text = f"{row.get('name', '')} {row.get('symbol', '')}".upper()
            if str(row.get("exch_seg", "")).upper() == "NSE" and "VIX" in text:
                return self._instrument_from_row(row)

        return Instrument("NSE", "99926017", "INDIA VIX", "INDIA VIX")

    def _resolve_near_month_options(self, symbol: str) -> list[Instrument]:
        option_rows = []
        for row in self._scrips():
            exch_seg = str(row.get("exch_seg", "")).upper()
            instrument_type = str(row.get("instrumenttype", "")).upper()
            name = str(row.get("name", "")).upper()
            if exch_seg == "NFO" and instrument_type == "OPTIDX" and name == symbol.upper():
                option_rows.append(row)

        contracts = [self._instrument_from_row(row) for row in option_rows]
        contracts = [
            contract for contract in contracts
            if contract.instrument_type.endswith(("CE", "PE"))
        ]
        if not contracts:
            raise MarketDataError(f"No NFO option contracts found for {symbol}")

        near_expiry = self._nearest_expiry(contracts)
        return [contract for contract in contracts if contract.expiry == near_expiry]

    def _nearest_expiry(self, contracts: Iterable[Instrument]) -> str:
        today = datetime.now(IST).date()
        expiries = sorted({
            contract.expiry for contract in contracts
            if self._parse_expiry_date(contract.expiry) >= today
        }, key=self._parse_expiry_date)
        if not expiries:
            raise MarketDataError("No future option expiry found")
        return expiries[0]

    def _instrument_from_row(self, row: Mapping[str, Any]) -> Instrument:
        return Instrument(
            exchange=str(row.get("exch_seg", "")),
            token=str(row.get("token", "")),
            symbol=str(row.get("symbol", "")),
            name=str(row.get("name", "")),
            expiry=str(row.get("expiry", "")),
            strike=self._normalize_strike(row.get("strike")),
            instrument_type=str(row.get("symbol", "")).upper()[-2:],
        )

    @staticmethod
    def _normalize_strike(value: Any) -> float:
        raw = LiveMarketDataClient._to_float(value) or 0.0
        return raw / 100.0 if raw > 100000 else raw

    def _scrips(self) -> list[dict]:
        if self._scrip_master is None:
            self._api_pause()
            with urllib.request.urlopen(SCRIP_MASTER_URL, timeout=20) as response:
                self._scrip_master = json.loads(response.read().decode("utf-8"))
        return self._scrip_master

    def _api(self) -> SmartConnect:
        self._ensure_session()
        if self.smart_api is None:
            raise MarketDataError("SmartAPI session is unavailable")
        return self.smart_api

    def _api_pause(self) -> None:
        time.sleep(self.api_pause_seconds)

    @staticmethod
    def _parse_expiry_date(value: str) -> date:
        for fmt in ("%d%b%Y", "%d%b%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.upper(), fmt).date()
            except ValueError:
                continue
        raise MarketDataError(f"Could not parse expiry date: {value}")

    @staticmethod
    def _required_env(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise MarketDataError(f"Missing required .env value: {name}")
        return value

    @staticmethod
    def _is_ok(response: Mapping[str, Any] | None) -> bool:
        if not response:
            return False
        if response.get("status") is True:
            return True
        return str(response.get("message", "")).lower() in ("success", "ok")

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "exceeding access rate" in text
            or "access rate" in text
            or "rate limit" in text
            or "too many requests" in text
        )

    @staticmethod
    def _first_float(data: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = LiveMarketDataClient._to_float(data.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _chunks(items: list[Instrument], size: int) -> Iterable[list[Instrument]]:
        for start in range(0, len(items), size):
            yield items[start:start + size]


def now_ist() -> datetime:
    """Return current wall-clock time in India Standard Time."""
    return datetime.now(IST)


def is_indian_market_hours(dt: datetime) -> bool:
    """Return True during regular Indian cash-market hours."""
    local_dt = dt.astimezone(IST)
    if local_dt.weekday() >= 5:
        return False
    return MARKET_OPEN <= local_dt.time() <= MARKET_CLOSE


def seconds_until_next_market_check(dt: datetime) -> int:
    """Return a conservative sleep duration while outside market hours."""
    local_dt = dt.astimezone(IST)
    today_open = datetime.combine(local_dt.date(), MARKET_OPEN, tzinfo=IST)

    if local_dt.weekday() >= 5:
        days_until_monday = 7 - local_dt.weekday()
        next_open = today_open + timedelta(days=days_until_monday)
    elif local_dt < today_open:
        next_open = today_open
    else:
        next_open = today_open + timedelta(days=1)

    return max(60, min(1800, int((next_open - local_dt).total_seconds())))


def run_forward_test_loop(
    *,
    engine: GreyPhase1Engine | None = None,
    data_client: LiveMarketDataClient | None = None,
    symbol: str = SYMBOL,
) -> None:
    """Run the GREY Phase 1 forward-testing loop."""
    engine = engine or GreyPhase1Engine()
    data_client = data_client or GreyLiveDataProvider(
        broker_client=LiveMarketDataClient(),
    )

    logging.info("GREY forward tester started in SmartAPI shadow mode for %s", symbol)
    while True:
        cycle_dt = now_ist()
        if not is_indian_market_hours(cycle_dt):
            sleep_seconds = seconds_until_next_market_check(cycle_dt)
            logging.info(
                "Outside market hours at %s. Sleeping %s seconds.",
                cycle_dt.isoformat(),
                sleep_seconds,
            )
            time.sleep(sleep_seconds)
            continue

        try:
            market_data = data_client.fetch_live_market_data(symbol=symbol)
            market_data["timestamp"] = cycle_dt.replace(tzinfo=None)
            result = engine.run_cycle(
                market_data_by_symbol={symbol: market_data},
                dt=cycle_dt.replace(tzinfo=None),
            )
            logging.info(
                "GREY cycle ran at %s for %s. Created=%s Evaluated=%s",
                cycle_dt.isoformat(),
                symbol,
                result.get("created_count", 0),
                result.get("evaluated_count", 0),
            )
            print(
                f"GREY cycle ran: {cycle_dt.isoformat()} "
                f"symbol={symbol} "
                f"created={result.get('created_count', 0)} "
                f"evaluated={result.get('evaluated_count', 0)}"
            )
        except RateLimitError:
            message = "Rate limit exceeded, skipping cycle"
            logging.warning(message)
            print(message)
            time.sleep(LOOP_INTERVAL_SECONDS)
            continue
        except MarketDataError as exc:
            logging.warning("Skipping cycle because market data is unavailable: %s", exc)
            time.sleep(LOOP_INTERVAL_SECONDS)
            continue
        except Exception as exc:
            logging.exception("GREY forward-test cycle failed safely: %s", exc)
            time.sleep(LOOP_INTERVAL_SECONDS)
            continue

        time.sleep(LOOP_INTERVAL_SECONDS)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    run_forward_test_loop()


if __name__ == "__main__":
    main()
