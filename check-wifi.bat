@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title PiDiagOS - find web panel

rem Checks Wi-Fi and opens the PiDiagOS web panel in a browser.
rem Run by double-clicking. The /nobrowser argument only displays the address.

set "OPEN=1"
if /I "%~1"=="/nobrowser" set "OPEN=0"

echo.
echo  ============================================
echo  PiDiagOS - connection check
echo  ============================================
echo.

rem --- 1. Wi-Fi -------------------------------------------------------------
set "SSID="
for /f "tokens=1,* delims=:" %%A in ('netsh wlan show interfaces 2^>nul ^| findstr /C:"SSID" ^| findstr /V /C:"BSSID"') do (
    if not defined SSID set "SSID=%%B"
)
if defined SSID for /f "tokens=* delims= " %%A in ("!SSID!") do set "SSID=%%A"
if not defined SSID set "SSID="

if defined SSID (
    echo  Wi-Fi: connected to "!SSID!"
) else (
    echo  Wi-Fi: no wireless connection found
)

rem --- 2. Default gateway --------------------------------------------------
set "GW="
for /f "tokens=3" %%A in ('route print -4 ^| findstr /R /C:"^ *0.0.0.0 *0.0.0.0 "') do if not defined GW set "GW=%%A"
if defined GW echo  Default gateway: !GW!

rem --- 3. Find panel -------------------------------------------------------
set "HOST="
set "HINT="

if /I "!SSID!"=="PiDiagOS" (
    call :probe 192.168.50.1 && set "HOST=192.168.50.1"
    if defined HOST set "HINT=the board is broadcasting its own Wi-Fi network"
)
if not defined HOST call :probe pidiag.local && set "HOST=pidiag.local"
if not defined HOST call :probe pidiag && set "HOST=pidiag"
if not defined HOST if defined GW call :probe !GW! && set "HOST=!GW!"
if not defined HOST call :probe 192.168.50.1 && set "HOST=192.168.50.1"

if not defined HOST goto :notfound

echo.
echo  Panel found: http://!HOST!/
if defined HINT echo  !HINT!
echo  Login: Admin / PiDiagOS (unless changed during build)
echo.

if "!OPEN!"=="0" goto :done
start "" "http://!HOST!/"
echo  Page opened in your browser.
goto :done

:notfound
echo.
echo  Panel not found. Check:
echo   1. The board is powered on and its green LED is blinking.
echo   2. The computer is connected to "PiDiagOS" or the same network as the board.
echo   3. The board has finished booting - this can take up to 60 seconds.
echo.
echo  If the "PiDiagOS" network is not visible, connect the board to your router by Ethernet
echo  and find its address in the router's client list.
goto :done

:probe
rem %1 - address; success if the HTTP server responds (401 counts as a response)
where curl >nul 2>&1
if errorlevel 1 goto :probe_powershell
curl -s -m 3 -o NUL "http://%~1/" >nul 2>&1
exit /b %errorlevel%

:probe_powershell
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://%~1/' -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop; exit 0 } catch { if ($_.Exception.Response) { exit 0 } else { exit 1 } }" >nul 2>&1
exit /b %errorlevel%

:done
echo.
pause
endlocal
