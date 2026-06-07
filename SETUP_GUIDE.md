# GREY Setup Guide

This guide prepares GREY 1.0, GREY 2.0, Telegram monitoring, daily efficacy tracking, and Gemini reasoning for 4-week shadow mode.

GREY is not a broker or execution system. It only collects context, scores market conditions, logs signals, and reviews outcomes.

## 1. Create Environment

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

## 2. Install Packages

```bash
pip install pandas numpy python-dotenv pyotp smartapi-python logzero requests pycryptodome websocket-client pyyaml huggingface_hub google-generativeai
```

`google-generativeai` is used only when Gemini is enabled.

## 2.5. Google Gemini Setup (5 Minutes)

Gemini gives GREY 2.0 a free AI reasoning layer through Google's `gemini-2.0-flash` model.

1. Open `https://ai.google.dev/`.
2. Click `Get API key`.
3. Create a new project or select an existing project.
4. Copy the API key. It usually starts with `AIzaSyD`.
5. Add it to `.env`:

   ```env
   GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key_here
   GREY_GEMINI_ENABLED=True
   GREY_GEMINI_FREQUENCY=1
   GREY_GEMINI_MIN_CONFIDENCE=0.55
   GREY_GEMINI_TIMEOUT=5
   ```

Cost note: the Gemini free tier is enough for GREY's 5-minute shadow-mode cycle. The code logs estimated tokens and daily estimated cost in `logs/gemini_reasoning.jsonl`.

Verify Gemini fallback and integration:

```bash
python test_gemini_integration.py
```

Expected final line:

```text
gemini integration OK
```

## 3. Create `.env`

```bash
copy .env.example .env
```

Open `.env` and fill in:

- Angel One SmartAPI credentials
- Telegram bot token and chat ID
- Gemini API key
- Optional VIX/PCR/OI fallback settings

Minimum Gemini fields:

```env
GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key_here
GREY_GEMINI_ENABLED=True
```

## 4. Verify Local Tests

```bash
python test_new_modules.py
python test_live_data_providers.py
python test_telegram_live_reporter.py
python test_gemini_integration.py
python test_grey2_enhanced.py
```

If Gemini is disabled or the key is missing, the Gemini test should still pass because GREY falls back safely.

## 5. Start GREY

For GREY 1.0 Phase 1 live forward testing:

```bash
python grey_live_forward_tester.py
```

For GREY 2.0 enhanced mode with Gemini reasoning:

```bash
python grey_enhanced_phase1_engine.py
```

By default, `grey_enhanced_phase1_engine.py` runs one safe cycle. To run every 5 minutes:

```bash
set GREY2_LOOP=True
python grey_enhanced_phase1_engine.py
```

For one-click startup on Windows, use `start_grey.bat` or `start_grey_with_kronos.bat`.

## 6. Schedule Daily Execution

GREY 2.0 includes Gemini AI reasoning once `.env` is configured. No extra daily Gemini command is needed.

Market-hours workflow:

1. Start GREY before 9:15 AM IST.
2. Let GREY run every 5 minutes.
3. Let Telegram report live module scores and 15-minute evaluation results.
4. At 3:30 PM, run:

   ```bash
   python generate_daily_efficacy.py
   ```

5. Review `daily_reports/` after market close.

Windows Task Scheduler commands:

```bash
python grey_enhanced_phase1_engine.py
python generate_daily_efficacy.py
```

## 7. Shadow Mode Rules

- Do not use GREY as an execution engine.
- Do not change module logic during the 4-week test unless something is technically broken.
- Track whether Gemini improves decisions or only repeats existing module output.
- Review daily reports, not individual intraday guesses.

## 8. After 4 Weeks

Use the efficacy reports to decide:

- Continue research if useful accuracy is 70%+.
- Continue shadow mode if accuracy is 60-70% and improving.
- Redesign if accuracy is below 55% or confidence is misleading.
- Keep Gemini only if it improves accuracy, catches contradictions, or gives useful risk context.
