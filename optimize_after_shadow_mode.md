# Optimize After Shadow Mode

1. Extract 20 days of efficacy data from `daily_reports/efficacy_YYYY-MM-DD.json` and signal journals.
2. Extract matching module scores from `journals/grey/phase1_signals.jsonl` and `journals/grey/enhanced_signals.jsonl`.
3. Run `LogisticWeightOptimizer.optimize(efficacy_reports, module_scores)`.
4. Save learned output to `learned_module_weights.json`.
5. Compare learned weights to the current guessed weights in `GreySignalAggregator.DEFAULT_CONFIG` and `GreyEnhancedPhase1Engine.ENHANCED_AGGREGATOR_CONFIG`.
6. Identify modules that contributed most to correct range-bound predictions.
7. Document findings in the Week 5 review notes.
8. Plan simplification to six core modules: `REGIME`, `VIX_REGIME`, `OPTIONS_FLOW`, `PCR`, `EXPIRY_CYCLE`, and `GLOBAL`.
9. Implement the simplified version only after the data supports cutting weaker modules.
