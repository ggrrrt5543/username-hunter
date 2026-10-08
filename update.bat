@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
    python updater.py %*
) else (
    py -3 updater.py %*
)
pause
