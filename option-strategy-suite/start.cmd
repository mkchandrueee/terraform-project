@echo off
REM Start the NSE helper AND the app together, then open the browser.
setlocal
cd /d "%~dp0"

where node >/dev/null 2>nul
if errorlevel 1 (
  echo Node.js was not found on PATH.
  echo Install the LTS build from https://nodejs.org then run this again.
  pause
  exit /b 1
)

echo Starting the NSE helper on port 8123...
start "NSE helper" cmd /k "node tools\nse-fetch.js"

echo Starting the app on port 8787...
start "Option Suite" cmd /k "node tools\serve.js 8787"

timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8787

echo.
echo Two windows opened - keep both running while you trade.
echo Close them to stop.
echo.
pause
