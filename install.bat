@echo off
setlocal

echo ============================================================
echo  DM Reader - Installer
echo ============================================================

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on your PATH.
    echo Install it from https://www.python.org/downloads/ ^(check
    echo "Add python.exe to PATH" during setup^), then run this again.
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv venv

echo Installing packages ^(this can take a couple of minutes^)...
call venv\Scripts\pip install --upgrade pip
call venv\Scripts\pip install -r requirements.txt

echo.
echo ============================================================
echo  One more manual step: install Tesseract-OCR
echo ============================================================
echo This tool reads the small text on your screen, and it needs
echo Tesseract-OCR installed to do that.
echo.
echo 1. Download the installer from:
echo    https://github.com/UB-Mannheim/tesseract/wiki
echo 2. Run it and keep the default install location.
echo 3. That's it - DM Reader will find it automatically.
echo.
echo Once that's done, double-click run.bat to start the app.
echo It will ask for your ElevenLabs API key and Voice ID the
echo first time it runs.
echo ============================================================
pause
