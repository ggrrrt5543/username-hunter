@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 bootstrap.py %*
goto finished
:use_python
python bootstrap.py %*
:finished
set "HUNTER_EXIT=%ERRORLEVEL%"
if not "%HUNTER_EXIT%"=="0" echo Launch failed. Check Python 3.10+ and your internet connection.
pause
endlocal & exit /b %HUNTER_EXIT%
