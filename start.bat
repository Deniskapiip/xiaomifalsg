@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found. Read STAGE-4-WINDOWS.md and create .venv first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "scripts\dev.py" %*
set "TAOJI_EXIT_CODE=%ERRORLEVEL%"
if not "%TAOJI_EXIT_CODE%"=="0" pause
exit /b %TAOJI_EXIT_CODE%
