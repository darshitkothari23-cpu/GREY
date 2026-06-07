# Gemini Setup for GREY 2.0

## What Is Gemini?

Gemini is Google's AI model family. GREY 2.0 uses Gemini through the free API tier to add real-time market reasoning on top of the rules-based GREY modules.

Gemini helps GREY:

- Analyze contradictions between signals
- Provide a professional trader-style perspective
- Compare smart money positioning with retail sentiment
- Maintain short multi-turn conversation context
- Respond quickly through `gemini-2.0-flash`
- Run at low or zero cost during normal shadow-mode testing

GREY still does not place trades. Gemini is used for reasoning and review only.

## Getting Started (5 Minutes)

### Step 1: Get API Key

1. Go to `https://ai.google.dev/`.
2. Click `Get API key`.
3. Create a new project or select an existing project.
4. Copy the key. It usually starts with `AIzaSyD`.

### Step 2: Add Gemini Settings To `.env`

Copy `.env.example` to `.env` if you have not already done that:

```bash
copy .env.example .env
```

Add or update these values:

```env
GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key_here
GREY_GEMINI_ENABLED=True
GREY_GEMINI_FREQUENCY=1
GREY_GEMINI_MIN_CONFIDENCE=0.55
GREY_GEMINI_TIMEOUT=5
```

### Step 3: Test Gemini

```bash
python test_gemini_integration.py
```

Expected final output:

```text
gemini integration OK
```

This test also works when the API key is missing, because GREY must prove that fallback behavior is safe.

### Step 4: Run GREY 2.0

```bash
python grey_enhanced_phase1_engine.py
```

To run every 5 minutes:

```bash
set GREY2_LOOP=True
python grey_enhanced_phase1_engine.py
```

## How Gemini Works

Each GREY 2.0 cycle follows this flow:

1. GREY collects live market data.
2. Rules-based modules score the market.
3. News and sentiment modules summarize outside context.
4. Options flow and microstructure modules inspect market plumbing.
5. Gemini receives the full context.
6. Gemini answers what is happening, what is contradictory, what is not obvious, and what could break the view.
7. GREY reconciles Gemini with technical and Claude-style reasoning.
8. GREY logs the enhanced signal for later review.
9. Telegram can show the Gemini decision and key insight.

## What Gemini Will Say

### Example 1: Smart Money Buying

```text
Decision: MILD_BULL
Reasoning: Price action is steady while put support is building. Retail sentiment is cautious, but options positioning suggests larger participants are supporting dips.
Risk: A volatility spike or failed breakout can invalidate this view.
```

### Example 2: Consensus Signals

```text
Decision: STRONG_BULL
Reasoning: Price, breadth, put OI, microstructure, and global cues are aligned. There are few contradictions, so the bullish view has stronger confirmation.
Risk: Avoid overconfidence near event windows.
```

### Example 3: Mixed Signals

```text
Decision: WAIT_FOR_CLARITY
Reasoning: Technical modules are bullish, but sentiment and microstructure are not confirming. The market may be underpricing event risk.
Risk: A false breakout is possible.
```

## Cost

For normal GREY shadow mode, Gemini free tier is expected to be enough:

- Free tier: about 15 requests/minute
- GREY default: 1 request every 5 minutes
- Estimated monthly cost during shadow mode: $0/month under normal free-tier usage

GREY logs estimated token use and estimated daily cost in:

```text
logs/gemini_reasoning.jsonl
```

Paid-tier pricing can change. Check Google AI Studio for current pricing before increasing frequency.

## Configuration Options

| Variable | Meaning | Suggested value |
| --- | --- | --- |
| `GOOGLE_GEMINI_API_KEY` | Your Google Gemini API key | Your key from `https://ai.google.dev/` |
| `GREY_GEMINI_ENABLED` | Turns Gemini reasoning on/off | `True` |
| `GREY_GEMINI_FREQUENCY` | Query every N GREY cycles | `1` |
| `GREY_GEMINI_MIN_CONFIDENCE` | Skip Gemini if technical confidence is already high | `0.55` |
| `GREY_GEMINI_TIMEOUT` | Max seconds to wait for Gemini | `5` |

## Comparing Results

After 1 week, compare:

- GREY 1.0 rules-only signal accuracy
- GREY 2.0 enhanced signal accuracy
- Gemini decisions versus final market movement
- Gemini disagreements versus rules-based GREY
- Whether Gemini caught risks before the modules did
- Whether Gemini latency was acceptable

Useful review questions:

- Did Gemini improve accuracy?
- Did Gemini reduce false confidence?
- Did Gemini produce different insight?
- Did Gemini identify smart money positioning earlier?
- Did Gemini add noise?

## Troubleshooting

### Gemini Falls Back

Check:

```env
GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key_here
GREY_GEMINI_ENABLED=True
```

Then run:

```bash
python test_gemini_integration.py
```

### Gemini Is Slow

Increase timeout:

```env
GREY_GEMINI_TIMEOUT=8
```

Or reduce frequency:

```env
GREY_GEMINI_FREQUENCY=2
```

### Gemini Disagrees With GREY

That is expected sometimes. The point is to identify contradictions, not force agreement. Track whether those disagreements helped during the daily efficacy review.

### Invalid API Key

Regenerate the key at `https://ai.google.dev/`, update `.env`, restart GREY, and run the Gemini test again.

## After 4 Weeks

You should know:

- Did Gemini improve GREY accuracy?
- By how much?
- Did Gemini catch contradictions earlier?
- Was the reasoning useful or repetitive?
- Was latency acceptable?
- Was the free tier enough?
- Should Gemini stay enabled for the next research phase?

Decision guide:

- Keep Gemini if it improves useful accuracy by more than 5 percentage points or catches important risks early.
- Keep testing if results are mixed but promising.
- Disable Gemini if it adds latency, noise, or repeated explanations without measurable benefit.
