@echo off
REM Default Y05601: scripts\run_daily_latency_workflow_no_greeksoft.cmd --date 20260811
REM Best client:    scripts\run_daily_latency_workflow_no_greeksoft.cmd --date 20260811 --client-mode best
REM Worst client:   scripts\run_daily_latency_workflow_no_greeksoft.cmd --date 20260811 --client-mode worst

cd /d %~dp0..
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    call venv\Scripts\activate.bat
)
python -m scripts.run_daily_latency_workflow --no-greeksoft %*
pause
