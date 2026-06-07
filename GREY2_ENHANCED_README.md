# GREY 2.0 Enhanced Intelligence Layer

GREY 2.0 adds a data layer and reasoning engines on top of the existing Phase 1 technical engine. It combines news, sentiment, options flow, microstructure, Gemini reasoning, and optional Claude-style reasoning into one enhanced market-intelligence signal.

Gemini is the recommended default AI reasoning path because the free tier is sufficient for GREY's 5-minute shadow-mode cycle. Claude is optional and typically paid. Both reasoning engines use recent conversation context, analyze contradictions, and return structured decisions without placing trades.

GREY remains a review system. It does not connect AI output to broker orders, position management, or execution behavior.

## How To Run

One safe cycle:

```bash
python grey_enhanced_phase1_engine.py
```

Every 5 minutes:

```bash
set GREY2_LOOP=True
python grey_enhanced_phase1_engine.py
```

## GREY 2.0 Components

- `grey_news_aggregator.py`: collects RSS/NSE-style market news, caches it, and scores NIFTY relevance.
- `grey_sentiment_engine.py`: combines news and optional Twitter, Reddit, and StockTwits text supplied by your data layer.
- `grey_options_flow_monitor.py`: detects unusual options activity, OI change rates, put walls, call walls, and smart positioning.
- `grey_microstructure_analyzer.py`: checks bid-ask spread, depth, volume imbalance, and large execution pressure.
- `grey_reasoning_engine.py`: optional Claude-style reasoning with local fallback.
- `grey_gemini_reasoning_engine.py`: Gemini reasoning with `gemini-2.0-flash`, fallback, conversation history, timeout, and token logging.
- `grey_enhanced_phase1_engine.py`: runs the full enhanced cycle and appends records to `journals/grey/enhanced_signals.jsonl`.

## Gemini Reasoning

Gemini receives a compact market context:

- Price data: spot, ATR, range
- News and sentiment: headlines, social sentiment, surprise
- Options positioning: put walls, call walls, PCR, unusual OI
- Macro context: GIFT Nifty, US futures, VIX, FII flow
- Microstructure: spread, volume profile, aggression

Gemini is asked:

- What is happening right now?
- What contradictions exist?
- What is not obvious but important?
- What could break the view?
- What is the market underpricing?
- What would a professional trader consider?

The output is stored as:

- `gemini_reasoning`
- `claude_reasoning`
- `gemini_vs_claude`
- `enhanced_signal`

## Optional Environment Variables

Core GREY 2.0:

- `GREY2_DUMMY_MODE=True`: safe dummy mode.
- `GREY2_LOOP=False`: set to `True` for the five-minute loop.
- `GREY2_INTERVAL_SECONDS=300`: loop delay.
- `GREY_NEWS_CACHE_SECONDS=300`: news cache lifetime.

Gemini:

- `GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key_here`
- `GREY_GEMINI_ENABLED=True`
- `GREY_GEMINI_FREQUENCY=1`
- `GREY_GEMINI_MIN_CONFIDENCE=0.55`
- `GREY_GEMINI_TIMEOUT=5`

Claude-style optional reasoning:

- `GREY_REASONING_ENABLED=False`
- `ANTHROPIC_API_KEY=your_key_here`
- `GREY_CLAUDE_MODEL=claude-3-5-sonnet-latest`

Options and flow:

- `GREY_NIFTY_LOT_SIZE=75`
- `GREY_OPTIONS_FLOW_CACHE_SECONDS=60`
- `GREY_LARGE_ORDER_THRESHOLD_QTY=5000`

## Testing

```bash
python test_gemini_integration.py
python test_grey2_enhanced.py
```

Expected lines:

```text
gemini integration OK
grey2 enhanced OK
```

## Shadow Mode Review

During the 4-week test, track:

- Rules-only GREY accuracy
- GREY 2.0 enhanced accuracy
- Gemini decision accuracy
- Gemini disagreements with rules
- Gemini latency
- Whether Gemini catches smart money positioning or hidden risks earlier

Keep Gemini if it improves useful accuracy by more than 5 percentage points, reduces false confidence, or consistently identifies important contradictions. Disable it if it adds latency or noise without measurable benefit.

## Related Docs

- [Gemini Setup](./GEMINI_SETUP.md)
- [Quick Start](./QUICK_START.md)
- [Setup Guide](./SETUP_GUIDE.md)
- [Troubleshooting](./TROUBLESHOOTING.md)
- [Project Status](./PROJECT_STATUS.md)
