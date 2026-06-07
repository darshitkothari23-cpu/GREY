@echo off
title GREY + Kronos Shadow Mode
echo ==========================================
echo Starting GREY Phase 1 Shadow Mode with Kronos...
echo This window will stay open if an error happens.
echo ==========================================

REM Activate the local virtual environment if it exists.
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo WARNING: .venv was not found. Using the default Python on PATH.
)

REM Run the live GREY forward tester.
python grey_live_forward_tester.py

REM Pause so you can read any error message before the window closes.
if errorlevel 1 (
    echo.
    echo GREY stopped with an error. Read the message above.
)
pause
