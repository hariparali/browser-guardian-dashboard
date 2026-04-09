@echo off
echo ============================================
echo  Browser Guardian — Build Installer
echo ============================================
echo.

echo [1/3] Installing build dependencies...
pip install pyinstaller pillow pystray psutil uiautomation requests --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Make sure Python is on PATH.
    pause & exit /b 1
)

echo [2/3] Building EXE with PyInstaller...
pyinstaller browser_guardian.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. See output above.
    pause & exit /b 1
)

echo [3/3] Copying config template...
if not exist "dist\BrowserGuardian\config.json" (
    copy config.json "dist\BrowserGuardian\config.json" >nul 2>&1
)

echo.
echo ============================================
echo  BUILD COMPLETE
echo  Output: desktop\dist\BrowserGuardian\
echo  Run:    dist\BrowserGuardian\BrowserGuardian.exe
echo ============================================
pause
