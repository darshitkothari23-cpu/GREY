# PRE-SHADOW-MODE CHECKLIST (Non-Negotiable)

1. Download 3 months NIFTY 1-minute data, or generate synthetic data only for software testing.
2. Run: `python grey_backtest_runner.py --data nifty_3months.csv`.
3. Check output: is `ev_simulated` positive or negative?
4. If backtest EV is negative: the system may not work. You can still run shadow mode to confirm.
5. If backtest EV is positive: proceed with more confidence, but still treat GREY as a hypothesis.
6. Verify VIX caching: 60 seconds normally, 20 seconds if VIX is above 20.
7. Verify position sizing includes VIX scaling: `position_size(0.7, 25)` should be below 2 lots.
8. Verify stop loss is time-weighted: 50 percent first 30 minutes, 75 percent from 30 to 120 minutes, 100 percent after 120 minutes.
9. Verify parallel A/B testing: run the system for 30 minutes and check that both baseline and Gemini are logged per signal.
10. Run `pytest test_pre_shadow_mode.py`: all 9 tests must pass.
11. Run the system in dummy mode for 1 hour and verify EV, accuracy, VIX scaling, and stop-loss metrics calculate correctly.
12. Final check: do you understand that there is a 75 percent probability this system will not work? If yes, proceed. If no, reconsider.

You are now ready for shadow mode only after the backtest is complete, this checklist passes, all tests pass, and the operator confirms the 75 percent failure-risk assumption.
