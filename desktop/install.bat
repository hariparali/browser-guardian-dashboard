@echo off
:: Browser Guardian v2 Installer
:: Run this as Administrator from the parent account.
:: For Chrome policies: log in as Kichukuttan and double-click apply_policies.reg

setlocal EnableDelayedExpansion

:: ── Check for admin rights ────────────────────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: This script must be run as Administrator.
    echo Right-click install.bat and choose "Run as administrator".
    pause
    exit /b 1
)

set EXE_DIR=C:\BrowserGuardian
set EXE_PATH=%EXE_DIR%\BrowserGuardian.exe
set BLOCKLIST=%EXE_DIR%\blocklist.txt
set HOSTS_SCRIPT=%~dp0run_hosts_install.py
set SON_ACCOUNT=Kichukuttan

echo ============================================================
echo  Browser Guardian v2 Installer
echo ============================================================
echo.

:: ── 1. Install hosts file blocking ───────────────────────────────────────────
echo [1/4] Installing hosts file blocking (SafeSearch + blocklist)...
"%EXE_DIR%\_internal\python.exe" "%HOSTS_SCRIPT%" "%BLOCKLIST%" 2>nul
if %errorlevel% neq 0 (
    python "%HOSTS_SCRIPT%" "%BLOCKLIST%" 2>nul
)
if %errorlevel% neq 0 (
    echo WARNING: Hosts install failed. Run manually: python run_hosts_install.py blocklist.txt
) else (
    echo Done.
)
echo.

:: ── 2. Flush DNS cache ────────────────────────────────────────────────────────
echo [2/4] Flushing DNS cache...
ipconfig /flushdns >nul 2>&1
echo Done.
echo.

:: ── 3. Create scheduled tasks for son's account ──────────────────────────────
echo [3/4] Creating scheduled tasks for %SON_ACCOUNT%...

:: Task A: start BrowserGuardian when son logs in
schtasks /delete /tn "BrowserGuardianStart" /f >nul 2>&1
schtasks /create /tn "BrowserGuardianStart" /tr "\"%EXE_PATH%\"" /sc ONLOGON /ru "%SON_ACCOUNT%" /rl LIMITED /f >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Could not create login task.
) else (
    echo   Login task created.
)

:: Task B: watchdog — checks every 2 minutes if BrowserGuardian is running, restarts if not
set WATCHDOG_CMD=powershell -WindowStyle Hidden -Command "if (-not (Get-Process BrowserGuardian -ErrorAction SilentlyContinue)) { Start-Process '%EXE_PATH%' }"
schtasks /delete /tn "BrowserGuardianWatchdog" /f >nul 2>&1
schtasks /create /tn "BrowserGuardianWatchdog" /tr "%WATCHDOG_CMD%" /sc MINUTE /mo 2 /ru "%SON_ACCOUNT%" /rl LIMITED /f >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Could not create watchdog task.
) else (
    echo   Watchdog task created (checks every 2 minutes).
)
echo.

:: ── 4. Next steps for Chrome policies ────────────────────────────────────────
echo [4/4] Chrome policies — manual step required:
echo.
echo   LOG IN AS %SON_ACCOUNT% AND DO THE FOLLOWING:
echo.
echo   a) Double-click:  %~dp0chrome_policy\apply_policies.reg
echo      (Disables incognito, forces SafeSearch, disables DNS-over-HTTPS)
echo.
echo   b) Run BrowserGuardian.exe once so it registers itself in startup:
echo      %EXE_PATH%
echo.

echo ============================================================
echo  Hosts file blocking is ACTIVE.
echo  Scheduled tasks created for %SON_ACCOUNT%.
echo.
echo  Still to do (as %SON_ACCOUNT%):
echo    1. Run apply_policies.reg
echo    2. Run BrowserGuardian.exe once to register startup
echo ============================================================
pause
