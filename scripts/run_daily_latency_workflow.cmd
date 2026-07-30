@echo off
cd /d %~dp0..
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    call venv\Scripts\activate.bat
)
python -m scripts.run_daily_latency_workflow %*
pause
