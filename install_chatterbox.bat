@echo off
setlocal

echo ============================================================
echo  DM Reader - Chatterbox local voice setup
echo ============================================================
echo Chatterbox needs Python 3.11 specifically, in its own virtual
echo environment kept separate from DM Reader's main one (which can
echo be a newer Python version - that's fine, they don't conflict).
echo.
echo This will also download 1-2GB of packages and, the first time
echo you run it, a similarly sized model file. Make sure you're on
echo a connection you don't mind using for that.
echo.

py -3.11 --version >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 was not found via the "py" launcher.
    echo.
    echo Install it from:
    echo   https://www.python.org/downloads/release/python-3119/
    echo ^(scroll down to Files, grab "Windows installer ^(64-bit^)"^)
    echo.
    echo You can leave "Add to PATH" unchecked during that install if
    echo you like - this script uses the "py -3.11" launcher directly,
    echo which works either way. Once installed, run this file again.
    pause
    exit /b 1
)

echo Found Python 3.11. Creating its virtual environment...
cd chatterbox_server
py -3.11 -m venv venv

echo Installing packages ^(this is the slow part - please wait^)...
call venv\Scripts\pip install --upgrade pip
call venv\Scripts\pip install -r requirements.txt

echo.
echo ============================================================
echo Setup complete.
echo.
echo Next: double-click run_chatterbox.bat and leave that window
echo open. The first time, it'll download the model itself (another
echo 1-2GB) - wait for it to print "Chatterbox is ready" before
echo switching to it in DM Reader Settings.
echo ============================================================
pause
