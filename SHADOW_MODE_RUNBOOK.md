# GREY Shadow Mode Runbook

## Week 1: Baseline

Run with `GREY_GEMINI_ENABLED=False`, `GREY_DISABLE_NEWS=True`, and `GREY_DISABLE_SENTIMENT=True`. Measure both directional accuracy and range-bound accuracy in the daily efficacy report. Do not paper trade.

## Week 2: Range Focus

Set `GREY_USE_RANGE_BOUND_EVALUATION=True`. Review whether predicted highs and lows contain actual NIFTY movement. Range-bound accuracy is the key Iron Condor viability metric.

## Week 3: Gemini A/B Test

Keep `GREY_A_B_TEST_MODE=True`. Compare `version_A_with_gemini` and `version_B_without_gemini` in the enhanced journal. Keep Gemini only if the Gemini arm beats baseline by more than 5 percentage points.

## Week 4: Final Data

Compile at least 20 trading days or signal-level records. Confirm daily reports include `directional_accuracy`, `range_bound_accuracy`, module scorecards, and A/B metadata where enabled.

## Decision Criteria

- Go: range-bound accuracy above 70 percent, no repeated risk-manager blocks, no major data-quality failures.
- Maybe: range-bound accuracy from 60 to 70 percent or directional accuracy from 55 to 60 percent. Redesign before paper trading.
- No-go: range-bound accuracy below 60 percent, directional accuracy below 55 percent, unstable data provider, or Gemini lift at 5 percent or less.
