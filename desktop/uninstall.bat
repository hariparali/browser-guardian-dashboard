@echo off
:: Browser Guardian v2 Uninstaller — full clean reversal
:: Run as Administrator

setlocal EnableDelayedExpansion

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Run as Administrator.
    pause
    exit /b 1
)

set SCRIPT_DIR=%~dp0

echo ============================================================
echo  Browser Guardian v2 Uninstaller
echo ============================================================
echo.

:: ── 1. Restore hosts file ────────────────────────────────────────────────────
echo [1/4] Restoring hosts file...
python "%SCRIPT_DIR%run_hosts_uninstall.py"
ipconfig /flushdns >nul 2>&1
echo Done.
echo.

:: ── 2. Remove scheduled task ──────────────────────────────────────────────────
echo [2/4] Removing watchdog scheduled task...
schtasks /delete /tn "BrowserGuardianWatchdog" /f >nul 2>&1
echo Done.
echo.

:: ── 3. Remove Chrome policies (in son's account) ─────────────────────────────
echo [3/4] Chrome policies...
echo To remove Chrome policies:
echo   1. Log in as son's account
echo   2. Double-click: %SCRIPT_DIR%chrome_policy\remove_policies.reg
echo.

:: ── 4. Kill BrowserGuardian ───────────────────────────────────────────────────
echo [4/4] Stopping BrowserGuardian...
taskkill /f /im BrowserGuardian.exe >nul 2>&1
echo Done.
echo.

echo ============================================================
echo  Uninstall complete. All browser restrictions removed.
echo ============================================================
pause
