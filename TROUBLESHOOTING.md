# GREY Troubleshooting

Use this guide when GREY does not start, data is missing, Telegram is silent, or Gemini reasoning falls back.

## SmartAPI Login Fails

Possible causes:

- `ANGEL_API_KEY`, `ANGEL_CLIENT_ID`, or `ANGEL_PIN` is wrong.
- TOTP is missing or expired.
- System clock is wrong.

Solutions:

- Check `ANGEL_API_KEY`, `ANGEL_CLIENT_ID`, and `ANGEL_PIN`.
- Prefer `ANGEL_TOTP_SECRET` over a one-time `ANGEL_TOTP`.
- Make sure the system clock is correct for TOTP.
- Restart GREY after changing `.env`.

## Rate Limit Errors

Possible causes:

- Too many SmartAPI calls in a short period.
- Multiple GREY instances running at the same time.
- Option-chain calls are too frequent.

Solutions:

- Increase `ANGEL_API_PAUSE_SECONDS` in `.env`.
- Keep GREY cycle frequency at 5 minutes.
- Avoid running multiple live GREY instances at the same time.
- Let PCR and OI cache settings do their job.

## VIX Data Missing

Possible causes:

- NSE temporarily blocks scraping.
- Internet connection is unstable.
- Fallback values are not configured.

Solutions:

- GREY will use VIX cache first.
- Add `GREY_FALLBACK_INDIA_VIX` and `GREY_FALLBACK_VIX_PREV_CLOSE` in `.env`.
- NSE scrape failure should not crash GREY; it should reduce confidence or use fallback context.

## Telegram Issues

### Telegram Not Sending

Possible causes:

- Bot token is wrong.
- Chat ID is wrong.
- The bot has not received an initial message.
- Telegram live reporting is disabled.

Solutions:

- Check `GREY_TELEGRAM_BOT_TOKEN`.
- Check `GREY_TELEGRAM_CHAT_ID`.
- Send one manual message to the bot before using `getUpdates`.
- Keep live Telegram disabled until dry-run formatting is verified.
- Run:

  ```bash
  python test_telegram_live_reporter.py
  ```

## Gemini Issues

### Gemini Returns `FALLBACK_TO_RULES`

Possible causes:

- `GOOGLE_GEMINI_API_KEY` is missing.
- `GREY_GEMINI_ENABLED` is not set to `True`.
- The `google-generativeai` package is not installed.
- Gemini initialization failed and GREY degraded safely.

Solutions:

- Check `.env`:

  ```env
  GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key_here
  GREY_GEMINI_ENABLED=True
  ```

- Install the dependency:

  ```bash
  pip install google-generativeai
  ```

- Run:

  ```bash
  python test_gemini_integration.py
  ```

- If needed, get a new key from `https://ai.google.dev/`.

### Gemini Reasoning Is Slow (>5 Seconds)

Possible causes:

- Network latency.
- Google API load.
- Local internet instability.
- Timeout is too strict for the current connection.

Solutions:

- Increase timeout in `.env`:

  ```env
  GREY_GEMINI_TIMEOUT=8
  ```

- Reduce frequency:

  ```env
  GREY_GEMINI_FREQUENCY=2
  ```

- Check the internet connection.
- Keep the default 5-minute GREY cycle; do not query Gemini every few seconds.

### Gemini Decision Does Not Match Rules

This can be normal and useful. GREY 2.0 compares rule-based signals, sentiment, options flow, microstructure, and Gemini reasoning. A disagreement can reveal:

- Retail sentiment versus smart money positioning
- Options flow contradicting price action
- Macro risk that rules did not fully capture
- A low-confidence environment where waiting is better

What to do:

- Do not force Gemini to match GREY rules.
- Check `gemini_vs_claude` and `module_vector`.
- Track whether Gemini disagreements helped after 15 minutes and in daily efficacy reports.

### Gemini API Key Invalid

Possible causes:

- Key was copied incorrectly.
- Key was revoked.
- Wrong Google project was used.
- Extra spaces were added in `.env`.

Solutions:

- Regenerate the key at `https://ai.google.dev/`.
- Copy it again into `.env`.
- Remove quotes and spaces around the key.
- Restart GREY.
- Run `python test_gemini_integration.py`.

## Daily Efficacy Report Is Empty

Possible causes:

- No signals were logged.
- OHLCV file is missing.
- Dates do not match.

Solutions:

- Confirm `journals/grey/phase1_signals.jsonl` exists.
- Confirm `journals/grey/enhanced_signals.jsonl` exists for GREY 2.0 review.
- Confirm an OHLCV CSV exists at `nifty_candles.csv` or set `GREY_EFFICACY_OHLCV_PATH`.
- Make sure signal timestamps and candle dates are for the same trading day.

## When to Contact Support

Collect these before asking for help:

- Screenshot or copy of the console error
- The command you ran
- Whether `.env` has Angel, Telegram, and Gemini values filled
- Output from `python test_gemini_integration.py`
- Output from `python test_live_data_providers.py`
- Latest file in `logs/`
- Whether GREY failed completely or safely returned fallback output
