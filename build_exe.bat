@echo off
setlocal

echo ============================================================
echo  DM Reader - Build standalone .exe files
echo ============================================================
echo This packages DMReader.exe and DMReaderSettings.exe so you
echo can run the app without opening a terminal or activating the
echo virtual environment every time.
echo.

if not exist venv (
    echo No venv folder found - run install.bat first.
    pause
    exit /b 1
)

call venv\Scripts\pip install pyinstaller

echo.
echo Building DMReader.exe ...
call venv\Scripts\pyinstaller --onefile --console --name DMReader main.py

echo.
echo Building DMReaderSettings.exe ...
call venv\Scripts\pyinstaller --onefile --windowed --name DMReaderSettings settings_gui.py

echo.
echo Building DMReaderLauncher.exe (the all-in-one GUI) ...
call venv\Scripts\pyinstaller --onefile --windowed --name DMReaderLauncher launcher_gui.py

echo.
echo ============================================================
echo Copying exe files into this folder for convenience...
copy /Y dist\DMReader.exe . >nul
copy /Y dist\DMReaderSettings.exe . >nul
copy /Y dist\DMReaderLauncher.exe . >nul

echo Done! DMReader.exe, DMReaderSettings.exe, and DMReaderLauncher.exe
echo are in this folder. DMReaderLauncher.exe is the one to pin to your
echo taskbar/desktop for everyday use - it can start/stop the reader
echo and open Settings, all from one window.
echo (The venv, .spec files, and build/ dist/ folders can be deleted
echo  if you want to tidy up, they're only needed for rebuilding.)
echo ============================================================
pause
