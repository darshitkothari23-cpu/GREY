# GREY Market Intelligence Engine

GREY is a shadow-mode market intelligence and review system for NSE index options research. It is not a broker, order-entry system, or execution engine.

GREY 1.0 provides the rules-based foundation: 10 analysis modules, signal logging, 15-minute outcome evaluation, Telegram monitoring, and daily efficacy tracking. GREY 2.0 adds real-time news, sentiment, options-flow, microstructure, and AI reasoning layers.

GREY 2.0 now includes Google Gemini reasoning through `gemini-2.0-flash`. Gemini reviews the full market context, looks for contradictions between signals, highlights what may be underpriced, and helps detect smart money positioning versus noisy retail sentiment. It uses short multi-turn conversation context so each cycle can benefit from recent market state without becoming a trading or execution system.

## Requirements

- Python 3.10+
- Angel One SmartAPI access
- Telegram bot, free via `@BotFather`
- Google Gemini API key, free tier is sufficient
- Internet connection

## Key Features

- Phase 1 signal logging during Indian market hours
- 10 rules-based GREY modules for options, regime, VIX, PCR, expiry, OI, global, macro, sector, and data quality
- GREY 2.0 news aggregation from market RSS/NSE-style sources
- Market sentiment aggregation from news and optional social inputs
- Real-time Gemini AI reasoning with `gemini-2.0-flash`
- Smart money positioning detection from options flow and OI changes
- Microstructure analysis from spread, depth, volume imbalance, and large executions
- Contradiction detection across rules, sentiment, options flow, Gemini, and Claude-style reasoning
- Multi-turn conversation context for AI reasoning
- Telegram live monitoring and 15-minute evaluation reports
- Daily efficacy reports for shadow-mode validation

## Quick Start

1. Copy `.env.example` to `.env`.

   ```bash
   copy .env.example .env
   ```

2. Add Angel One credentials and Telegram credentials to `.env`.

3. Get a Gemini API key:
   - Open `https://ai.google.dev/`
   - Click `Get API key`
   - Create or select a project
   - Copy the key into `.env`

4. Enable Gemini in `.env`.

   ```env
   GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key_here
   GREY_GEMINI_ENABLED=True
   ```

5. Run tests.

   ```bash
   python test_new_modules.py
   python test_live_data_providers.py
   python test_telegram_live_reporter.py
   python test_gemini_integration.py
   ```

6. Start GREY 2.0 shadow mode.

   ```bash
   python grey_enhanced_phase1_engine.py
   ```

## How It Works

1. Every 5 minutes during market hours: GREY fetches live market data, runs rules-based modules, and builds a technical signal.
2. GREY 2.0 adds news, sentiment, options flow, microstructure, and Gemini reasoning.
3. GREY stores the enhanced signal and module vector for later review.
4. Every 15 minutes: GREY checks whether a past signal was useful and sends a Telegram report.
5. Every day at 3:30 PM: GREY measures module accuracy and writes a daily efficacy report.
6. After 4 weeks: review accuracy, latency, Gemini usefulness, and false-confidence behavior before deciding what to do next.

## Project Status

- Phase 1 Engine: Complete
- 10 Modules: Complete
- GREY 2.0 Data Layer: Complete
- Gemini AI Integration: Complete
- Telegram Monitoring: Complete
- Efficacy Tracking: Complete
- Live Deployment: Ready for 4-week shadow mode

## Expected Accuracy

- Current estimate: unknown until shadow-mode data is collected
- Viable target: 70%+ directional usefulness with controlled false confidence
- Marginal range: 60-70%, requires deeper review
- Not viable: below 55%, or if signals are late, noisy, or overconfident
- Profitability: unknown; GREY must prove usefulness before any paper-trading decision

## Testing

```bash
# Test all rules-based modules
python test_new_modules.py

# Test data providers
python test_live_data_providers.py

# Test Telegram
python test_telegram_live_reporter.py

# Test Gemini integration
python test_gemini_integration.py

# Test GREY 2.0 enhanced engine
python test_grey2_enhanced.py
```

## Documentation

- [Setup Guide](./SETUP_GUIDE.md)
- [Quick Start](./QUICK_START.md)
- [Gemini Setup](./GEMINI_SETUP.md)
- [GREY 2.0 Enhanced README](./GREY2_ENHANCED_README.md)
- [Project Status](./PROJECT_STATUS.md)
- [Troubleshooting](./TROUBLESHOOTING.md)
- [Module Inventory](./grey_module_inventory.md)
- [Folder Snapshot](./grey_folder_snapshot.md)

## Security

- All credentials stay in `.env`
- `.env` is listed in `.gitignore`
- Only `.env.example` should be committed
- API keys should never be logged or shared
- GREY logs decisions and estimated token use, not secrets

## License

Private project

## Author

Built for NSE options trading research
