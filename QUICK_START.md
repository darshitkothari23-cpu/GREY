# GREY Quick Start

This is the shortest path to run GREY 2.0 with Gemini in shadow mode.

## First Run

1. Copy `.env.example` to `.env`.
2. Add Angel One credentials.
3. Add Telegram bot token and chat ID if Telegram reports are needed.
4. Get a Gemini API key from `https://ai.google.dev/`.
5. Add `GOOGLE_GEMINI_API_KEY` to `.env`.
6. Set `GREY_GEMINI_ENABLED=True`.
7. Run tests.
8. Start shadow mode during market hours.

## Commands

```bash
python test_new_modules.py
python test_live_data_providers.py
python test_telegram_live_reporter.py
python test_gemini_integration.py
python test_grey2_enhanced.py
python grey_enhanced_phase1_engine.py
```

## Morning Start

Run this before or near market open:

```bash
python grey_enhanced_phase1_engine.py
```

Expected output includes a GREY 2.0 signal and Gemini status:

```text
GREY 2.0 Enhanced Signal
Symbol: NIFTY
Direction: BULL
Composite score: 0.36
Confidence: 0.60
Gemini reasoning: MILD_BULL confidence=0.70
Reasoning agreement: Reasoning models agree on BULL bias.
```

If the Gemini API key is missing, GREY should continue and show:

```text
Gemini reasoning: FALLBACK_TO_RULES confidence=0.0
Gemini insight: Gemini API unavailable or disabled
```

That is safe fallback behavior, not a crash.

## Gemini Reasoning

Gemini adds AI-powered market reasoning on top of GREY's rules-based signal. It reviews:

- Contradictions between technicals, sentiment, flow, and macro context
- Smart money versus retail divergence
- Put wall and call wall behavior
- Whether the market may be underpricing event risk
- What could break the current view
- Recent context through multi-turn conversation memory

Example Telegram-style note:

```text
GREY: NIFTY EARLY_TREND
Direction: BULL
Confidence: 0.62
Gemini: MILD_BULL | confidence 0.70
Insight: Put support is building while sentiment is cautious; this can indicate smart money support against retail fear.
15-min result: pending
```

## Daily Checklist

Before market:

- Confirm `.env` is filled.
- Confirm Gemini is enabled if you want AI reasoning.
- Start GREY and watch for one clean cycle.
- Confirm Telegram is receiving messages.

During market:

- Do not manually interfere with signals.
- Check that Gemini reasoning makes sense.
- Note any major contradictions Gemini identifies.
- Track whether Gemini appears right or wrong, but do not change rules intraday.
- Monitor Gemini token/cost log if using a real key.

After market:

- Run the daily efficacy report.
- Review whether rules, Gemini, or both were useful.
- Record false confidence, late signals, and missed warnings.

## Daily Report

Run this after market close or schedule it for 3:30 PM:

```bash
python generate_daily_efficacy.py
```

Reports are saved in `daily_reports/`.

## After 5 Days

Ask:

- Did Gemini add value versus rules-based GREY?
- Did Gemini improve accuracy?
- Did Gemini give different signals or just repeat the module output?
- Did Gemini catch contradictions before large moves?
- Was latency acceptable?
- Was cost acceptable?

Do not judge the system from one day. Use at least 5 days for early impressions and 4 weeks for the real decision.
