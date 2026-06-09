@echo off
reg add "HKCU\SOFTWARE\Policies\Google\Chrome" /v DnsOverHttpsMode /t REG_SZ /d "off" /f
reg add "HKCU\SOFTWARE\Policies\Google\Chrome" /v ForceGoogleSafeSearch /t REG_DWORD /d 1 /f
reg add "HKCU\SOFTWARE\Policies\Google\Chrome" /v ForceYouTubeRestrict /t REG_DWORD /d 2 /f
reg add "HKCU\SOFTWARE\Policies\Google\Chrome" /v IncognitoModeAvailability /t REG_DWORD /d 1 /f
echo Done. Chrome policies applied.
pause
