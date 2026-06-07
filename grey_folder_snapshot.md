# GREY Review Folder Snapshot

This is a simple snapshot of the current GREY review folder. Generated cache folders are not listed.

## Top-Level Python Files

| File | Short note |
| --- | --- |
| `grey_config.py` | Main GREY review configuration values. |
| `grey_session_machine.py` | Tracks the current market session phase. |
| `market_calendar.py` | Local event calendar helper for pre-event checks. |
| `grey_options_microstructure.py` | Reviews option premium and liquidity conditions. |
| `grey_regime_engine.py` | Classifies the broad market regime. |
| `grey_global_risk_module.py` | Summarizes overnight and global risk context. |
| `grey_india_macro_module.py` | Summarizes USDINR, crude, and India liquidity context. |
| `grey_sector_rotation_module.py` | Reviews sector leadership and market breadth. |
| `grey_data_quality_guard.py` | Flags stale, missing, broken, or conflicting inputs. |
| `grey_signal_aggregator.py` | Combines module outputs into one GREY composite view. |
| `grey_phase1_engine.py` | Runs Phase 1 signal logging, delayed review, and Telegram-style reporting. |
| `grey_live_forward_tester.py` | Live shadow-mode bridge for broker data. |
| `grey_live_data_provider.py` | Master market-context provider for GREY. |
| `grey_news_aggregator.py` | Collects and scores market news. |
| `grey_sentiment_engine.py` | Aggregates news and optional social sentiment. |
| `grey_options_flow_monitor.py` | Monitors unusual options flow and OI changes. |
| `grey_microstructure_analyzer.py` | Analyzes spread, depth, volume imbalance, and large orders. |
| `grey_reasoning_engine.py` | Optional Claude-style reasoning engine with local fallback. |
| `grey_gemini_reasoning_engine.py` | Gemini reasoning engine with fallback, history, timeout, and token logging. |
| `grey_enhanced_phase1_engine.py` | Runs GREY 2.0 enhanced signal generation. |
| `grey_evaluation_tracker.py` | Reviews module usefulness through the day. |
| `grey_daily_report.py` | Builds an end-of-day GREY report. |
| `generate_daily_efficacy.py` | Creates the daily efficacy report file. |
| `grey_smoke_test.py` | Runs a lightweight dummy integration check. |
| `grey_phase1_smoke_test.py` | Runs a lightweight Phase 1 flow check. |
| `test_gemini_integration.py` | Tests Gemini setup, fallback, parsing, and enhanced integration. |
| `test_grey2_enhanced.py` | Tests a GREY 2.0 enhanced dummy cycle. |

## Top-Level Markdown Files

| File | Short note |
| --- | --- |
| `README.md` | Main project overview and status. |
| `SETUP_GUIDE.md` | Full setup instructions. |
| `QUICK_START.md` | Short operator runbook. |
| `GEMINI_SETUP.md` | Dedicated Gemini API setup and validation guide. |
| `GREY2_ENHANCED_README.md` | GREY 2.0 component and reasoning overview. |
| `PROJECT_STATUS.md` | Current completion and shadow-mode plan. |
| `TROUBLESHOOTING.md` | Common fixes for data, Telegram, and Gemini issues. |
| `grey_module_inventory.md` | Human-readable inventory of GREY review modules. |
| `grey_folder_snapshot.md` | This folder snapshot. |

## Subfolders

| Folder | Contents | Short note |
| --- | --- | --- |
| `data/` | Event calendar and live cache files | Local data and cache storage. |
| `daily_reports/` | Efficacy report JSON files | End-of-day review outputs. |
| `journals/grey/` | Signal JSONL files | Phase 1 and enhanced signal logs. |
| `logs/` | Runtime and test logs | Operational logs, including Gemini token estimates. |
| `modules/` | `grey_module_base.py`, `grey_calendar_module.py` | Shared module base and calendar risk-gate module. |

## Notes

- The review folder is self-contained for smoke testing with dummy data.
- `__pycache__/` folders may appear after Python runs; they are generated cache and not part of the review design.
- GREY 2.0 is ready for 4-week shadow-mode deployment once `.env` is filled.
