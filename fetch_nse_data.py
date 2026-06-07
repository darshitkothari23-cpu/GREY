"""
Download recent NIFTY 50 candles for Kronos fine-tuning.

This script uses the same Angel One SmartAPI login path as GREY's live forward
tester and writes `nifty_candles.csv` in the current folder.
"""

from __future__ import annotations

from pathlib import Path

from grey_live_forward_tester import LiveMarketDataClient, MarketDataError, RateLimitError


def main() -> None:
    """Fetch the last 512 NIFTY 15-minute candles and save them as CSV."""
    print("Step 1: Loading Angel One credentials from .env...")
    output_path = Path("nifty_candles.csv")

    try:
        # This client handles .env loading, SmartAPI login, and TOTP generation.
        client = LiveMarketDataClient()
        print("Step 2: Connecting to Angel One SmartAPI...")

        # This fetches exactly the candle format Kronos needs.
        candles = client.fetch_recent_ohlcv(
            symbol="NIFTY",
            interval="FIFTEEN_MINUTE",
            count=512,
        )
        print(f"Step 3: Downloaded {len(candles)} candles.")

        # Keep only the requested columns in the requested order.
        candles = candles[["timestamp", "open", "high", "low", "close", "volume"]]

        # Save the file in the GREY folder so the fine-tune script can find it.
        candles.to_csv(output_path, index=False)
        print(f"Step 4 done: Saved candles to {output_path}")
    except RateLimitError:
        print("Rate limit exceeded. Please wait a minute and run this script again.")
    except MarketDataError as exc:
        print(f"Angel One data error: {exc}")
    except Exception as exc:
        print(f"Unexpected error while fetching NSE data: {exc}")


if __name__ == "__main__":
    main()
