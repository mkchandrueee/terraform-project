@echo off
REM Put the whole suite on your phone from ANYWHERE - no wifi sharing, works on
REM mobile data. One process serves the app and the API; cloudflared publishes
REM it as an https address.
REM
REM Needs cloudflared once:  winget install --id Cloudflare.cloudflared
setlocal
cd /d "%~dp0"

where node >/dev/null 2>nul
if errorlevel 1 (
  echo Node.js was not found on PATH.
  echo Install the LTS build from https://nodejs.org then run this again.
  pause
  exit /b 1
)

where cloudflared >/dev/null 2>nul
if errorlevel 1 (
  echo cloudflared was not found on PATH.
  echo Install it once with:  winget install --id Cloudflare.cloudflared
  echo Then run this file again.
  pause
  exit /b 1
)

REM A fresh secret each run, so an old link stops working.
set TOKEN=
for /f %%t in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString(\"N\").Substring(0,20)"') do set TOKEN=%%t
if "%TOKEN%"=="" set TOKEN=change-me-please

echo Starting the suite on port 8123 (app + API, token protected)...
start "Option Suite" cmd /k "node tools\nse-fetch.js --serve --token %TOKEN%"

timeout /t 2 /nobreak >nul

echo.
echo ================================================================
echo   Your one-time secret for this run:
echo     %TOKEN%
echo ================================================================
echo.
echo cloudflared is starting. It prints a line like
echo     https://random-words-here.trycloudflare.com
echo.
echo On your iPhone, open that address with the secret on the end:
echo     https://random-words-here.trycloudflare.com/?token=%TOKEN%
echo.
echo Safari remembers it after the first load, so Add to Home Screen
echo then works without the secret. Because it is https, notifications
echo work too once you install it to the Home Screen.
echo.
echo Keep BOTH windows open. Closing them takes the link offline.
echo ================================================================
echo.

cloudflared tunnel --url http://127.0.0.1:8123
pause
