@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m src.zzEXE
) else (
    start "" "venv\Scripts\pythonw.exe" -m src.zzEXE
)
exit /b
