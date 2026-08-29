@echo off
setlocal
echo ============================================
echo  BrowserGuardian - New PC Setup
echo ============================================
echo.

REM Must be run as Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Please right-click this file and choose "Run as administrator"
    pause
    exit /b 1
)

REM ── Resolve the ACTUAL interactive logged-on user ──────────────────────────
REM If the account you're setting this up for is a Standard User, UAC requires
REM a DIFFERENT admin account's credentials to elevate this script — and that
REM makes this process's own HKCU point at the ADMIN's registry hive, not the
REM logged-on user's. Writing to bare HKCU below would silently misconfigure
REM the wrong account (this exact bug happened once before with a Chrome
REM policy .reg file). So resolve the real interactive user's SID and target
REM HKU\<SID> explicitly instead of trusting HKCU.
echo Detecting the currently logged-on user...
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).UserName"`) do set "LOGON_ACCOUNT=%%U"
if not defined LOGON_ACCOUNT (
    echo ERROR: Could not determine the currently logged-on user.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%S in (`powershell -NoProfile -Command "([System.Security.Principal.NTAccount]'%LOGON_ACCOUNT%').Translate([System.Security.Principal.SecurityIdentifier]).Value"`) do set "LOGON_SID=%%S"
if not defined LOGON_SID (
    echo ERROR: Could not resolve SID for %LOGON_ACCOUNT%
    pause
    exit /b 1
)

reg query "HKU\%LOGON_SID%" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: %LOGON_ACCOUNT%'s registry hive isn't loaded ^(HKU\%LOGON_SID%^).
    echo Make sure you're logged in as the child's account on THIS machine
    echo ^(not just elevating with a different admin login^), then re-run this.
    pause
    exit /b 1
)

echo   Target account: %LOGON_ACCOUNT%  (SID %LOGON_SID%)
set "HIVE=HKU\%LOGON_SID%"
echo.

REM 1. Register auto-start (launches on every login for the target account)
echo [1/5] Registering startup...
reg add "%HIVE%\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "BrowserGuardian" /t REG_SZ /d "\"C:\Windows\System32\wscript.exe\" \"C:\BrowserGuardian\launcher.vbs\"" /f
if %errorlevel% neq 0 (
    echo FAILED - could not write to registry
    pause
    exit /b 1
)
echo       OK

REM 2. Chrome SafeSearch + disable incognito + disable DoH
echo [2/5] Applying Chrome policies...
reg add "%HIVE%\SOFTWARE\Policies\Google\Chrome" /v "ForceGoogleSafeSearch"      /t REG_DWORD /d 1     /f
reg add "%HIVE%\SOFTWARE\Policies\Google\Chrome" /v "IncognitoModeAvailability"  /t REG_DWORD /d 1     /f
reg add "%HIVE%\SOFTWARE\Policies\Google\Chrome" /v "ForceYouTubeRestrict"       /t REG_DWORD /d 2     /f
reg add "%HIVE%\SOFTWARE\Policies\Google\Chrome" /v "DnsOverHttpsMode"           /t REG_SZ    /d "off" /f
echo       OK

REM 3. Edge SafeSearch + disable InPrivate + disable DoH
echo [3/5] Applying Edge policies...
reg add "%HIVE%\SOFTWARE\Policies\Microsoft\Edge" /v "ForceGoogleSafeSearch"   /t REG_DWORD /d 1     /f
reg add "%HIVE%\SOFTWARE\Policies\Microsoft\Edge" /v "InPrivateModeAvailability" /t REG_DWORD /d 1   /f
reg add "%HIVE%\SOFTWARE\Policies\Microsoft\Edge" /v "ForceYouTubeRestrict"    /t REG_DWORD /d 2     /f
reg add "%HIVE%\SOFTWARE\Policies\Microsoft\Edge" /v "DnsOverHttpsMode"        /t REG_SZ    /d "off" /f
echo       OK

REM 4. Adult domain blocking via hosts file (self-contained - no system Python needed)
echo [4/5] Applying hosts file blocks...
if exist "C:\BrowserGuardian\BrowserGuardian.exe" if exist "C:\BrowserGuardian\blocklist.txt" (
    "C:\BrowserGuardian\BrowserGuardian.exe" --install-hosts "C:\BrowserGuardian\blocklist.txt"
    if %errorlevel% equ 0 (
        echo       OK
    ) else (
        echo       FAILED - hosts install returned an error ^(non-critical, continuing^)
    )
) else (
    echo       SKIPPED - BrowserGuardian.exe or blocklist.txt not found ^(non-critical^)
)

REM 5. Launch BrowserGuardian now
echo [5/5] Starting BrowserGuardian...
start "" "C:\Windows\System32\wscript.exe" "C:\BrowserGuardian\launcher.vbs"
echo       OK

echo.
echo ============================================
echo  Setup complete!
echo  - Applied to account: %LOGON_ACCOUNT%
echo  - BrowserGuardian is now running
echo  - It will auto-start on every login
echo  - Look for tray icon (bottom-right)
echo  - Logs: C:\BrowserGuardian\browser_guardian.log
echo ============================================
echo.
pause
