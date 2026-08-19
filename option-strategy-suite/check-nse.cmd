@echo off
REM Does the NSE fetch work on this machine? Run during market hours.
setlocal
cd /d "%~dp0"
node tools\nse-fetch.js --check
echo.
pause
