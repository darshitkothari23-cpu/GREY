# GREY Market Intelligence Engine

GREY is a shadow-mode market intelligence and review system for NSE index options research. It is not a broker, order-entry system, or execution engine.

GREY 1.0 provides the rules-based foundation: 10 analysis modules, signal logging, 15-minute outcome evaluation, Telegram monitoring, and daily efficacy tracking. GREY is now range-bound focused for Iron Condor research: it measures whether actual NIFTY highs and lows stayed inside predicted bounds, not only whether direction was right.

GREY 2.0 keeps options-flow, microstructure, and optional AI reasoning layers. News aggregation and keyword sentiment are disabled because they were slow, noisy, and usually priced in before processing. Gemini is disabled by default and should be retained only if A/B testing proves more than 5 percentage points of accuracy lift.

GREY now tracks Expected Value (EV) after costs. Accuracy is not enough; profit after slippage, brokerage, and STT is what matters.

## Requirements

- Python 3.10+
- Angel One SmartAPI access
- Telegram bot, free via `@BotFather`
- Google Gemini API key, optional for Week 3 A/B testing
- Internet connection

## Key Features

- Phase 1 signal logging during Indian market hours
- 10 rules-based GREY modules for options, regime, VIX, PCR, expiry, OI, global, macro, sector, and data quality
- Range-bound accuracy tracking for Iron Condor viability
- Risk manager with daily loss limits, VIX-scaled lot sizing, and time-weighted short-premium stop levels
- Gemini A/B testing with `gemini-2.0-flash` disabled by default
- Expected Value tracking after costs
- Dynamic VIX caching: 60 seconds normally, 20 seconds when VIX is above 20
- Time-weighted stops: 50 percent first 30 minutes, 75 percent mid-trade, 100 percent late-trade
- Position sizing with volatility scaling: high VIX means smaller positions, low VIX allows larger positions
- Mandatory pre-shadow-mode backtest on 3 months historical NIFTY 1-minute data
- Smart money positioning detection from options flow and OI changes
- Microstructure analysis from spread, depth, volume imbalance, and large executions
- Contradiction detection across rules, options flow, Gemini, and Claude-style reasoning
- Multi-turn conversation context for AI reasoning
- Telegram live monitoring and 15-minute evaluation reports
- Daily efficacy reports for shadow-mode validation

## Quick Start

1. Copy `.env.example` to `.env`.

   ```bash
   copy .env.example .env
   ```

2. Add Angel One credentials and Telegram credentials to `.env`.

3. Optional: get a Gemini API key for Week 3 A/B testing.
   - Open `https://ai.google.dev/`
   - Click `Get API key`
   - Create or select a project
   - Copy the key into `.env`

4. Keep Gemini off for the baseline shadow-mode run.

   ```env
   GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key_here
   GREY_GEMINI_ENABLED=False
   GREY_A_B_TEST_MODE=True
   ```

5. Run tests.

   ```bash
   python -m pytest test_pre_shadow_mode.py
   python test_new_modules.py
   python test_live_data_providers.py
   python test_telegram_live_reporter.py
   python test_gemini_integration.py
   ```

6. Run the mandatory pre-shadow backtest before shadow mode.

   ```bash
   python grey_backtest_runner.py --data data/nifty_3months.csv
   ```

7. Start GREY 2.0 shadow mode only after the backtest and checklist pass.

   ```bash
   python grey_enhanced_phase1_engine.py
   ```

## How It Works

1. Every 5 minutes during market hours: GREY fetches live market data, runs rules-based modules, and builds a technical signal.
2. GREY 2.0 adds options flow, microstructure, risk controls, EV tracking, and optional Gemini reasoning.
3. GREY stores the enhanced signal and module vector for later review.
4. Parallel A/B testing logs baseline and Gemini variants on the same market tick for fair comparison.
5. Every 15 minutes: GREY checks whether a past signal was useful and sends a Telegram report.
6. Every day at 3:30 PM: GREY measures accuracy, EV, range-bound fit, ATR-adjusted range fit, and A/B lift.
7. After 4 weeks: review range-bound accuracy, EV, risk decisions, Gemini usefulness, and false-confidence behavior before deciding what to do next.

## Mandatory Pre-Shadow Backtest

Pre-shadow-mode backtesting is mandatory. Run GREY on 3 months of NIFTY 1-minute historical data before Monday 9:15 AM shadow mode. Do not skip this step. If simulated EV is negative, shadow mode will likely confirm that the system has no usable edge. If simulated EV is positive, shadow mode has a chance, but it is still not proof.

## Parallel A/B Testing

Gemini is tested fairly against baseline on identical market conditions. Every signal logs baseline direction, confidence, and score, plus Gemini direction, confidence, and score. End-of-shadow analysis should compare exact same-tick outcomes, not Week 1 versus Week 3 market regimes.

## Expected Outcome

Expected shadow-mode outcome: 75 percent chance GREY shows negative or marginal EV and does not work, 25 percent chance it is viable enough for further paper-trading review. This system is a hypothesis, not a guarantee.

## Project Status

- Phase 1 Engine: Complete
- 10 Modules: Complete
- GREY 2.0 Data Layer: Complete
- Gemini AI Integration: Optional A/B test
- Risk Manager: Complete
- Telegram Monitoring: Complete
- Efficacy Tracking: Complete
- Live Deployment: Ready for 4-week shadow mode

## Expected Accuracy

- Current estimate: unknown until shadow-mode data is collected
- Viable target: 70%+ range-bound accuracy for Iron Condors
- Directional target: 65%+ directional usefulness if directional overlays are considered
- Marginal range: 60-70% range-bound, requires redesign
- Not viable: below 55% directional, below 60% range-bound, or if signals are late, noisy, or overconfident
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
