# GREY Deep Review Feedback

## Critical Issues

1. Gemini parsing was unreliable because free-form text was converted into decisions by keyword counting. Gemini is now disabled by default and, when used, must return structured JSON: `decision`, `confidence`, and `reasoning`.
2. Module weights are guessed rather than learned from live shadow-mode outcomes. Week 5 must use `LogisticWeightOptimizer` to learn weights from at least 20 daily records.
3. GREY was optimized around directional signal labels while the intended trade style is Iron Condors, which need range-bound accuracy. Daily efficacy now reports both `directional_accuracy` and `range_bound_accuracy`.
4. News aggregation and keyword sentiment added latency and noise without proven predictive value. They are disabled by default and archived from the active engine path.
5. Short-premium strategy had no explicit risk controls. `GreyRiskManager` now adds daily loss gating, position sizing, and 50 percent adverse premium stop logic.
6. Angel One access relied on private helper reflection. GREY now uses public adapter methods only and logs: "Angel One session expired, restart system" when public calls fail.

## What To Keep

- Efficacy tracking, because it creates evidence before trading decisions.
- Data quality guard, because bad inputs should cap confidence or freeze contribution.
- Safe error handling, because live shadow-mode loops must not crash on one bad provider.
- Modular architecture, because individual modules can be measured, cut, or reweighted.

## Decision Framework

- Directional shadow-mode accuracy below 55 percent: stop directional use.
- Range-bound shadow-mode accuracy below 70 percent: stop Iron Condor use.
- Directional accuracy from 55 to 60 percent: redesign before paper trading.
- Range-bound accuracy from 60 to 70 percent: redesign before paper trading.
- Directional accuracy above 65 percent or range-bound accuracy above 70 percent: proceed to paper trading review.

## Gemini A/B Decision

Week 1 and Week 2 baseline should run with `GREY_GEMINI_ENABLED=False`. Week 3 can enable Gemini or keep `GREY_A_B_TEST_MODE=True` to log Gemini-on and Gemini-off variants. If Gemini improves accuracy by more than 5 percentage points, keep it. If lift is 5 points or less, disable it permanently.

## Weight Learning Plan

After 4 weeks of shadow-mode data, collect 20 daily efficacy records and the corresponding module score vectors. Run `LogisticWeightOptimizer.optimize(efficacy_reports, module_scores)`. Store results in `learned_module_weights.json`, compare learned weights with guessed weights, and use learned weights for Week 5+ paper-trading evaluation.

## Module Simplification Plan

Keep all modules during shadow mode to measure effectiveness. After analysis, simplify to six core modules if the data supports it:

- Keep: `REGIME`, `VIX_REGIME`, `OPTIONS_FLOW`, `PCR`, `EXPIRY_CYCLE`, `GLOBAL`.
- Cut or demote: `KRONOS`, `INDIA_MACRO`, `SECTOR`, `OI_CHANGE`, `MICROSTRUCTURE`, and GREY 2.0 extras except `OPTIONS_FLOW`.
