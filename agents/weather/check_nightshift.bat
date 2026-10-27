@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
python check_nightshift.py > nightshift_check.txt 2>&1
type nightshift_check.txt
echo.
echo Press any key to close.
pause >nul
