# GREY Review Module Inventory

These files are review-side GREY modules. They provide market context, checks, AI reasoning, summaries, and smoke testing. They do not place trades.

## Core GREY 1.0 and Phase 1 Files

| File | Main class | Type | Key methods | Plain-English purpose |
| --- | --- | --- | --- | --- |
| `grey_config.py` | n/a | Support module | n/a | Stores GREY configuration defaults and feature switches. |
| `grey_session_machine.py` | `GreySessionMachine` | Support module | `get_current_state`, `is_expiry_sensitive`, `get_session_weights` | Identifies the current market session phase and adjusts module weights by phase. |
| `market_calendar.py` | `MarketCalendar` | Support module | `get_next_event_minutes`, `has_pre_event`, `get_todays_events` | Looks up local scheduled events so GREY can detect pre-event periods. |
| `grey_options_microstructure.py` | `GreyOptionsMicrostructure` | Analysis module | `evaluate` | Checks whether option premium conditions look attractive or expensive. |
| `grey_regime_engine.py` | `GreyRegimeEngine` | Analysis module | `evaluate` | Labels the market as trending, range-bound, volatile, event-risk, or low-participation. |
| `grey_global_risk_module.py` | `GreyGlobalRiskModule` | Analysis module | `evaluate` | Summarizes overnight and global cues such as GIFT Nifty, Asia, US futures, and volatility proxies. |
| `grey_india_macro_module.py` | `GreyIndiaMacroModule` | Analysis module | `evaluate` | Summarizes India-specific context from USDINR, crude, and liquidity or rates data. |
| `grey_sector_rotation_module.py` | `GreySectorRotationModule` | Analysis module | `evaluate` | Checks whether index movement is broad, narrow, bank-led, sector-led, or weakening internally. |
| `grey_data_quality_guard.py` | `GreyDataQualityGuard` | Guard module | `evaluate` | Flags missing, stale, noisy, contradictory, or unreliable inputs and suggests confidence caps. |
| `grey_signal_aggregator.py` | `GreySignalAggregator` | Aggregator | `aggregate` | Combines module outputs into one readable GREY composite view while preserving conflicts and top drivers. |
| `grey_phase1_engine.py` | `GreyPhase1Engine`, `GreySignalStore`, `GreyTelegramNotifier` | Support module | `run_cycle`, `run_once`, `evaluate_due_signals`, `format_telegram_message` | Runs Phase 1 signal logging, 15-minute review, and Telegram-style reporting. |
| `grey_evaluation_tracker.py` | `GreyEvaluationTracker` | Support module | `record_snapshot`, `finalize_day`, `score_prediction_timing` | Reviews how useful modules were through the day, including early warnings, late signals, and wrong confidence. |
| `grey_daily_report.py` | `GreyDailyReport` | Report | `build_report` | Builds a simple end-of-day report from tracker and aggregator output. |

## GREY 2.0 Enhanced Files

| File | Main class | Type | Key methods | Plain-English purpose |
| --- | --- | --- | --- | --- |
| `grey_live_data_provider.py` | `GreyLiveDataProvider` | Support module | `get_market_context`, `fetch_live_market_data` | Combines broker, VIX, PCR, and OI context into one market-data packet. |
| `grey_news_aggregator.py` | `GreyNewsAggregator` | Analysis module | `collect`, `score_relevance` | Collects and scores relevant market news for NIFTY context. |
| `grey_sentiment_engine.py` | `GreySentimentEngine` | Analysis module | `analyze` | Summarizes news and optional social sentiment into consensus and contradictions. |
| `grey_options_flow_monitor.py` | `GreyOptionsFlowMonitor` | Analysis module | `analyze` | Detects unusual option activity, put walls, call walls, and OI change rates. |
| `grey_microstructure_analyzer.py` | `GreyMicrostructureAnalyzer` | Analysis module | `analyze` | Reviews bid-ask spread, depth, volume imbalance, and large execution pressure. |
| `grey_reasoning_engine.py` | `GreyReasoningEngine` | Reasoning module | `analyze` | Provides optional Claude-style reasoning or local fallback reasoning. |
| `grey_gemini_reasoning_engine.py` | `GreyGeminiReasoningEngine` | Reasoning module | `analyze_market` | Uses Gemini `gemini-2.0-flash` for market reasoning, contradiction detection, and fallback-safe AI context. |
| `grey_enhanced_phase1_engine.py` | `GreyEnhancedPhase1Engine` | Aggregator/runner | `run_once`, `run_loop` | Runs GREY 2.0 enhanced cycles and logs enhanced signals. |

## Data, Reporting, And Tests

| File | Main class | Type | Key methods | Plain-English purpose |
| --- | --- | --- | --- | --- |
| `grey_vix_data_provider.py` | `GreyVixDataProvider` | Data provider | `get_vix_data` | Gets India VIX with cache and fallback behavior. |
| `grey_pcr_calculator.py` | `GreyPcrCalculator` | Data provider | `calculate` | Calculates PCR and option-wall weights from limited option-chain rows. |
| `grey_oi_tracker.py` | `GreyOiTracker` | Data provider | `update_and_calculate` | Tracks OI baseline and percentage changes. |
| `generate_daily_efficacy.py` | n/a | Report script | `main` | Builds daily efficacy reports after market close. |
| `grey_smoke_test.py` | `main` | Test | `main` | Runs a lightweight dummy flow to confirm GREY review modules work together. |
| `grey_phase1_smoke_test.py` | `main` | Test | `main` | Checks Phase 1 logging, delayed evaluation, and Telegram dry-run reporting. |
| `test_gemini_integration.py` | n/a | Test | test functions | Checks Gemini initialization, fallback, prompt formatting, parsing, and enhanced-engine integration. |
| `test_grey2_enhanced.py` | n/a | Test | test function | Checks GREY 2.0 enhanced dummy cycle. |

## Operator Notes

- Analysis modules explain market context; they do not decide actions.
- Gemini and Claude-style reasoning are review layers, not trading engines.
- Guard modules help reduce confidence when data quality is doubtful.
- The aggregator keeps disagreements visible instead of hiding them behind one number.
- The tracker and report help review what was useful, late, or misleading after the day is complete.
- Shadow mode should run for 4 weeks before any paper-trading decision.
