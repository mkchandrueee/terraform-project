@echo off
REM Keeps the NSE helper running. If it ever exits - a crash, a stray Ctrl+C,
REM Windows putting the machine to sleep - this starts it again, so the app
REM stops showing "No helper at 127.0.0.1:8123".
REM
REM Close this window to stop it for good.
setlocal
cd /d "%~dp0"

:loop
echo.
echo === NSE helper starting at %TIME% ===
node tools\nse-fetch.js %*
if errorlevel 1 (
  echo.
  echo The helper exited with an error. If the port is already in use, another
  echo copy is probably still running - close the other window, or start this
  echo one on a different port:  run-helper.cmd --port 8124
  echo Retrying in 10 seconds. Close this window to stop.
  timeout /t 10 /nobreak >nul
) else (
  echo.
  echo Helper stopped. Restarting in 3 seconds. Close this window to stop.
  timeout /t 3 /nobreak >nul
)
goto loop
