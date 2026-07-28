@echo off
REM Double-click this to open the app. First run installs the requirements.
cd /d "%~dp0"

if not exist ".venv\" (
    echo First-time setup: creating environment and installing components...
    python -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

python gui.py
if errorlevel 1 pause
