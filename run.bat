@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
    python bootstrap.py %*
) else (
    py -3 bootstrap.py %*
)
if errorlevel 1 echo Ошибка запуска. Проверь Python 3.10+ и интернет.
pause
