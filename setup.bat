@echo off
echo ============================================================
echo  Browser Guardian — Desktop App Setup
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

echo Installing desktop dependencies...
cd /d "%~dp0desktop"
pip install -r requirements.txt

echo.
echo ============================================================
echo  Setup complete!
echo.
echo  BEFORE FIRST RUN:
echo    1. Open Settings from the tray icon and set your password.
echo    2. Add your Supabase URL + Key in Settings.
echo.
echo  TO START THE APP:
echo    cd desktop
echo    python main.py
echo.
echo  The app will appear as a shield icon in the system tray.
echo ============================================================
pause
