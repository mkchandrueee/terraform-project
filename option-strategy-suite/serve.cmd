@echo off
REM Start the app only. Double-click this file.
setlocal
cd /d "%~dp0"

where node >/dev/null 2>nul
if errorlevel 1 (
  echo Node.js was not found on PATH.
  echo Install the LTS build from https://nodejs.org then run this again.
  pause
  exit /b 1
)

set PORT=%1
if "%PORT%"=="" set PORT=8787

start "" http://127.0.0.1:%PORT%
node tools\serve.js %PORT%
pause
