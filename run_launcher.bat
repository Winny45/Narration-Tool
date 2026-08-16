@echo off
if exist venv\Scripts\pythonw.exe (
    start "" venv\Scripts\pythonw.exe launcher_gui.py
) else (
    call venv\Scripts\activate
    python launcher_gui.py
)
