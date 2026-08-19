@echo off
REM Start the helper and the app bound to the whole network, so an iPhone or
REM iPad on the same wifi can open them. Prints the address to type on the phone.
setlocal enabledelayedexpansion
cd /d "%~dp0"

where node >/dev/null 2>nul
if errorlevel 1 (
  echo Node.js was not found on PATH.
  echo Install the LTS build from https://nodejs.org then run this again.
  pause
  exit /b 1
)

REM First IPv4 address that is not loopback - the one the phone must use.
set LANIP=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
  for /f "tokens=* delims= " %%b in ("%%a") do (
    if not defined LANIP if not "%%b"=="127.0.0.1" set LANIP=%%b
  )
)
if not defined LANIP set LANIP=your-pc-ip

echo Starting the NSE helper on port 8123 (all interfaces)...
start "NSE helper" cmd /k "run-helper.cmd --host 0.0.0.0"

echo Starting the app on port 8787 (all interfaces)...
start "Option Suite" cmd /k "node tools\serve.js 8787 lan"

timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8787

echo.
echo ================================================================
echo   On this PC      http://127.0.0.1:8787
echo   On your iPhone  http://!LANIP!:8787
echo ================================================================
echo.
echo Type that second address into Safari. The app finds the helper on
echo the same PC by itself - you should not need to change any address.
echo.
echo If Safari cannot reach it, Windows Firewall is blocking Node. Run
echo this ONCE in an Administrator Command Prompt:
echo.
echo   netsh advfirewall firewall add rule name="Option Suite" dir=in ^
action=allow protocol=TCP localport=8787,8123
echo.
echo Keep both windows running while you trade. Close them to stop.
echo.
pause
